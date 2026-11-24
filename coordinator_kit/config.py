"""Project settings as data: ``coordinator.json`` at the project root.

Everything here is expected to change as the coordinator learns how the user works: where the
status file is, how often the heartbeat runs, what the agent decides alone and what it must ask,
which models do which kind of work, and the budget thresholds. Edit the JSON (or ask the
coordinator to); ``coordinator rule render`` writes the current values into the agent rules.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

NAME = "coordinator.json"

DEFAULT = {
    "agents_dir": "docs/agents",
    "status_file": "TODO.md",
    "heartbeat": {"every_minutes": 30, "silent_lane_minutes": 45, "status_stale_commits": 10,
                  "fresh_start_hours": 8},
    "usage_commands": [],
    "boundary": {
        "decide": ["technical choices: design, libraries, tests, tools, which lane does what",
                   "how many agents run and on which models",
                   "merging a branch that passed its checks, when merging is allowed"],
        "ask": ["push or deploy", "deleting anything", "changes users can see",
                "spending money beyond the agreed budget", "anything only the user can sign or agree to"],
    },
    "models": {
        "roles": {"design, debugging, changes to defaults": "the strongest available",
                  "mechanical work, proof runs, receipts, judging": "the cheapest model that can do it"},
        "fallback": [],
        "checkpoint_usage_percent": 90,
        "relaunch_context_tokens": None,
    },
}


def find(start=None) -> Path | None:
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / NAME).is_file():
            return folder / NAME
    return None


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Config:
    def __init__(self, path: Path | None):
        self.path = Path(path).resolve() if path else None
        self.root = self.path.parent if self.path else Path.cwd().resolve()
        raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
        self.data = _merge(DEFAULT, raw)

    @classmethod
    def load(cls, path=None) -> "Config":
        return cls(Path(path) if path else find())

    def __getitem__(self, key):
        return self.data[key]

    @property
    def agents_dir(self) -> Path:
        return self.root / self.data["agents_dir"]

    @property
    def status_file(self) -> Path:
        return self.root / self.data["status_file"]
