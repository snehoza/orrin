# Finish: {lane}

- Worktree: `{worktree}`; branch: `{branch}`; handoff: `{handoff_path}`.
- Goal: close {what} with evidence; done when: {acceptance}.
- OWNER APPROVED {date}: "{quote}"
- Read first: `{rules_path}`, then `{handoff_path}`.

## Finish
1. Start from the handoff. Check every job it lists: `orrin jobs status <job>`. Accept only `COMPLETE=1` with `JOB_COMPLETE`. Don't rerun completed work.
2. Verify the reported evidence: the receipts come from this worktree and the right interpreter, and the counts match.
3. Fill in the numbers, then commit the write-up and any code already in scope.
4. Update the handoff and run `orrin tidy`. Then stop there: no new experiments and no scope growth, because this brief is only for closing out.

## Report (at most 25 lines)
Verdict first, then numbers, commits and running jobs.
