"""The lead session's own continuity, and the heartbeat prompt's history.

Worker agents are relaunched from their handoffs; the lead needs the same. Its context gets
compacted or the session ends, and the next lead (or the same one after compaction) must pick
up without re-deriving everything. ``LEAD_HANDOFF.md`` is that file: what is running, what each
lane is doing, what waits on the user, what to do next. The lead keeps it current; the check-in
flags it when it falls behind the commits or goes untouched while work happens.

The check-in prompt also changes as the work changes (which lanes to watch, what to relay).
``heartbeat set`` records each version with the reason, and renders the current one into
``HEARTBEAT.md`` between markers, with the history below it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Config

PBEGIN, PEND = "<!-- coordinator:prompt -->", "<!-- /coordinator:prompt -->"


def handoff_path(cfg: Config) -> Path:
    return cfg.root / cfg.data.get("lead_handoff", f"{cfg.data['agents_dir']}/LEAD_HANDOFF.md")


def _log(cfg: Config) -> Path:
    return cfg.agents_dir / "heartbeat.jsonl"


def prompts(cfg: Config) -> list[dict]:
    p = _log(cfg)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def set_prompt(cfg: Config, text: str, why: str) -> dict:
    e = {"time": time.strftime("%Y-%m-%d %H:%M"), "prompt": text.strip(), "why": why.strip()}
    _log(cfg).parent.mkdir(parents=True, exist_ok=True)
    with open(_log(cfg), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    render(cfg)
    return e


def current_prompt(cfg: Config) -> str | None:
    rows = prompts(cfg)
    if rows:
        return rows[-1]["prompt"]
    target = cfg.agents_dir / "HEARTBEAT.md"
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if PBEGIN in text and PEND in text:
            return text.split(PBEGIN, 1)[1].split(PEND, 1)[0].strip()
    return None


def render(cfg: Config) -> Path:
    target = cfg.agents_dir / "HEARTBEAT.md"
    text = target.read_text(encoding="utf-8") if target.exists() else f"# Heartbeat\n\n{PBEGIN}\n{PEND}\n"
    if PBEGIN not in text or PEND not in text:
        text = text.rstrip("\n") + f"\n\n{PBEGIN}\n{PEND}\n"
    rows = prompts(cfg)
    if not rows:
        return target
    head, rest = text.split(PBEGIN, 1)
    tail = rest.split(PEND, 1)[1]
    marker = "\n## Prompt history"
    if marker in tail:
        tail = tail.split(marker, 1)[0].rstrip("\n") + "\n"
    quoted = "\n".join("> " + line if line else ">" for line in rows[-1]["prompt"].splitlines())
    history = [marker.strip(), "", "Newest first. Each change says why the work needed it.", ""]
    history += [f"- {r['time']}: {r['why'] or '(no reason given)'}" for r in reversed(rows)]
    target.write_text(head + PBEGIN + "\n" + quoted + "\n" + PEND + tail.rstrip("\n") + "\n\n" + "\n".join(history) + "\n",
                      encoding="utf-8", newline="\n")
    return target
