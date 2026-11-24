"""The lane board: who is working where, on what, and what heavy job comes next.

Information only. A board entry never blocks anyone and grants nothing; decisions and approvals go
through the coordinator. Entries go stale (and are ignored) when they are older than ``stale_h``
hours, their PID is gone, or the job they are bound to has finished.

One JSON file per lane under ``<home>/board/``; ``done`` moves the file to ``board/archive/``.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import jobs, procs
from .home import check_name, home, human_age, mutex, read_json, write_json

FIELDS = ("worktree", "branch", "model", "activity", "next", "eta", "job")


def board_dir(root=None) -> Path:
    path = home(root) / "board"
    path.mkdir(parents=True, exist_ok=True)
    return path


def update(lane: str, fields: dict | None = None, note: str | None = None, pid: int | None = None, root=None) -> dict:
    check_name(lane, "lane")
    base = board_dir(root)
    with mutex(base / ".mutex"):
        path = base / f"{lane}.json"
        row = read_json(path) or {"lane": lane, "notes": []}
        row.update({k: v for k, v in (fields or {}).items() if v is not None})
        if pid:
            row["pid"], row["pid_ident"] = pid, procs.identity(pid)
        if note:
            row["notes"].append({"time": time.time(), "text": note})
            row["notes"] = row["notes"][-50:]
        row["updated"] = time.time()
        write_json(path, row)
    return row


def done(lane: str, root=None) -> Path | None:
    check_name(lane, "lane")
    base = board_dir(root)
    with mutex(base / ".mutex"):
        path = base / f"{lane}.json"
        if not path.exists():
            return None
        (base / "archive").mkdir(exist_ok=True)
        target = base / "archive" / f"{lane}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.replace(target)
        return target


def read(root=None, stale_h: float = 2.0, jobs_out=None, now: float | None = None) -> list[dict]:
    now = now or time.time()
    rows = []
    for path in sorted(board_dir(root).glob("*.json")):
        row = read_json(path)
        if not isinstance(row, dict):
            continue
        reasons = []
        if now - row.get("updated", 0) > stale_h * 3600:
            reasons.append(f"not updated for {human_age(now - row.get('updated', 0))}")
        if row.get("pid") and not procs.alive(row["pid"], row.get("pid_ident")):
            reasons.append("process gone")
        if row.get("job"):
            try:
                state = jobs.status(jobs.resolve(row["job"], jobs_out, root))["state"]
            except ValueError:
                state = "missing"
            if state not in ("running", "waiting-lock", "waiting-ram", "starting"):
                reasons.append(f"bound job {state}")
        rows.append(dict(row, stale=bool(reasons), stale_reasons=reasons))
    return rows


def render(rows: list[dict], now: float | None = None) -> str:
    now = now or time.time()
    if not rows:
        return "LANE BOARD: empty"
    out = ["LANE BOARD (information only; decisions go through the coordinator)"]
    for row in rows:
        bits = [row.get("model", "?"), row.get("activity", "-")]
        if row.get("next"):
            bits.append(f"next {row['next']}" + (f" eta {row['eta']}" if row.get("eta") else ""))
        out.append(f"{row['lane']}: {'STALE' if row['stale'] else 'live'} | " + " | ".join(bits)
                   + f" | updated {human_age(now - row.get('updated', now))} ago")
        if row.get("worktree"):
            out.append(f"  worktree {row['worktree']}" + (f" ({row['branch']})" if row.get("branch") else ""))
        if row["stale"]:
            out.append("  stale: " + ", ".join(row["stale_reasons"]))
        for note in row.get("notes", [])[-3:]:
            out.append(f"  note {time.strftime('%m-%d %H:%M', time.localtime(note['time']))}: {note['text']}")
    return "\n".join(out)
