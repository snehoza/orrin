"""Short blocking waits on job markers.

An agent that polls a job every few seconds re-sends its whole context on every poll; an agent that
blocks for an hour cannot hear messages from anyone else. The middle path: one blocking call of a
few minutes (3 by default) that returns early when every job has finished or any job has failed,
then the agent calls it again if the job is still running.

Exit codes: 0 every job finished with COMPLETE=1; 1 a job failed, stopped or stalled;
3 timeout with jobs still running (call again).
"""
from __future__ import annotations

import time
from pathlib import Path

from . import jobs
from .home import human_age

EXIT_OK, EXIT_FAILED, EXIT_RUNNING = 0, 1, 3
BAD = ("failed", "stopped", "stalled", "missing")


def wait(folders: list[Path], timeout_s: float = 180, interval: float = 2.0) -> tuple[int, list[dict]]:
    deadline = time.monotonic() + timeout_s
    while True:
        rows = [jobs.status(f) for f in folders]
        if any(r["state"] in BAD for r in rows):
            return EXIT_FAILED, rows
        if all(r["state"] == "done" for r in rows):
            return EXIT_OK, rows
        if time.monotonic() >= deadline:
            return EXIT_RUNNING, rows
        time.sleep(min(interval, max(0.05, deadline - time.monotonic())))


def summary(row: dict) -> str:
    head = f"{row['name']}: {row['state']}"
    if row.get("marker"):
        head += f" | {row['marker']}"
    p = row.get("progress")
    if p:
        head += f" | {p['done']}/{p['total']}"
        if row.get("eta_s") is not None:
            head += f" eta {human_age(row['eta_s'])}"
    lines = [head]
    if row["state"] in BAD and row.get("last_line"):
        lines.append(f"  last log line: {row['last_line'][:300]}")
    return "\n".join(lines)
