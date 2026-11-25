"""A task list where "done" needs evidence.

Long-running agents tend to declare victory early. Anthropic's long-running harness keeps a
JSON feature list in which agents may only flip an item to passing; Ralph-style loops let the
harness, not the agent, decide when work is finished. Same idea here, kept small:

* ``add`` a task with an optional ``--check`` command and ``--after`` dependencies;
* ``claim`` it for a lane (refused while dependencies are open or another lane holds it);
* ``done`` runs the task's check and refuses unless it passes; ``--evidence job:NAME`` must point at
  a job with ``COMPLETE=1``; the evidence and the check's last output lines are recorded;
* ``baseline`` records which failures the check already has before the work, so ``done`` refuses only
  new ones;
* ``set_check`` changes a task's check, with a reason. Any other change to it is refused;
* ``reopen`` with a reason when it turns out not to be done.

The file is ``<agents_dir>/tasks.json``. JSON, not Markdown, on purpose: agents edit it through
these commands rather than rewriting it freehand. The human status file stays the narrative;
this is the checked list behind it.

The check, its baseline and fingerprints of the project files it names are also kept in the machine
home, outside the checkout, when the task is added. An agent that edits its own check is then noticed.
That catches drift and shortcuts, not a determined attacker: the home is writable too.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from . import jobs, procs
from .config import Config
from .home import home, mutex, read_json, write_json

STATES = ("open", "claimed", "done")
# pytest summary lines and unittest headers
FAILURE = r"^(?:FAILED|ERROR) (\S.*?)(?: - .*)?$|^(?:FAIL|ERROR): (.+)$"


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


def _record_path(t: dict, root=None) -> Path | None:
    return home(root) / "checks" / f"{t['key']}.json" if t.get("key") else None


def _record(t: dict, root=None) -> dict | None:
    p = _record_path(t, root)
    return read_json(p, None) if p and p.exists() else None


def _write_record(t: dict, record: dict, root=None) -> None:
    p = _record_path(t, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json(p, record)


def _fingerprints(cfg: Config, check: str) -> dict[str, str]:
    """Hashes of the project files the check names, e.g. the test script it runs."""
    try:
        words = shlex.split(check.replace("\\", "/"))
    except ValueError:
        words = check.split()
    out = {}
    for w in words:
        p = (cfg.root / w.split("::")[0]).resolve()
        if p.is_file() and p.is_relative_to(cfg.root.resolve()):
            out[p.relative_to(cfg.root.resolve()).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _failures(lines: list[str], pattern: str) -> list[str]:
    found = set()
    for line in lines:
        m = re.search(pattern, line)
        if m:
            found.add(next((g for g in m.groups() if g), m.group(0)).strip())
    return sorted(found)


def add(cfg: Config, title: str, check: str | None = None, after: list[str] | None = None,
        lane: str | None = None, root=None) -> dict:
    with _lock(cfg):
        tasks = load(cfg)
        for d in after or []:
            _find(tasks, d)
        n = 1 + max((int(t["id"][1:]) for t in tasks if t["id"][1:].isdigit()), default=0)
        t = {"id": f"T{n}", "key": uuid.uuid4().hex, "title": title.strip(), "check": check, "after": list(after or []), "lane": lane,
             "status": "open", "created": time.strftime("%Y-%m-%d %H:%M"), "history": []}
        if check:
            _write_record(t, {"check": check, "files": _fingerprints(cfg, check)}, root)
        tasks.append(t)
        _save(cfg, tasks)
    return t


def set_check(cfg: Config, tid: str, check: str, why: str, root=None) -> dict:
    if not why.strip():
        raise TaskError("changing a check needs a reason")
    with _lock(cfg):
        tasks = load(cfg)
        t = _find(tasks, tid)
        if t["status"] == "done":
            raise TaskError(f"{tid} is already done")
        t.setdefault("key", uuid.uuid4().hex)
        t["history"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "event": "check changed", "why": why,
                             "was": t.get("check")})
        t["check"] = check
        t.pop("baseline", None)  # it described the old check
        _write_record(t, {"check": check, "files": _fingerprints(cfg, check)}, root)
        _save(cfg, tasks)
    return t


def baseline(cfg: Config, tid: str, why: str = "", pattern: str = FAILURE, root=None, check_timeout: float = 1800) -> dict:
    """Run the check before the work and record what already fails.

    Recording it late or again could hide new failures, so both need a reason."""
    t = _find(load(cfg), tid)
    if t["status"] == "done":
        raise TaskError(f"{tid} is already done")
    if not t.get("check"):
        raise TaskError(f"{tid} has no check")
    record = _record(t, root)
    if not record:
        raise TaskError(f"no record of {tid}'s original check on this machine; use task set-check")
    if record["check"] != t["check"]:
        raise TaskError(f"{tid}'s check was changed outside `task set-check`")
    if (record.get("baseline") or t["status"] != "open") and not why.strip():
        raise TaskError(f"{tid} is claimed or already has a baseline; recording it now could hide new failures, so give --why")
    code, lines = _run_check(cfg, t["check"], check_timeout)
    found = _failures(lines, pattern)
    if code != 0 and not found:
        raise TaskError(f"{tid} check failed (exit {code}) but no failure names were recognised; pass --pattern")
    base = {"exit": code, "failures": found, "pattern": pattern, "time": time.strftime("%Y-%m-%d %H:%M"), "why": why}
    with _lock(cfg):
        tasks = load(cfg)
        t = _find(tasks, tid)
        t["baseline"] = base
        t["history"].append({"time": base["time"], "event": f"baseline: {len(found)} known failures", "why": why})
        _write_record(t, dict(record, baseline=base), root)
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
    return r.returncode, lines


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
    kept = _record(t, root)
    if kept and kept["check"] != t.get("check"):
        raise TaskError(f"{tid}'s check was changed outside `task set-check` (it was: {kept['check']})")
    if t.get("check"):
        notes = []
        if not kept:
            notes.append("no record of the original check on this machine, so a changed check would not be noticed")
        else:
            now = _fingerprints(cfg, t["check"])
            changed = sorted(f for f, h in kept["files"].items() if now.get(f) != h)
            if changed:
                notes.append("files the check uses changed since the task was added, review them: " + ", ".join(changed))
        code, lines = _run_check(cfg, t["check"], check_timeout)
        record["check_output"] = lines[-5:]
        base = (kept or {}).get("baseline")
        if code != 0:
            found = _failures(lines, base["pattern"]) if base else []
            new = [f for f in found if f not in base["failures"]] if base else []
            # same exit code: a crash or interrupted run must not pass as "only old failures"
            if not base or code != base["exit"] or not found or new:
                detail = ("new failures: " + ", ".join(new)) if new else " | ".join(lines[-3:])
                raise TaskError(f"{tid} check failed (exit {code}): {detail}")
            record["known_failures"] = found
            notes.append(f"{len(found)} failures from before this task remain: " + ", ".join(found))
        if notes:
            record["notes"] = notes
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
        for k in ("done", "evidence", "check_output", "known_failures", "notes"):
            t.pop(k, None)
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
        out += [f"   note: {n}" for n in t.get("notes", [])]
    return "\n".join(out) if out else "no open tasks"


def dumps(tasks) -> str:
    return json.dumps(tasks, indent=2)
