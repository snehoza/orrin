"""The heartbeat: one call that tells the coordinator what needs attention since the last one.

A coordinator that runs for days doesn't need a fixed plan. It needs to look at the same few
things on a regular beat and act on what changed:

* **usage**: the output of each configured usage command (any provider; failures are reported as
  "unavailable", never as zero), so work can be planned around the quota that is left;
* **jobs**: what finished, failed or stalled since the last check-in, and what is still running;
* **lanes**: board entries that have gone quiet longer than ``silent_lane_minutes`` (nudge them)
  or stale (their process or job is gone);
* **the lock**: jobs waiting unusually long;
* **the anchor**: whether the status file kept up with the commits (``status_stale_commits``).

Run it from a scheduler (cron, a harness loop, a scheduled task) with the check-in prompt from
``HEARTBEAT.md``. ``--quiet`` prints a single line when nothing needs attention.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import board, jobs, lock, procs
from .config import Config
from .home import home, human_age, read_json, write_json

NO_WINDOW = procs.NO_WINDOW if procs.WINDOWS else 0


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
    dirty = _git(cfg, "status", "--porcelain", "--", rel)
    info["uncommitted_change"] = bool(dirty)
    return info


def collect(cfg: Config, root=None, jobs_out=None, run_usage: bool = True) -> dict:
    now = time.time()
    hb = cfg["heartbeat"]
    mark_path = home(root) / "checkin.json"
    last = (read_json(mark_path) or {}).get("time", 0)
    rows = jobs.list_jobs(jobs_out, root)
    finished = [r for r in rows if r["state"] in ("done", "failed", "stopped") and r.get("finished", 0) > last]
    stalled = [r for r in rows if r["state"] == "stalled"]
    running = [r for r in rows if r["state"] in ("running", "waiting-lock", "waiting-ram", "starting")]
    lanes = board.read(root, jobs_out=jobs_out, now=now)
    quiet = [r for r in lanes if not r["stale"] and now - r.get("updated", now) > hb["silent_lane_minutes"] * 60]
    stale = [r for r in lanes if r["stale"]]
    waits = []
    base = home(root) / "locks"
    if base.exists():
        for p in base.iterdir():
            if p.is_dir():
                for q in lock.state(p.name, root)["queue"]:
                    if now - q["since"] > 30 * 60:
                        waits.append(dict(q, lock=p.name))
    anchor = _anchor(cfg)
    attention = []
    for r in finished:
        if r["state"] != "done":
            attention.append(f"job {r['name']} {r['state']} ({r.get('reason')}, exit {r.get('exit_code')}): read its log and fix or relaunch")
    for r in stalled:
        attention.append(f"job {r['name']} stalled (runner gone, no marker): relaunch it; `coordinator tidy --apply` marks it")
    for r in quiet:
        attention.append(f"lane {r['lane']} quiet for {human_age(now - r['updated'])}: check it is working; nudge or resume it")
    for r in stale:
        attention.append(f"lane {r['lane']} stale ({', '.join(r['stale_reasons'])}): resume from its handoff or close it (`board done`)")
    for q in waits:
        attention.append(f"{q['label'] or q['pid']} waiting {human_age(now - q['since'])} for lock {q['lock']}")
    if not anchor["exists"]:
        attention.append(f"status file {anchor['file']} missing: create it; it is the anchor every check-in re-reads")
    elif (anchor["commits_since"] or 0) >= hb["status_stale_commits"]:
        attention.append(f"status file not updated in the last {anchor['commits_since']} commits: make it true again")
    data = {"time": now, "last_checkin": last or None, "usage": _usage(cfg) if run_usage else [],
            "finished": finished, "running": running, "attention": attention, "anchor": anchor,
            "lanes": len(lanes)}
    write_json(mark_path, {"time": now})
    return data


def render(data: dict, quiet: bool = False) -> str:
    if quiet and not data["attention"]:
        done = len([r for r in data["finished"] if r["state"] == "done"])
        bits = [f"{len(data['running'])} running", f"{done} finished OK since last check-in"]
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
        if r["state"] == "done":
            out.append(f"FINISHED OK: {r['name']}")
    for r in data["running"]:
        p = r.get("progress")
        out.append(f"RUNNING: {r['name']} {r['state']}" + (f" {p['done']}/{p['total']}" if p else "")
                   + (f" eta {human_age(r['eta_s'])}" if r.get("eta_s") is not None else ""))
    return "\n".join(out)
