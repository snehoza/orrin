# Changelog

## 1.0.0
First release.
- `coordinator jobs`: detached jobs with `.pid/.log/.done` markers, an exclusive/shared/no lock, a RAM guard, fail-fast, progress and ETA, smoke runs, stop with the whole process tree.
- `coordinator wait`: short blocking waits (exit 0 done, 1 failed, 3 still running).
- `coordinator lock`: a fair FIFO machine lock with exclusive and shared modes; crash-safe; refuses nesting.
- `coordinator board`, `status`, `tidy`, `data` (protected-data registry, archive-only cleanup), `init` (agent rules, briefs, handoff templates).
- Agent Skills: `coordinator` (lead session) and `lane-agent` (workers).
- Write-up: docs/WRITEUP.md.
