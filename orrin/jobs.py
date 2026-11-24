"""Detached jobs with completion markers.

An agent's turn, terminal or session can end at any time; a long job must not end with it, and the
agent (or the next one) must be able to tell afterwards, from files alone, whether the job finished.

``launch`` writes ``<jobs>/<name>/job.json`` and starts a detached runner that:

1. writes ``<name>.pid`` (PID + start-time identity);
2. waits for the machine lock (exclusive by default, ``shared`` or ``none``), FIFO;
3. waits until enough memory is free (the RAM guard) instead of failing or swapping;
4. runs the command with its output in ``<name>.log``; a line starting ``ERROR ``, ``FATAL `` or
   ``JOB_FATAL `` stops it at once (fail fast); ``PROGRESS n/N`` lines feed the ETA;
5. on success appends ``JOB_COMPLETE <name>`` to the log, and always writes ``<name>.done``:
   ``EXIT=<code> COMPLETE=<0|1> REASON=<why> <time>``.

A job is accepted only with ``COMPLETE=1`` in the marker and ``JOB_COMPLETE <name>`` in the log; an exit
code alone proves nothing (a waiter's exit status can come from the waiter, not the job).

Exit codes the runner adds: 75 = RAM guard gave up, 76 = lock wait timed out, 130 = stopped.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

from . import procs
from .home import check_name, home, iso, read_json, tail_lines, write_json, write_text
from .lock import FairLock, LockCancelled, LockTimeout

FAIL_RE = re.compile(r"^(ERROR|FATAL|JOB_FATAL)\b")
PROGRESS_RE = re.compile(r"PROGRESS\s+(\d+)\s*/\s*(\d+)")
EXIT_RAM, EXIT_LOCK, EXIT_STOPPED = 75, 76, 130


def jobs_dir(out=None, root=None) -> Path:
    path = Path(out) if out else home(root) / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve(job: str, out=None, root=None) -> Path:
    """A job given as a directory path or as a name in the jobs folder."""
    p = Path(job)
    if p.is_dir() and (p / "job.json").exists():
        return p.resolve()
    return jobs_dir(out, root) / check_name(job, "job name")


# --- launching ------------------------------------------------------------------------------------------

def launch(name: str, command: list[str], *, out=None, root=None, cwd=None, env: dict | None = None,
           lock: str = "exclusive", lock_name: str = "machine", lock_timeout_s: float = 7200,
           min_free_mb: int = 0, ram_wait_s: float = 1800, fail_fast: bool = True, smoke: int | None = None,
           lane: str = "", wait_start: float = 5.0) -> dict:
    check_name(name, "job name")
    if not command:
        raise ValueError("no command given")
    if lock not in ("exclusive", "shared", "none"):
        raise ValueError("lock must be exclusive, shared or none")
    folder = jobs_dir(out, root) / name
    try:
        folder.mkdir(parents=True)
    except FileExistsError:
        raise FileExistsError(f"job {name!r} already exists in {folder.parent}; pick a new name") from None
    spec = {
        "name": name, "command": [str(c) for c in command], "cwd": str(Path(cwd or os.getcwd()).resolve()),
        "env": {k: str(v) for k, v in (env or {}).items()}, "lock": lock, "lock_name": lock_name,
        "lock_timeout_s": lock_timeout_s, "min_free_mb": int(min_free_mb), "ram_wait_s": ram_wait_s,
        "fail_fast": fail_fast, "smoke": smoke, "lane": lane, "home": str(home(root)), "created": time.time(),
    }
    write_json(folder / "job.json", spec)
    argv = [sys.executable, "-m", "orrin.jobs", "_run", str(folder)]
    # make the runner importable even when the package is used from a source checkout
    run_env = dict(os.environ)
    pkg_parent = str(Path(__file__).resolve().parents[1])
    run_env["PYTHONPATH"] = os.pathsep.join(p for p in (pkg_parent, run_env.get("PYTHONPATH", "")) if p)
    holder = procs.spawn_detached(argv, cwd=spec["cwd"], env=run_env)
    deadline = time.monotonic() + wait_start
    pid = None
    while time.monotonic() < deadline:
        data = read_json(folder / f"{name}.pid")
        if data:
            pid = data.get("pid")
            break
        time.sleep(0.05)
    return {"name": name, "dir": str(folder), "pid": pid, "holder_pid": holder,
            "log": str(folder / f"{name}.log"), "done": str(folder / f"{name}.done")}


# --- the runner (inside the detached process) -----------------------------------------------------------

class _Runner:
    def __init__(self, folder: Path):
        self.folder = folder
        self.spec = read_json(folder / "job.json")
        self.name = self.spec["name"]
        self.log = open(folder / f"{self.name}.log", "a", encoding="utf-8", errors="replace", buffering=1)
        self.stop_reason: str | None = None
        self.child = None

    def say(self, line: str) -> None:
        self.log.write(line.rstrip("\n") + "\n")

    def phase(self, value: str) -> None:
        write_text(self.folder / f"{self.name}.phase", f"{value} {time.time()}\n")

    def stop_requested(self) -> bool:
        return (self.folder / f"{self.name}.stop").exists()

    def finish(self, code: int, reason: str) -> int:
        complete = code == 0 and reason == "ok"
        if complete:
            self.say(f"JOB_COMPLETE {self.name}")
        write_text(self.folder / f"{self.name}.done",
                   f"EXIT={code} COMPLETE={int(complete)} REASON={reason} {iso()}\n")
        self.phase("done")
        self.log.close()
        return code

    def run(self) -> int:
        pid, ident = procs.me()
        write_json(self.folder / f"{self.name}.pid", {"pid": pid, "ident": ident, "started": time.time()})
        self.say(f"JOB_START {self.name} {iso()} cmd={json.dumps(self.spec['command'])}")
        if not procs.WINDOWS:
            import signal
            signal.signal(signal.SIGTERM, lambda *_: self._request_stop())
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        held = None
        try:
            if self.spec["lock"] != "none":
                self.phase("lock")
                held = FairLock(self.spec["lock_name"], shared=self.spec["lock"] == "shared", label=self.name,
                                timeout=self.spec["lock_timeout_s"], root=self.spec["home"], progress=self.say,
                                cancel=self.stop_requested)
                try:
                    held.acquire()
                except LockCancelled:
                    held = None
                    return self.finish(EXIT_STOPPED, "stopped")
                except LockTimeout as e:
                    held = None
                    self.say(f"LOCK_TIMEOUT {e}")
                    return self.finish(EXIT_LOCK, "lock-timeout")
                self.say(f"LOCK_HELD {self.spec['lock']} {self.spec['lock_name']}")
            code = self._ram_guard()
            if code is not None:
                return code
            if self.stop_requested():
                return self.finish(EXIT_STOPPED, "stopped")
            return self._run_child()
        except Exception:
            self.say("JOB_FATAL runner error:\n" + traceback.format_exc())
            return self.finish(1, "runner-error")
        finally:
            if held:
                held.release()

    def _request_stop(self) -> None:
        write_text(self.folder / f"{self.name}.stop", f"signal {iso()}\n")

    def _ram_guard(self) -> int | None:
        need = self.spec["min_free_mb"]
        if need <= 0:
            return None
        self.phase("ram")
        waited, told = 0.0, False
        while True:
            free = procs.available_mb()
            if free is None or free >= need:
                return None
            if waited >= self.spec["ram_wait_s"]:
                self.say(f"RAM_GUARD_FAILED available={free}MB required={need}MB waited={waited:.0f}s")
                return self.finish(EXIT_RAM, "ram-guard")
            if not told:
                self.say(f"RAM_GUARD_WAIT available={free}MB required={need}MB")
                told = True
            if self.stop_requested():
                return self.finish(EXIT_STOPPED, "stopped")
            time.sleep(5)
            waited += 5

    def _run_child(self) -> int:
        import subprocess
        env = dict(os.environ)
        env.update(self.spec["env"])
        env.update(ORRIN_JOB=self.name, PYTHONUNBUFFERED="1")
        if self.spec.get("smoke"):
            env["ORRIN_SMOKE"] = str(self.spec["smoke"])
        self.phase("running")
        self.child = procs.popen_group(self.spec["command"], cwd=self.spec["cwd"], env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        failed = threading.Event()

        def pump():
            for raw in iter(self.child.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                self.say(line)
                if self.spec["fail_fast"] and FAIL_RE.match(line):
                    failed.set()
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        reason = None
        while self.child.poll() is None:
            if failed.is_set():
                reason = "fail-fast"
            elif self.stop_requested():
                reason = "stopped"
            if reason:
                procs.kill_tree(self.child.pid)
                break
            time.sleep(0.25)
        code = self.child.wait()
        reader.join(timeout=10)
        if reason == "stopped":
            return self.finish(EXIT_STOPPED, "stopped")
        if failed.is_set():
            return self.finish(code or 1, "fail-fast")
        return self.finish(code, "ok" if code == 0 else "failed")


# --- reading state --------------------------------------------------------------------------------------

def parse_done(text: str) -> dict:
    out = {"exit_code": None, "complete": False, "reason": None}
    for token in text.split():
        if token.startswith("EXIT="):
            try:
                out["exit_code"] = int(token[5:])
            except ValueError:
                pass
        elif token.startswith("COMPLETE="):
            out["complete"] = token[9:] == "1"
        elif token.startswith("REASON="):
            out["reason"] = token[7:]
    return out


def progress(lines: list[str]) -> dict | None:
    for line in reversed(lines):
        m = PROGRESS_RE.search(line)
        if m:
            return {"done": int(m.group(1)), "total": int(m.group(2)), "line": line.strip()}
    return None


def status(folder: Path) -> dict:
    """State from the files only: running / waiting-lock / waiting-ram / done / failed / stopped / stalled / missing."""
    folder = Path(folder)
    name = folder.name
    spec = read_json(folder / "job.json", {}) or {}
    rec = {"name": name, "dir": str(folder), "lane": spec.get("lane", ""), "state": "starting",
           "exit_code": None, "complete": False, "reason": None, "pid": None, "progress": None, "eta_s": None,
           "created": spec.get("created")}
    if not (folder / "job.json").exists():
        rec["state"] = "missing"
        return rec
    log = folder / f"{name}.log"
    lines = tail_lines(log)
    rec["progress"] = progress(lines)
    rec["last_line"] = lines[-1] if lines else ""
    done = folder / f"{name}.done"
    if done.exists():
        rec.update(parse_done(done.read_text(encoding="utf-8", errors="replace")))
        rec["marker"] = done.read_text(encoding="utf-8", errors="replace").strip()
        rec["complete"] = rec["complete"] and f"JOB_COMPLETE {name}" in lines
        rec["state"] = "done" if rec["complete"] else ("stopped" if rec["reason"] == "stopped" else "failed")
        rec["acked"] = (folder / f"{name}.ack").exists()
        rec["finished"] = done.stat().st_mtime
        return rec
    pid = read_json(folder / f"{name}.pid")
    if not pid:
        age = time.time() - (spec.get("created") or time.time())
        rec["state"] = "starting" if age < 60 else "stalled"
        return rec
    rec["pid"] = pid.get("pid")
    if not procs.alive(pid.get("pid"), pid.get("ident")):
        rec["state"] = "stalled"  # the runner died without writing its marker (machine restart, kill -9)
        rec["acked"] = (folder / f"{name}.ack").exists()
        return rec
    phase_text = (folder / f"{name}.phase").read_text(encoding="utf-8").split() if (folder / f"{name}.phase").exists() else []
    phase = phase_text[0] if phase_text else "running"
    rec["state"] = {"lock": "waiting-lock", "ram": "waiting-ram"}.get(phase, "running")
    if rec["state"] == "running" and rec["progress"] and len(phase_text) > 1:
        p, began = rec["progress"], float(phase_text[1])
        if 0 < p["done"] <= p["total"]:
            rec["eta_s"] = (time.time() - began) * (p["total"] - p["done"]) / p["done"]
    return rec


def list_jobs(out=None, root=None) -> list[dict]:
    base = jobs_dir(out, root)
    rows = [status(p) for p in base.iterdir() if p.is_dir() and (p / "job.json").exists()]
    return sorted(rows, key=lambda r: r.get("created") or 0)


def ack(folder: Path, note: str = "") -> dict:
    """Mark a failed, stopped or stalled job as handled, so check-ins stop raising it."""
    folder = Path(folder)
    write_text(folder / f"{folder.name}.ack", f"{iso()} {note}".strip() + "\n")
    return status(folder)


def stop(folder: Path) -> dict:
    """Ask the runner to stop the job (it kills the command's whole process tree and writes the marker)."""
    folder = Path(folder)
    write_text(folder / f"{folder.name}.stop", f"requested {iso()}\n")
    return status(folder)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "_run":
        raise SystemExit(_Runner(Path(sys.argv[2])).run())
    raise SystemExit("internal entry point; use `orrin jobs ...`")
