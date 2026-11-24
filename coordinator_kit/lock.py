"""A fair machine lock: first come, first served, exclusive or shared, safe when holders crash.

Why not a plain file lock: ``flock`` is not fair. An agent that releases and immediately relaunches
can take the lock again ahead of a job that has been waiting; in practice one job waited about 70
minutes that way. Here every waiter takes a numbered ticket and only the head of the queue may enter.

* **exclusive** (heavy jobs, GPU work, timing): runs alone.
* **shared** (tests, short scripts): runs beside other shared holders, but never beside an exclusive
  holder, and never jumps ahead of an exclusive ticket that is already waiting, so a stream of short
  commands cannot starve a heavy job.

Tickets and holders are small files under ``<home>/locks/<name>/``. A ticket or hold whose process
has died (checked with the PID and its start time, so a reused PID does not count) is dropped the
next time anyone looks, so a crashed holder never wedges the machine.

Nesting is refused: a process that already holds a lock and asks for it again would wait for itself.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import procs
from .home import check_name, home, mutex, read_json


class LockTimeout(TimeoutError):
    pass


class NestedLock(RuntimeError):
    pass


class LockCancelled(RuntimeError):
    pass


@dataclass
class Entry:
    file: str
    pid: int
    ident: str | None
    mode: str
    label: str
    since: float

    @property
    def order(self) -> str:
        return self.file


def lock_dir(name: str = "machine", root=None) -> Path:
    return home(root) / "locks" / check_name(name, "lock name")


def _entries(folder: Path) -> list[Entry]:
    out = []
    for path in sorted(folder.glob("*.json")):
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        out.append(Entry(path.name, int(data.get("pid", 0)), data.get("ident"), data.get("mode", "exclusive"),
                         data.get("label", ""), float(data.get("since", 0))))
    return out


def _purge(folder: Path) -> list[Entry]:
    """Drop entries of dead processes; return the live ones in order."""
    live = []
    for entry in _entries(folder):
        if procs.alive(entry.pid, entry.ident):
            live.append(entry)
        else:
            try:
                (folder / entry.file).unlink()
            except FileNotFoundError:
                pass
    return live


def state(name: str = "machine", root=None) -> dict:
    """Current holders and queue (dead entries are dropped first)."""
    base = lock_dir(name, root)
    with mutex(base / ".mutex"):
        holders = _purge(base / "holders") if (base / "holders").exists() else []
        queue = _purge(base / "queue") if (base / "queue").exists() else []
    return {"name": name, "holders": [e.__dict__ for e in holders], "queue": [e.__dict__ for e in queue]}


class FairLock:
    """``with FairLock(shared=False, label='bench'):`` ... ; or ``acquire()`` / ``release()``."""

    def __init__(self, name: str = "machine", shared: bool = False, label: str = "", timeout: float | None = None,
                 root=None, poll: float = 0.5, progress=None, cancel=None):
        self.base = lock_dir(name, root)
        self.mode = "shared" if shared else "exclusive"
        self.label, self.timeout, self.poll, self.progress = label, timeout, poll, progress
        self.cancel = cancel
        self.ticket: str | None = None
        self.held = False

    # -- internals ---------------------------------------------------------------------------------------
    def _grantable(self, holders: list[Entry], queue: list[Entry]) -> tuple[bool, str]:
        ahead = [e for e in queue if e.order < self.ticket]
        if self.mode == "exclusive":
            if holders:
                return False, "held by " + ", ".join(f"{h.label or h.pid} ({h.mode})" for h in holders)
            if ahead:
                return False, f"{len(ahead)} ahead: {ahead[0].label or ahead[0].pid}"
            return True, ""
        if any(h.mode == "exclusive" for h in holders):
            h = next(h for h in holders if h.mode == "exclusive")
            return False, f"held by {h.label or h.pid} (exclusive)"
        waiting_ex = [e for e in ahead if e.mode == "exclusive"]
        if waiting_ex:
            return False, f"exclusive job queued ahead: {waiting_ex[0].label or waiting_ex[0].pid}"
        return True, ""

    def _try(self) -> tuple[bool, str]:
        with mutex(self.base / ".mutex"):
            holders = _purge(self.base / "holders")
            queue = _purge(self.base / "queue")
            ok, why = self._grantable(holders, queue)
            if ok:
                os.replace(self.base / "queue" / self.ticket, self.base / "holders" / self.ticket)
                self.held = True
            return ok, why

    # -- API ---------------------------------------------------------------------------------------------
    def acquire(self) -> "FairLock":
        for sub in ("queue", "holders"):
            (self.base / sub).mkdir(parents=True, exist_ok=True)
        pid, ident = procs.me()
        with mutex(self.base / ".mutex"):
            for h in _purge(self.base / "holders"):
                if h.pid == pid and h.ident == ident:
                    raise NestedLock(f"this process already holds lock {self.base.name!r} ({h.mode}); never nest it")
            self.ticket = f"{time.time_ns():020d}-{pid}-{uuid.uuid4().hex[:6]}.json"
            (self.base / "queue" / self.ticket).write_text(json.dumps(
                {"pid": pid, "ident": ident, "mode": self.mode, "label": self.label, "since": time.time()}),
                encoding="utf-8")
        started, told = time.monotonic(), None
        try:
            while True:
                ok, why = self._try()
                if ok:
                    return self
                if self.progress and why != told:
                    self.progress(f"LOCK_QUEUE_WAIT {why}")
                    told = why
                if self.cancel and self.cancel():
                    raise LockCancelled(f"wait for lock {self.base.name!r} cancelled")
                if self.timeout is not None and time.monotonic() - started >= self.timeout:
                    raise LockTimeout(f"lock {self.base.name!r} not granted after {self.timeout:.0f} s ({why})")
                time.sleep(self.poll)
        except BaseException:
            self._drop()
            raise

    def _drop(self) -> None:
        if not self.ticket:
            return
        with mutex(self.base / ".mutex"):
            for sub in ("queue", "holders"):
                try:
                    (self.base / sub / self.ticket).unlink()
                except FileNotFoundError:
                    pass
        self.ticket, self.held = None, False

    def release(self) -> None:
        self._drop()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
