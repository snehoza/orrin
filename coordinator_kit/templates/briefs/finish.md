# Finish: {lane}

- Worktree: `{worktree}`; branch: `{branch}`; handoff: `{handoff_path}`.
- Goal: close {what} with evidence; done when: {acceptance}.
- OWNER APPROVED {date}: "{quote}"
- Read first: `{rules_path}`, then `{handoff_path}`.

## Finish
1. Start from the handoff. Check every job it lists: `coordinator jobs status <job>`. Accept only `COMPLETE=1` with `JOB_COMPLETE`. Don't rerun completed work.
2. Verify the reported evidence: the receipts come from this worktree and the right interpreter, and the counts match.
3. Fill in the numbers, then commit the write-up and any code already in scope.
4. Update the handoff and run `coordinator tidy`. Then STOP: no new experiments, no scope growth.

## Report (at most 25 lines)
Verdict first, then numbers, commits and running jobs.
