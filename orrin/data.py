"""Protected data: a registry of what must never be removed by hand, and an archive-only cleanup.

Data has three tiers:

* **source**: irreplaceable inputs (datasets, recordings, the repository). Never moved.
* **golden**: reference outputs that tests compare against. A golden must be self-contained: every
  input it lists lives inside its own folder, so cleaning up anything else can never break it.
* **cache**: derived and rebuildable. The only tier the cleanup moves, and only to an archive folder.

The registry is a JSON file (``protected_data.json``)::

    {"entries": [
      {"id": "dataset", "path": "/data/recordings", "kind": "source", "why": "the only copy"},
      {"id": "golden-v3", "path": "goldens/v3", "kind": "golden", "inputs": ["goldens/v3/in"], "why": "..."},
      {"id": "renders", "path": "cache/renders", "kind": "cache", "why": "...", "rebuild": "make renders"}]}

Relative paths resolve against the registry file's folder.

* ``check``: sources and goldens exist, and every golden input exists inside its golden.
* ``scan ROOT``: the folders under ROOT with size, age and whether each is protected.
* ``archive PATH... --to DIR``: move unprotected folders to DIR (dry run unless ``apply``); each move is
  logged to ``DIR/ARCHIVE_LOG.jsonl`` so it can be undone. Nothing is ever deleted.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .home import read_json

KINDS = ("source", "golden", "cache")
KEEP = ("source", "golden")


class Registry:
    def __init__(self, path):
        self.path = Path(path).resolve()
        data = read_json(self.path)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise ValueError(f"{self.path}: expected {{\"entries\": [...]}}")
        self.entries = []
        for e in data["entries"]:
            if e.get("kind") not in KINDS:
                raise ValueError(f"{self.path}: entry {e.get('id')!r} has kind {e.get('kind')!r}; use one of {KINDS}")
            e = dict(e, path=self._abs(e["path"]), inputs=[self._abs(i) for i in e.get("inputs", [])])
            self.entries.append(e)

    def _abs(self, p: str) -> Path:
        p = Path(os.path.expanduser(p))
        return (p if p.is_absolute() else self.path.parent / p).resolve()

    def protection(self, path) -> str | None:
        """Why ``path`` must stay, or None. A folder that is, is inside, or contains a kept path is kept."""
        path = Path(path).resolve()
        for e in self.entries:
            if e["kind"] not in KEEP:
                continue
            for kept in [e["path"], *e["inputs"]]:
                if path == kept or kept in path.parents:
                    return f"{e['kind']} {e['id']}"
                if path in kept.parents:
                    return f"contains {e['kind']} {e['id']}"
        return None

    def check(self) -> list[str]:
        problems = []
        for e in self.entries:
            if e["kind"] in KEEP and not e["path"].exists():
                problems.append(f"{e['kind']} {e['id']}: missing {e['path']}")
            if e["kind"] == "golden":
                for i in e["inputs"]:
                    if e["path"] != i and e["path"] not in i.parents:
                        problems.append(f"golden {e['id']}: input {i} lives outside the golden (not self-contained)")
                    elif not i.exists():
                        problems.append(f"golden {e['id']}: input missing {i}")
        return problems


def size_of(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def scan(registry: Registry, root) -> list[dict]:
    rows = []
    for p in sorted(Path(root).iterdir()):
        if not p.is_dir():
            continue
        rows.append({"path": str(p), "bytes": size_of(p), "age_days": (time.time() - p.stat().st_mtime) / 86400,
                     "protected": registry.protection(p)})
    return rows


def archive(registry: Registry, paths, to, apply: bool = False) -> list[dict]:
    to = Path(to).resolve()
    plan = []
    for p in map(lambda x: Path(x).resolve(), paths):
        why = registry.protection(p)
        if not p.exists():
            why = why or "does not exist"
        if to == p or p in to.parents:
            why = why or "archive folder is inside it"
        plan.append({"path": str(p), "refused": why, "target": None if why else str(to / p.name)})
    if apply:
        to.mkdir(parents=True, exist_ok=True)
        for row in plan:
            if row["refused"]:
                continue
            target = Path(row["target"])
            if target.exists():
                target = target.with_name(f"{target.name}-{time.strftime('%Y%m%d-%H%M%S')}")
                row["target"] = str(target)
            shutil.move(row["path"], target)
            with open(to / "ARCHIVE_LOG.jsonl", "a", encoding="utf-8") as log:
                log.write(json.dumps({"time": time.time(), "from": row["path"], "to": str(target)}) + "\n")
            row["moved"] = True
    return plan
