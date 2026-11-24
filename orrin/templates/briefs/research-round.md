# Research round: {topic}

- Worktree: `{worktree}`; branch: `{branch}`; handoff: `{handoff_path}`.
- Goal: {goal}; done when: a keep / reject / next-test verdict backed by numbers.
- OWNER APPROVED {date}: "{quote}"
- Read first: `{rules_path}`, `SETTLED.md`, then `{history_file}`.

## History check (write this first, in the design note)
- What was tried before on this problem, and why it failed.
- What is different this time. If nothing is, stop and report instead of repeating it.

## Round
1. State a falsifiable hypothesis, the baseline and the switch. The switch is off by default; product defaults don't change.
2. Use few arms and an evaluation set that covers the paths. Write down why each item is in it.
3. Reuse cached inputs and rerun only the stage your change affects. Prove the reuse is faithful with a byte-exact switch-off check on 1–2 items.
4. Save the numbers as JSON with the arm, metrics, provenance and verdict.
5. Score against ground truth where there is any. Count failures per item, not only pooled averages.
6. Add what you learned to `{history_file}` in the same commit as the result. Report every idea you measured and rejected, so the coordinator can add it to `SETTLED.md`.

## Report (at most 25 lines)
Verdict first, then a numbers table, cost and the recommendation, then the outputs worth a look and the commits.
