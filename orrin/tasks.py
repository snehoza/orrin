"""A task list where "done" needs evidence.

Long-running agents tend to declare victory early. Anthropic's long-running harness keeps a
JSON feature list in which agents may only flip an item to passing; Ralph-style loops let the
harness, not the agent, decide when work is finished. Same idea here, kept small:

* ``add`` a task with an optional ``--check`` command and ``--after`` dependencies;
* ``claim`` it for a lane (refused while dependencies are open or another lane holds it);
* ``done`` runs the task's check and refuses unless it passes; ``--evidence job:NAME`` must point at
  a job with ``COMPLETE=1``; the evidence and the check's last output lines are recorded;
* ``reopen`` with a reason when it turns out not to be done.

The file is ``<agents_dir>/tasks.json``. JSON, not Markdown, on purpose: agents edit it through
these commands rather than rewriting it freehand. The human status file stays the narrative;
this is the checked list behind it.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import jobs, procs
from .config import Config
from .home import mutex, read_json, write_json

STATES = ("open", "claimed", "done")


class TaskError(ValueError):
    pass


def path(cfg: Config) -> Path:
    return cfg.agents_dir / "tasks.json"


def load(cfg: Config) -> list[dict]:
    data = read_json(path(cfg), {"tasks": []})
    return data.get("tasks", [])


def _save(cfg: Config, tasks: list[dict]) -> None:
    path(cfg).parent.mkdir(parents=True, exist_ok=True)
    write_json(path(cfg), {"tasks": tasks})


def _lock(cfg: Config):
    return mutex(cfg.agents_dir / ".tasks.lock")


def _find(tasks: list[dict], tid: str) -> dict:
    for t in tasks:
        if t["id"] == tid:
            return t
    raise TaskError(f"no task {tid}")


def blocked_by(tasks: list[dict], t: dict) -> list[str]:
    done = {x["id"] for x in tasks if x["status"] == "done"}
    return [d for d in t.get("after", []) if d not in done]


def add(cfg: Config, title: str, check: str | None = None, after: list[str] | None = None,
        lane: str | None = None) -> dict:
    with _lock(cfg):
        tasks = load(cfg)
        for d in after or []:
            _find(tasks, d)
        n = 1 + max((int(t["id"][1:]) for t in tasks if t["id"][1:].isdigit()), default=0)
        t = {"id": f"T{n}", "title": title.strip(), "check": check, "after": list(after or []), "lane": lane,
             "status": "open", "created": time.strftime("%Y-%m-%d %H:%M"), "history": []}
        tasks.append(t)
        _save(cfg, tasks)
    return t


def claim(cfg: Config, tid: str, lane: str) -> dict:
    with _lock(cfg):
        tasks = load(cfg)
        t = _find(tasks, tid)
        if t["status"] == "done":
            raise TaskError(f"{tid} is already done")
        if t["status"] == "claimed" and t.get("lane") not in (None, lane):
            raise TaskError(f"{tid} is claimed by {t['lane']}")
        waiting = blocked_by(tasks, t)
        if waiting:
            raise TaskError(f"{tid} waits on {', '.join(waiting)}")
        t.update(status="claimed", lane=lane)
        t["history"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "event": f"claimed by {lane}"})
        _save(cfg, tasks)
    return t


def _run_check(cfg: Config, check: str, timeout: float) -> tuple[int, list[str]]:
    try:
        r = subprocess.run(check, shell=True, cwd=cfg.root, capture_output=True, text=True, timeout=timeout,
                           creationflags=procs.NO_WINDOW if procs.WINDOWS else 0)
    except subprocess.TimeoutExpired:
        return 124, [f"check timed out after {timeout:.0f} s"]
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode, lines[-5:]


def done(cfg: Config, tid: str, evidence: str = "", root=None, jobs_out=None, check_timeout: float = 1800) -> dict:
    tasks = load(cfg)
    t = _find(tasks, tid)
    if t["status"] == "done":
        raise TaskError(f"{tid} is already done")
    waiting = blocked_by(tasks, t)
    if waiting:
        raise TaskError(f"{tid} waits on {', '.join(waiting)}")
    if evidence.startswith("job:"):
        row = jobs.status(jobs.resolve(evidence[4:], jobs_out, root))
        if row["state"] != "done":
            raise TaskError(f"evidence {evidence} is {row['state']}, not a job with COMPLETE=1")
    record = {"evidence": evidence}
    if t.get("check"):
        code, lines = _run_check(cfg, t["check"], check_timeout)
        record["check_output"] = lines
        if code != 0:
            raise TaskError(f"{tid} check failed (exit {code}): " + " | ".join(lines[-3:]))
    elif not evidence:
        raise TaskError(f"{tid} has no check, so `done` needs --evidence (job:NAME, a commit, or what proves it)")
    with _lock(cfg):
        tasks = load(cfg)
        t = _find(tasks, tid)
        t.update(status="done", done=time.strftime("%Y-%m-%d %H:%M"), **record)
        t["history"].append({"time": t["done"], "event": "done", "evidence": evidence})
        _save(cfg, tasks)
    return t


def reopen(cfg: Config, tid: str, why: str) -> dict:
    with _lock(cfg):
        tasks = load(cfg)
        t = _find(tasks, tid)
        t.update(status="open", lane=None)
        t.pop("done", None)
        t["history"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "event": "reopened", "why": why})
        _save(cfg, tasks)
    return t


def summary(cfg: Config) -> dict:
    tasks = load(cfg)
    ready = [t for t in tasks if t["status"] == "open" and not blocked_by(tasks, t)]
    return {"total": len(tasks), "done": sum(t["status"] == "done" for t in tasks),
            "claimed": [t for t in tasks if t["status"] == "claimed"], "ready": ready,
            "blocked": [t for t in tasks if t["status"] == "open" and blocked_by(tasks, t)]}


def render(tasks: list[dict], show_all: bool = False) -> str:
    out = []
    for t in tasks:
        if t["status"] == "done" and not show_all:
            continue
        waits = blocked_by(tasks, t)
        state = t["status"] + (f" by {t['lane']}" if t["status"] == "claimed" else "")
        if waits and t["status"] == "open":
            state = "blocked on " + ",".join(waits)
        line = f"{t['id']} [{state}] {t['title']}"
        if t.get("check"):
            line += f"  (check: {t['check']})"
        if t["status"] == "done" and t.get("evidence"):
            line += f"  (evidence: {t['evidence']})"
        out.append(line)
    return "\n".join(out) if out else "no open tasks"


def dumps(tasks) -> str:
    return json.dumps(tasks, indent=2)
