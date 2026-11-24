# Agent rules

Every agent reads this file before working. It is short on purpose, and it changes often.

## How these rules work
- **They grow from corrections.** When the user corrects the work ("don't do that", "do it this way"), the coordinator records it the same day: `coordinator rule add "<rule>" --why "<the user's words>"`. A rule it replaces is superseded, not left beside it, so two rules never contradict.
- **They serve the work.** If following a rule would make the result worse in a case it wasn't written for, say so with evidence and propose the better option. Don't follow it into a regression, and don't quietly ignore it either.
- **Only the coordinator changes them.** Lane agents propose changes in their report.
- Old rules and why they changed are in `RULES_HISTORY.md`. Settings (status file, heartbeat, the decision boundary, models and budget) are data in `coordinator.json`.

## The loop
- **Anchor:** the status file (`coordinator.json` → `status_file`) is always true. Update it in the same commit as the work it describes. Every check-in re-reads it.
- **Heartbeat:** the coordinator runs `coordinator checkin` on a schedule (see `HEARTBEAT.md`) and acts on what changed: failed or stalled jobs, quiet lanes, usage left, a status file that fell behind.
- **Lanes:** one agent, one worktree, one branch, one handoff. A handoff is state, not story: what is done, what is next, what blocks, what is running.
- **Long work runs as jobs** (`coordinator jobs launch`). Accept a job only with `COMPLETE=1` and `JOB_COMPLETE`. Wait in short blocking calls (`coordinator wait --timeout-min 3`).
- **Check separately from building.** Results are verified by someone who didn't produce them (receipts, a reviewer, a blind judge) before they count.

<!-- coordinator:rules -->
<!-- /coordinator:rules -->
