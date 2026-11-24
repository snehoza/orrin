"""The heartbeat: one call that tells the coordinator what needs attention now.

A coordinator that runs for days doesn't need a fixed plan. It needs to look at the same few
things on a regular beat and act on what changed:

* **usage**: the output of each configured usage command (any provider). A line showing
  ``NN% used`` at or above ``models.checkpoint_usage_percent`` becomes an attention item. A failing
  command is "unavailable", never zero.
* **jobs**: failed, stopped or stalled jobs stay on the list until handled (relaunched, or
  ``coordinator jobs ack``), so a check-in that crashed before acting loses nothing. Successful jobs
  are reported once.
* **lanes**: quiet longer than ``silent_lane_minutes``, unless their bound job is still running
  (waiting on a job is not silence); stale (process or job gone); or running longer than
  ``fresh_start_hours``, where a checkpoint and a fresh relaunch beats a degrading context.
* **the lock**: jobs waiting more than 30 minutes.
* **the anchor**: the status file missing, or behind by ``status_stale_commits`` commits.
* **tasks**: claimed, ready and blocked counts from ``tasks.json``, if there is one.

Run it from a scheduler with the prompt in ``HEARTBEAT.md``. ``--quiet`` prints one line when
nothing needs attention.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import time

from . import board, jobs, lock, procs, tasks
from .config import Config
from .home import home, human_age, read_json, write_json

NO_WINDOW = procs.NO_WINDOW if procs.WINDOWS else 0
USED_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%\s*used", re.I)
ACTIVE = ("running", "waiting-lock", "waiting-ram", "starting")


def _usage(cfg: Config, timeout: float = 30) -> list[dict]:
    out = []
    for cmd in cfg["usage_commands"]:
        try:
            r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout,
                               cwd=cfg.root, creationflags=NO_WINDOW)
            text = (r.stdout or r.stderr).strip().splitlines()
            out.append({"command": cmd, "ok": r.returncode == 0, "lines": text[-6:]})
        except (OSError, subprocess.SubprocessError) as e:
            out.append({"command": cmd, "ok": False, "lines": [f"unavailable: {e}"]})
    return out


def _git(cfg: Config, *args) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(cfg.root), *args], capture_output=True, text=True, timeout=20,
                           creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _anchor(cfg: Config) -> dict:
    status = cfg.status_file
    info = {"file": str(status), "exists": status.exists(), "commits_since": None}
    if not status.exists():
        return info
    rel = status.relative_to(cfg.root).as_posix()
    last = _git(cfg, "log", "-1", "--format=%H", "--", rel)
    if last:
        count = _git(cfg, "rev-list", "--count", f"{last}..HEAD")
        info["commits_since"] = int(count) if count and count.isdigit() else None
    return info


def _mark_path(cfg: Config, root):
    key = hashlib.sha1(str(cfg.root).lower().encode()).hexdigest()[:12]
    return home(root) / "checkins" / f"{key}.json"


def collect(cfg: Config, root=None, jobs_out=None, run_usage: bool = True) -> dict:
    now = time.time()
    hb = cfg["heartbeat"]
    mark_path = _mark_path(cfg, root)
    mark_path.parent.mkdir(parents=True, exist_ok=True)
    last = (read_json(mark_path) or {}).get("time", 0)
    rows = jobs.list_jobs(jobs_out, root)
    by_name = {r["name"]: r for r in rows}
    finished_ok = [r for r in rows if r["state"] == "done" and r.get("finished", 0) > last]
    unhandled = [r for r in rows if r["state"] in ("failed", "stopped", "stalled") and not r.get("acked")]
    running = [r for r in rows if r["state"] in ACTIVE]
    lanes = board.read(root, jobs_out=jobs_out, now=now)
    attention = []

    usage = _usage(cfg) if run_usage else []
    threshold = cfg["models"].get("checkpoint_usage_percent")
    for u in usage:
        for line in u["lines"]:
            values = [float(v) for v in USED_RE.findall(line)]
            if threshold and values and max(values) >= threshold:
                attention.append(f"usage at {max(values):g}% ({line.strip()[:120]}): checkpoint the agents on it, "
                                 "plan around the reset or move work to another account")
    for r in unhandled:
        what = "runner gone, no marker" if r["state"] == "stalled" else f"{r.get('reason')}, exit {r.get('exit_code')}"
        attention.append(f"job {r['name']} {r['state']} ({what}): read its log, fix and relaunch, "
                         f"then `coordinator jobs ack {r['name']}`")
    for r in lanes:
        job = by_name.get(r.get("job") or "")
        waiting_on_job = job is not None and job["state"] in ACTIVE
        if r["stale"]:
            attention.append(f"lane {r['lane']} stale ({', '.join(r['stale_reasons'])}): "
                             "resume it from its handoff, or close it with `board done`")
        elif not waiting_on_job and now - r.get("updated", now) > hb["silent_lane_minutes"] * 60:
            attention.append(f"lane {r['lane']} quiet for {human_age(now - r['updated'])}: check that it is working; "
                             "nudge or resume it")
        fresh = hb.get("fresh_start_hours")
        if fresh and not r["stale"] and now - r.get("started", now) > fresh * 3600:
            attention.append(f"lane {r['lane']} running for {human_age(now - r['started'])}: checkpoint it "
                             "(commit, handoff) and relaunch fresh before its context degrades")
    base = home(root) / "locks"
    if base.exists():
        for p in base.iterdir():
            if p.is_dir():
                for q in lock.state(p.name, root)["queue"]:
                    if now - q["since"] > 30 * 60:
                        attention.append(f"{q['label'] or q['pid']} waiting {human_age(now - q['since'])} "
                                         f"for lock {p.name}: check the holder is making progress")
    anchor = _anchor(cfg)
    if not anchor["exists"]:
        attention.append(f"status file {anchor['file']} missing: create it; every check-in re-reads it")
    elif (anchor["commits_since"] or 0) >= hb["status_stale_commits"]:
        attention.append(f"status file not updated in the last {anchor['commits_since']} commits: make it true again")
    task_summary = tasks.summary(cfg) if tasks.path(cfg).exists() else None
    if task_summary and not running and not task_summary["claimed"] and task_summary["ready"]:
        attention.append(f"{len(task_summary['ready'])} ready task(s) and nothing running: start "
                         f"{task_summary['ready'][0]['id']} ({task_summary['ready'][0]['title'][:60]})")
    data = {"time": now, "last_checkin": last or None, "usage": usage, "finished": finished_ok,
            "running": running, "attention": attention, "anchor": anchor, "lanes": len(lanes),
            "tasks": task_summary}
    write_json(mark_path, {"time": now, "project": str(cfg.root)})
    return data


def render(data: dict, quiet: bool = False) -> str:
    t = data.get("tasks")
    task_bits = (f"tasks {t['done']}/{t['total']} done, {len(t['claimed'])} claimed, {len(t['ready'])} ready"
                 if t else None)
    if quiet and not data["attention"]:
        bits = [f"{len(data['running'])} running", f"{len(data['finished'])} finished OK since last check-in"]
        if task_bits:
            bits.append(task_bits)
        return "CHECK-IN: nothing needs attention (" + ", ".join(bits) + ")"
    now = data["time"]
    since = f" (last {human_age(now - data['last_checkin'])} ago)" if data.get("last_checkin") else ""
    out = [f"CHECK-IN{since}"]
    for u in data["usage"]:
        out.append(f"USAGE {u['command'] if isinstance(u['command'], str) else ' '.join(u['command'])}"
                   + ("" if u["ok"] else " [unavailable]"))
        out += [f"  {line}" for line in u["lines"]]
    out.append("NEEDS ATTENTION:" if data["attention"] else "NEEDS ATTENTION: nothing")
    out += [f"  - {a}" for a in data["attention"]]
    for r in data["finished"]:
        out.append(f"FINISHED OK: {r['name']}")
    for r in data["running"]:
        p = r.get("progress")
        out.append(f"RUNNING: {r['name']} {r['state']}" + (f" {p['done']}/{p['total']}" if p else "")
                   + (f" eta {human_age(r['eta_s'])}" if r.get("eta_s") is not None else ""))
    if task_bits:
        out.append("TASKS: " + task_bits)
    return "\n".join(out)
