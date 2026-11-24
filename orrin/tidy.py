"""Find stale workflow state; ``apply`` repairs only what loses no data.

Finds:
* lock tickets and holds left by dead processes (dropped; they are state, not data);
* jobs whose runner died without a marker (``stalled``): a marker ``REASON=stalled`` is written so
  every reader agrees the job is over;
* stale board entries (moved to ``board/archive/``);
* finished jobs older than ``keep_days`` (moved to ``jobs/archive/``, never deleted).

The default is a dry run that only reports.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import board, jobs, lock
from .home import home, iso, write_text


def find(root=None, jobs_out=None, keep_days: float = 14, stale_h: float = 2.0) -> list[dict]:
    items = []
    locks = home(root) / "locks"
    if locks.exists():
        for folder in locks.iterdir():
            if not folder.is_dir():
                continue
            before = sum(1 for sub in ("queue", "holders") for _ in (folder / sub).glob("*.json"))
            live = lock.state(folder.name, root)  # drops dead entries as a side effect of reading
            after = len(live["holders"]) + len(live["queue"])
            if before > after:
                items.append({"kind": "lock", "what": folder.name, "detail": f"{before - after} dead ticket(s) dropped",
                              "applied": True})
    now = time.time()
    for row in jobs.list_jobs(jobs_out, root):
        if row["state"] == "stalled":
            items.append({"kind": "job-stalled", "what": row["dir"], "detail": "runner gone, no marker"})
        elif row["state"] in ("done", "failed", "stopped") and now - row.get("finished", now) > keep_days * 86400:
            items.append({"kind": "job-old", "what": row["dir"], "detail": f"{row['state']}, older than {keep_days:g} days"})
    for row in board.read(root, stale_h, jobs_out):
        if row["stale"]:
            items.append({"kind": "board-stale", "what": row["lane"], "detail": ", ".join(row["stale_reasons"])})
    return items


def apply(items: list[dict], root=None, jobs_out=None) -> list[dict]:
    for item in items:
        if item.get("applied"):
            continue
        if item["kind"] == "job-stalled":
            folder = Path(item["what"])
            write_text(folder / f"{folder.name}.done", f"EXIT=-1 COMPLETE=0 REASON=stalled {iso()}\n")
        elif item["kind"] == "job-old":
            folder = Path(item["what"])
            archive = folder.parent / "archive"
            archive.mkdir(exist_ok=True)
            shutil.move(str(folder), str(archive / folder.name))
        elif item["kind"] == "board-stale":
            board.done(item["what"], root)
        item["applied"] = True
    return items
