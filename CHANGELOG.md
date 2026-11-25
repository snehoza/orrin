# Changelog

## 1.0.0
First release.
- The loop:
  - `orrin checkin`: the heartbeat. Usage commands, jobs finished or failed since the last check-in, quiet and stale lanes, long lock waits, status-file drift.
  - `orrin rule add/retire/list/render`: dated rules that supersede each other, rendered into `AGENT_RULES.md` with the history in `RULES_HISTORY.md`.
  - `orrin rule add --prevents` and `orrin rule outcome`: what a rule should stop, and what it did; `orrin lint` lists rules to review and rules tied to one case.
  - `orrin task baseline` and `set-check`: only new failures count, and a check changed any other way is refused.
  - `orrin.json` and `orrin policy`: the status file, heartbeat, decision boundary and model policy, as data.
  - `orrin task add/claim/done/reopen/list`: a dependency-aware task list where done needs a passing check or a completed job.
  - `orrin jobs ack`: failures stay on the check-in until acknowledged.
  - The lead's memory layer: `rule add --for coordinator` (renders `WORKING_WITH_USER.md`), `orrin settled` (`SETTLED.md`, with lookalike tasks flagged), `orrin handoff` (`LEAD_HANDOFF.md`, flagged when stale), and `orrin heartbeat set` (the check-in prompt's history).
  - `orrin stop-check`: a stop-hook helper that keeps the lead going while it has work it can do, capped so it never loops.
  - `briefs/plan-review.md`: one reviewer, one pass, before a multi-lane or expensive round.
  - `orrin lint`: keeps instructions from making agents rigid (token budgets, capitalised commands, rules without a reason, too many rules); `rule add` warns at write time.
  - `agents_command`: the check-in reads the harness's own agent list (quiet agents, context size, strong models per account).
- `orrin jobs`: detached jobs with `.pid/.log/.done` markers, an exclusive/shared/no lock, a RAM guard, fail-fast, progress and ETA, smoke runs, and stop with the whole process tree.
- `orrin wait`: short blocking waits (exit 0 done, 1 failed, 3 still running).
- `orrin lock`: a fair FIFO machine lock with exclusive and shared modes; crash-safe; refuses nesting.
- `orrin board`, `status`, `tidy`, `data` (protected-data registry, archive-only cleanup), and `init` (rules frame, heartbeat prompt, lessons, briefs, handoff).
- Agent Skills: `orrin` (lead session) and `orrin-lane` (workers).
- Write-up: docs/WRITEUP.md.
