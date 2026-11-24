# Lane round: {lane}

- Worktree: `{worktree}`; branch: `{branch}`; handoff: `{handoff_path}`.
- Goal: {goal}; done when: {acceptance}.
- OWNER APPROVED {date}: "{quote}"
- Read first: `{rules_path}`, then `{handoff_path}` if it exists.

## Scope
- In: {in_scope}
- Out: {out_of_scope}
- Visible changes need the owner. Report them with before/after evidence; don't ship them.

## Round
1. Post to the board: `coordinator board set --lane {lane} --worktree {worktree} --activity "{goal}"`.
2. Read the history first: `{queue_or_failures_file}`. Don't retry a rejected idea unchanged.
3. Work in steps. For each step: change one thing, run the focused tests and the path-covering subset, commit.
4. Long work runs as jobs: smoke first, one early check, then `coordinator wait <job> --timeout-min 3`.
5. At the end: launch the full checks ({full_checks}) as jobs, write their names into the handoff, run `coordinator tidy`, and hand back.

## Report (at most 25 lines)
Verdict first, then numbers, then the 1–3 outputs worth a look (with what to see in each), then commits and running jobs. List every idea you did not get to.
