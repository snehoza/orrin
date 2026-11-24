"""Where shared state lives, and small file helpers.

All agents on a machine must see the same lock, board and jobs, so the default home is per user,
not per repository: ``~/.orrin`` (override with ``ORRIN_HOME`` or ``--home``).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")


def home(path: str | os.PathLike | None = None) -> Path:
    root = Path(path or os.environ.get("ORRIN_HOME") or Path.home() / ".orrin")
    root.mkdir(parents=True, exist_ok=True)
    return root


def check_name(name: str, what: str = "name") -> str:
    if not NAME_RE.fullmatch(name or "") or name in (".", ".."):
        raise ValueError(f"{what} must be letters, digits, '_', '.' or '-' (got {name!r})")
    return name


def write_json(path: Path, value) -> None:
    """Write atomically: readers see the old file or the new one, never half of it."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() if t is None else t))


def human_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


@contextmanager
def mutex(path: Path, poll: float = 0.05):
    """A short critical section shared by every process on the machine (OS file lock)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(poll)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def tail_lines(path: Path, max_bytes: int = 65536) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if size > max_bytes else lines
