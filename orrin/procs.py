"""Process and machine helpers that work on Linux, macOS and Windows with the standard library.

* ``identity(pid)``: a token that changes when a PID is reused (process start time), or None where
  the platform does not expose it cheaply.
* ``alive(pid, ident)``: the process exists, is not a zombie and, when ``ident`` is given, is the same
  process that was recorded.
* ``available_mb()``: memory a new process can use without swapping, in MiB (None if unknown).
* ``spawn_detached(argv)``: start a process that outlives the caller, its terminal and its session,
  with no console window on Windows.
* ``kill_tree(pid)``: stop a process and everything it started.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)


# --- identity and liveness ------------------------------------------------------------------------------

def _linux_stat(pid: int) -> list[str] | None:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    # the command name is in parentheses and may contain spaces
    return text[text.rfind(")") + 2:].split()


if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    _QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    _STILL_ACTIVE = 259

    def _win_open(pid: int):
        return _k32.OpenProcess(_QUERY, False, pid)

    def _win_identity(pid: int) -> str | None:
        h = _win_open(pid)
        if not h:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not _k32.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            _k32.CloseHandle(h)

    def _win_running(pid: int) -> bool:
        h = _win_open(pid)
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            return bool(_k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == _STILL_ACTIVE
        finally:
            _k32.CloseHandle(h)


def identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    if WINDOWS:
        return _win_identity(pid)
    if sys.platform.startswith("linux"):
        fields = _linux_stat(pid)
        return fields[19] if fields and len(fields) > 19 else None
    return None


def alive(pid: int | None, ident: str | None = None) -> bool:
    if not pid or pid <= 0:
        return False
    if WINDOWS:
        running = _win_running(pid)
    else:
        try:
            os.kill(pid, 0)
            running = True
        except ProcessLookupError:
            running = False
        except PermissionError:
            running = True
        if running and sys.platform.startswith("linux"):
            fields = _linux_stat(pid)
            running = bool(fields) and fields[0] not in ("Z", "X")
    if not running:
        return False
    if ident is not None:
        now = identity(pid)
        if now is not None and now != ident:
            return False  # the PID was reused by another process
    return True


def me() -> tuple[int, str | None]:
    pid = os.getpid()
    return pid, identity(pid)


# --- machine --------------------------------------------------------------------------------------------

def available_mb() -> int | None:
    """Memory available to a new process without swapping, in MiB."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            return None
        return None
    if WINDOWS:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if _k32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullAvailPhys // (1024 * 1024))
        return None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        page = 4096
        pages = 0
        for line in out.splitlines():
            if "page size of" in line:
                page = int(line.split("page size of")[1].split()[0])
            for key in ("Pages free", "Pages inactive", "Pages purgeable"):
                if line.startswith(key + ":"):
                    pages += int(line.split(":")[1].strip().rstrip("."))
        return pages * page // (1024 * 1024) if pages else None
    return None


def load_percent() -> float | None:
    """1-minute load as a share of the CPUs (POSIX), or None."""
    if hasattr(os, "getloadavg"):
        try:
            return 100.0 * os.getloadavg()[0] / (os.cpu_count() or 1)
        except OSError:
            return None
    return None


# --- spawning -------------------------------------------------------------------------------------------

def spawn_detached(argv: list[str], cwd: str | None = None, env: dict | None = None) -> int:
    """Start ``argv`` so it survives the caller, its terminal and (where allowed) its job object.

    POSIX: double fork + setsid, so the process is adopted by init and never becomes a zombie of the
    caller. Windows: a new process group with a hidden console, broken away from the caller's job
    object when the job allows it (some agent harnesses kill their whole job on exit).
    """
    if WINDOWS:
        base = NO_WINDOW | NEW_GROUP
        for flags in (base | BREAKAWAY, base):
            try:
                p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
                return p.pid
            except OSError:
                if flags == base:
                    raise
        raise RuntimeError("unreachable")
    r, w = os.pipe()
    first = os.fork()
    if first == 0:  # pragma: no cover - runs in the child
        try:
            os.close(r)
            os.setsid()
            second = os.fork()
            if second:
                os.write(w, str(second).encode())
                os._exit(0)
            os.close(w)
            null = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(null, fd)
            if cwd:
                os.chdir(cwd)
            os.execve(argv[0], argv, env if env is not None else os.environ)
        except BaseException:
            os._exit(127)
    os.close(w)
    os.waitpid(first, 0)
    with os.fdopen(r, "rb") as f:
        data = f.read().decode() or "0"
    return int(data)


def popen_group(argv, **kwargs) -> subprocess.Popen:
    """Start a child in its own process group (so the whole tree can be stopped), no console window."""
    if WINDOWS:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | NO_WINDOW | NEW_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def kill_tree(pid: int, grace: float = 5.0) -> None:
    """Ask the process tree rooted at ``pid`` to stop, then force it after ``grace`` seconds."""
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=NO_WINDOW)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):  # macOS: EPERM when only an unreaped process is left
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
