"""One read-only screen: the machine lock, jobs, the lane board and the machine itself."""
from __future__ import annotations

import os
import time

from . import board, jobs, lock, procs
from .home import home, human_age

ACTIVE = ("starting", "waiting-lock", "waiting-ram", "running")


def collect(root=None, jobs_out=None, recent_h: float = 24, stale_h: float = 2.0) -> dict:
    now = time.time()
    locks = []
    base = home(root) / "locks"
    if base.exists():
        locks = [lock.state(p.name, root) for p in sorted(base.iterdir()) if p.is_dir()]
    rows = jobs.list_jobs(jobs_out, root)
    shown = [r for r in rows if r["state"] in ACTIVE or r["state"] == "stalled"
             or now - r.get("finished", now) <= recent_h * 3600]
    return {
        "time": now,
        "machine": {"cpus": os.cpu_count(), "available_mb": procs.available_mb(), "load_percent": procs.load_percent()},
        "locks": locks,
        "jobs": shown,
        "board": board.read(root, stale_h, jobs_out, now),
    }


def render(data: dict) -> str:
    now = data["time"]
    m = data["machine"]
    out = [f"MACHINE: {m['cpus']} CPUs | available {m['available_mb'] if m['available_mb'] is not None else '?'} MiB"
           + (f" | load {m['load_percent']:.0f}%" if m.get("load_percent") is not None else "")]
    for lk in data["locks"]:
        if not lk["holders"] and not lk["queue"]:
            out.append(f"LOCK {lk['name']}: free")
            continue
        held = ", ".join(f"{h['label'] or h['pid']} ({h['mode']}, {human_age(now - h['since'])})" for h in lk["holders"])
        out.append(f"LOCK {lk['name']}: held by {held or 'nobody'}")
        for q in lk["queue"]:
            out.append(f"  queued: {q['label'] or q['pid']} ({q['mode']}, waiting {human_age(now - q['since'])})")
    if not data["locks"]:
        out.append("LOCK: never used")
    out.append(f"JOBS ({len(data['jobs'])} active or recent):" if data["jobs"] else "JOBS: none active or recent")
    for r in data["jobs"]:
        line = f"  {r['name']}: {r['state']}"
        if r.get("lane"):
            line += f" [{r['lane']}]"
        if r.get("progress"):
            line += f" {r['progress']['done']}/{r['progress']['total']}"
        if r.get("eta_s") is not None:
            line += f" eta {human_age(r['eta_s'])}"
        if r.get("reason") and r["state"] != "done":
            line += f" ({r['reason']}, exit {r['exit_code']})"
        out.append(line)
    out.append(board.render(data["board"], now))
    return "\n".join(out)
