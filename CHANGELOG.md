# Changelog

## 1.0.0
First release.
- The loop:
  - `coordinator checkin`: the heartbeat. Usage commands, jobs finished or failed since the last check-in, quiet and stale lanes, long lock waits, status-file drift.
  - `coordinator rule add/retire/list/render`: dated rules that supersede each other, rendered into `AGENT_RULES.md` with the history in `RULES_HISTORY.md`.
  - `coordinator.json` and `coordinator policy`: the status file, heartbeat, decision boundary and model policy, as data.
- `coordinator jobs`: detached jobs with `.pid/.log/.done` markers, an exclusive/shared/no lock, a RAM guard, fail-fast, progress and ETA, smoke runs, and stop with the whole process tree.
- `coordinator wait`: short blocking waits (exit 0 done, 1 failed, 3 still running).
- `coordinator lock`: a fair FIFO machine lock with exclusive and shared modes; crash-safe; refuses nesting.
- `coordinator board`, `status`, `tidy`, `data` (protected-data registry, archive-only cleanup), and `init` (rules frame, heartbeat prompt, lessons, briefs, handoff).
- Agent Skills: `coordinator` (lead session) and `lane-agent` (workers).
- Write-up: docs/WRITEUP.md.
