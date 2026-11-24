# Plan review: {round}

Use before launching a round with several lanes, or work that changes defaults or is expensive to redo. Skip it for small, single-lane work. One fresh reviewer, one pass, on a cheap model unless the plan is mostly design.

- Plan: `{plan_path}` (goal, lanes with scope and acceptance tests, tasks and checks, the evaluation set, what is out of scope).
- Read: `{rules_path}`, `SETTLED.md`, the status file.

## Check
1. **Goal:** does the plan answer what the user actually asked? Quote the request and point at any mismatch.
2. **Settled:** does any lane retry something in `SETTLED.md` without saying what is different?
3. **Acceptance:** does every lane have a check that a separate agent could run? Is "done" decided by that check, not by the builder?
4. **Overlap:** do two lanes touch the same files or the same machine resource at the same time?
5. **Gaps:** is there a step that every later step depends on but that nobody owns? Is there a decision that only the user can make?
6. **Cost:** is the number of lanes and models proportionate to the work and the usage left?

## Reply (at most 10 lines)
`APPROVE` or `REVISE`, then one line per problem: what, where, the fix. Don't rewrite the plan.
