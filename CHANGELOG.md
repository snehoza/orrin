# Changelog

## 1.0.0
First release.
- The loop:
  - `coordinator checkin`: the heartbeat. Usage commands, jobs finished or failed since the last check-in, quiet and stale lanes, long lock waits, status-file drift.
  - `coordinator rule add/retire/list/render`: dated rules that supersede each other, rendered into `AGENT_RULES.md` with the history in `RULES_HISTORY.md`.
  - `coordinator.json` and `coordinator policy`: the status file, heartbeat, decision boundary and model policy, as data.
  - `coordinator task add/claim/done/reopen/list`: a dependency-aware task list where done needs a passing check or a completed job.
  - `coordinator jobs ack`: failures stay on the check-in until acknowledged.
  - The lead's memory layer: `rule add --for coordinator` (renders `WORKING_WITH_USER.md`), `coordinator settled` (`SETTLED.md`, with lookalike tasks flagged), `coordinator handoff` (`LEAD_HANDOFF.md`, flagged when stale), and `coordinator heartbeat set` (the check-in prompt's history).
  - `coordinator stop-check`: a stop-hook helper that keeps the lead going while it has work it can do, capped so it never loops.
  - `briefs/plan-review.md`: one reviewer, one pass, before a multi-lane or expensive round.
  - `coordinator lint`: keeps instructions from making agents rigid (token budgets, capitalised commands, rules without a reason, too many rules); `rule add` warns at write time.
  - `agents_command`: the check-in reads the harness's own agent list (quiet agents, context size, strong models per account).
- `coordinator jobs`: detached jobs with `.pid/.log/.done` markers, an exclusive/shared/no lock, a RAM guard, fail-fast, progress and ETA, smoke runs, and stop with the whole process tree.
- `coordinator wait`: short blocking waits (exit 0 done, 1 failed, 3 still running).
- `coordinator lock`: a fair FIFO machine lock with exclusive and shared modes; crash-safe; refuses nesting.
- `coordinator board`, `status`, `tidy`, `data` (protected-data registry, archive-only cleanup), and `init` (rules frame, heartbeat prompt, lessons, briefs, handoff).
- Agent Skills: `coordinator` (lead session) and `lane-agent` (workers).
- Write-up: docs/WRITEUP.md.
