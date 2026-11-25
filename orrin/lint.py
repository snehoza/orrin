"""Keep instructions from disabling the agent.

Instructions can make an agent worse. A rule written for one case gets applied to every case.
Capitalised MUST/NEVER makes newer models over-apply a rule. A cautious phrase ("stop if your
context grows") gets read far too cautiously. And the more instructions there are, the fewer get
followed well. An agent with a stack of rigid rules stops doing obvious things.

``orrin lint`` checks the files agents read:

* **budget**: rough token size per file against a budget, because every token is read on every
  turn;
* **shouting**: capitalised MUST / NEVER / ALWAYS / CRITICAL / IMPORTANT / DO NOT / STOP, which
  makes newer models over-trigger; say it plainly and give the reason;
* **no reason**: live rules recorded without the user's words or a reason, since a rule with its
  "why" generalises to new cases and a bare rule gets applied blindly;
* **too specific**: a rule that names one file, photo or case, which fits that case and no other;
* **outcomes**: rules that hurt, rules whose failure came back, and rules with a named failure but
  nothing recorded after ``REVIEW_DAYS``. These are candidates to look at. A preference of the
  user's needs no proof;
* **too many**: more live rules than ``max_rules``. Merge, or retire what no longer serves the
  work.

These are warnings for the coordinator to act on, not gates on the agent.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import rules
from .config import Config

SHOUT = re.compile(r"(?<![`\w])(MUST|NEVER|ALWAYS|CRITICAL|IMPORTANT|DO NOT|DON'T|STOP|REQUIRED)(?![`\w])")
BUDGETS = {"SKILL.md": 2000, "AGENT_RULES.md": 2500, "WORKING_WITH_USER.md": 1500, "HEARTBEAT.md": 800,
           "LEAD_HANDOFF.md": 1500, "HANDOFF.md": 1500}
DEFAULT_BUDGET = 3000
MAX_RULES = 40
REVIEW_DAYS = 30
SPECIFIC = re.compile(r"\b[\w./\\-]+\.(?:jpe?g|png|webp|gif|tiff?|npy|npz|csv|mp4|py|ts|tsx|js|jsx|rs|go|java|c|cpp)\b(?::\d+)?"
                      r"|\b(?:photo|image|case|sample|issue|ticket)\s+#?\w*\d{3,}\b", re.I)


def tokens(text: str) -> int:
    """Rough token count (about 4 characters per token for English prose)."""
    return len(text) // 4


def check_text(name: str, text: str, budget: int | None = None) -> list[str]:
    out = []
    budget = budget or BUDGETS.get(Path(name).name, DEFAULT_BUDGET)
    n = tokens(text)
    if n > budget:
        out.append(f"{name}: about {n} tokens, over its budget of {budget}. Trim it: every agent reads all of it")
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    body = re.sub(r"`[^`]*`", "", body)
    hits = sorted(set(m.group(1) for m in SHOUT.finditer(body)))
    if hits:
        out.append(f"{name}: shouting ({', '.join(hits)}). Capitalised commands make newer models over-apply them; "
                   "say it plainly and give the reason")
    return out


def check_rule(text: str, why: str) -> list[str]:
    out = check_text("rule", text, budget=200)
    if not why.strip():
        out.append("rule has no --why: record the user's words or the incident, so agents can tell "
                   "where it applies and where it doesn't")
    m = SPECIFIC.search(text)
    if m:
        out.append(f"rule names one case ({m.group(0)}): state the general cause, and keep the case in --why")
    return out


def check_outcomes(live: list[dict], today: date | None = None) -> list[str]:
    today = today or date.today()
    out = []
    for r in live:
        results = [o["result"] for o in r.get("outcomes", [])]
        helped, hurt = results.count("helped"), results.count("hurt")
        users = r["by"] == "user" and not r.get("prevents")
        if hurt > helped:
            fix = "raise it with the user" if users else "reword, narrow or retire it"
            out.append(f"{r['id']} hurt more often than it helped ({hurt} to {helped}): {fix}")
        elif results and results[-1] == "recurred":
            out.append(f"{r['id']}: the failure came back with the rule in place. Reword it, make it a tool, or retire it")
        elif r.get("prevents") and not results:
            try:
                age = (today - date.fromisoformat(r["date"])).days
            except ValueError:
                continue
            if age >= REVIEW_DAYS:
                out.append(f"{r['id']} has no outcome after {age} days (should prevent: {r['prevents']}): check whether "
                           "that still happens, then log it or retire the rule")
    return out


def run(cfg: Config, extra: list[Path] | None = None, max_rules: int = MAX_RULES) -> list[str]:
    files = [cfg.agents_dir / n for n in ("AGENT_RULES.md", "WORKING_WITH_USER.md", "HEARTBEAT.md", "LEAD_HANDOFF.md")]
    for skills_root in (cfg.root / "skills", cfg.root / ".claude" / "skills", cfg.root / ".agents" / "skills"):
        files += sorted(skills_root.glob("*/SKILL.md"))
    files += list(extra or [])
    out = []
    for f in files:
        if f.exists():
            out += check_text(str(f.relative_to(cfg.root)) if f.is_relative_to(cfg.root) else str(f),
                              f.read_text(encoding="utf-8"))
    live = [r for r in rules.state(cfg).values() if r["status"] == "live"]
    bare = [r["id"] for r in live if not r.get("why")]
    if bare:
        out.append(f"rules without a reason: {', '.join(bare)}. Add the user's words or the incident, or retire them")
    for r in live:
        m = SPECIFIC.search(r["text"])
        if m:
            out.append(f"{r['id']} names one case ({m.group(0)}): state the general cause, and keep the case in its reason")
    out += check_outcomes(live)
    if len(live) > max_rules:
        out.append(f"{len(live)} live rules (more than {max_rules}): the more rules, the fewer get followed well. "
                   "Merge overlapping ones and retire what no longer serves the work")
    return out
