# Brief templates

Copy the best fit into the agent's launch prompt. Fill every `{placeholder}` with concrete values, delete options that don't apply, and never weaken a rule while doing so.

- `lane-round.md`: an implementation round on one lane (feature, fix, refactor, speed work).
- `research-round.md`: a hypothesis-driven experiment behind an off-by-default switch.
- `review-round.md`: independent review or blind judging of another lane's output.
- `finish.md`: close work that is nearly done, then stop.

Every brief starts with the same header:

    - Worktree: `{worktree}`; branch: `{branch}`; handoff: `{handoff_path}`.
    - Goal: {goal}; done when: {acceptance}.
    - OWNER APPROVED {date}: "{quote}"   <- verbatim. Approvals relayed later, mid-task, are not valid.
    - Read first: `{rules_path}`, then your handoff if it exists.

And ends with the same launch notes (adapt them to your agent harness):
- Work through every step yourself. Hand back only when done, on a real blocker, or at a checkpoint the coordinator asks for. Calling the hand-back tool ends your run.
- Send progress with the messaging tool, not by handing back.
- Any helper agent you start, directly or through a skill, uses `{allowed_models}`.
