"""React when the lead goes idle, not only on the heartbeat.

The heartbeat checks in every N minutes. Between beats, a lead that finishes a turn while a
job has failed or ready tasks wait would sit idle until the next beat. A harness stop hook
closes that gap: when the agent is about to stop, ``orrin stop-check`` peeks at the same
state as ``checkin`` (without the usage commands and without consuming the check-in's
"since last time" mark) and, if there is work the agent can do itself, tells the harness to
keep going with a short reason.

It is deliberately small:
* it blocks only for work the agent can act on (a failed job, a quiet or stale lane, a status
  file or lead handoff that fell behind, a ready task with nothing running); never for usage
  or for anything that needs the user;
* the reason is at most three lines;
* it blocks at most ``heartbeat.stop_hook_max_blocks`` times in a row per session (3 by
  default), then lets the agent stop and won't block again for the same items until they
  change, so it can't loop;
* with nothing to do it prints nothing.

Claude Code: add to ``.claude/settings.json``::

    {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "orrin stop-check"}]}]}}

Other harnesses: call it from whatever runs when the agent ends a turn; exit 0 with
``{"decision": "block", "reason": ...}`` on stdout means "keep going".
"""
from __future__ import annotations

import json
import re
import sys
import time

from . import checkin
from .config import Config
from .home import home, read_json, write_json

SKIP = ("usage at",)  # needs a reset or the user, not more agent work


def decide(cfg: Config, hook_input: dict, root=None, jobs_out=None) -> dict | None:
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(hook_input.get("session_id") or "default"))[:64] or "default"
    state_path = home(root) / "stopcheck" / f"{session}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = read_json(state_path) or {"blocks": 0}
    data = checkin.collect(cfg, root, jobs_out, run_usage=False, mark=False)
    items = [a for a in data["attention"] if not a.startswith(SKIP)]
    limit = int(cfg["heartbeat"].get("stop_hook_max_blocks", 3))
    if not items:
        write_json(state_path, {"blocks": 0, "time": time.time()})
        return None
    if items == state.get("gave_up_on"):
        return None  # the same items survived the last round of blocks: leave them to the heartbeat
    if state["blocks"] >= limit:
        write_json(state_path, {"blocks": 0, "gave_up_on": items, "time": time.time()})
        return None
    write_json(state_path, {"blocks": state["blocks"] + 1, "time": time.time()})
    shown = [i if len(i) <= 160 else i[:157] + "..." for i in items[:3]]
    more = f" (+{len(items) - 3} more: orrin checkin)" if len(items) > 3 else ""
    return {"decision": "block", "reason": "Before stopping:\n- " + "\n- ".join(shown) + more}


def main(cfg: Config, root=None, jobs_out=None) -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        hook_input = json.loads(raw) if raw.strip() else {}
    except ValueError:
        hook_input = {}
    try:
        result = decide(cfg, hook_input, root, jobs_out)
    except Exception as e:  # a broken hook must never trap the agent
        print(f"orrin stop-check skipped: {e}", file=sys.stderr)
        return 0
    if result:
        print(json.dumps(result))
    return 0
