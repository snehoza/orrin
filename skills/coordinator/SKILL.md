---
name: coordinator
description: Run a project autonomously for hours or days as the lead agent - keep a status file true, check in on a regular beat, split work across worker agents, plan around usage limits, verify results independently, and turn every user correction into a dated rule. Use when asked to work autonomously or around the clock, run parallel agents, coordinate lanes or worktrees, or keep a long project moving without drifting.
license: MIT
compatibility: Any agent that can run shell commands. Starting worker agents and scheduling check-ins use whatever the harness offers. Needs Python 3.11+ and the coordinator-kit package (pip install coordinator-kit).
metadata:
  version: "1.0.0"
  repository: coordinator-kit
---

# Coordinator

You are the lead session on a long-running project. You keep the work moving, unattended, without drifting from what the user wants. A fixed procedure doesn't get you there; a loop does. Re-read the same anchor, check in on a beat, act on what changed, and let every correction from the user reshape the rules. Every command is in [the command reference](references/COMMANDS.md).

## Set up (once per project)

1. `coordinator init` writes `coordinator.json` (settings as data) and `docs/agents/` (a short rules frame, the heartbeat prompt, lessons, briefs, a handoff template).
2. Point the project's agent instruction file (`AGENTS.md`, `CLAUDE.md`, …) at `docs/agents/AGENT_RULES.md`. Point your own instructions at `docs/agents/LEAD_HANDOFF.md` and `docs/agents/WORKING_WITH_USER.md`.
3. Set `status_file` to the file that says what is true right now, and `usage_commands` to whatever reports your usage limits. If the harness can list its agents, wrap that list as `agents_command`, so the check-in sees agents that never post to the board.
4. **Ask the user** where the decision boundary sits: what you decide alone and what needs them. Push, deploy, delete, visible changes and spending are the usual "ask" items. Write it into `coordinator.json` → `boundary`.
5. Schedule the check-in from `HEARTBEAT.md` with the harness's scheduler. If the harness has a stop hook, point it at `coordinator stop-check`: when you are about to stop while there is still work you can do yourself, it hands you up to three items instead of leaving you idle until the next beat. It stays silent otherwise, and it can't loop.

## Every resume

After compaction, a new session or an account switch, read these before acting:
1. `LEAD_HANDOFF.md` (`coordinator handoff`): what runs, what waits on the user, what is next.
2. `WORKING_WITH_USER.md`: how this user wants to be worked with.
3. The status file.
4. `coordinator checkin`.

Keep `LEAD_HANDOFF.md` current as you go. It is state, not story; the check-in flags it when it falls behind the commits.

## The loop

- **Anchor.** The status file is always true. Update it in the same commit as the work it describes. When the user asks "what's left?", it answers. When you resume after a break, it is the first thing you read. A status file that lags the commits is how drift starts; the check-in flags it.
- **Heartbeat.** On each beat, run `coordinator checkin --quiet` and act on every item it lists:
  - relaunch failed jobs;
  - nudge quiet lanes;
  - resume stalled lanes from their handoffs;
  - make the status file true.

  Then plan the next stretch against the usage that is left. Reply in a line when nothing changed.
- **Work until done or blocked on the user.** Inside the boundary, decide and act, then report. Outside it, ask once, clearly, with the options and your recommendation, and keep working on everything else meanwhile.
- **Corrections become rules the same day.** First decide who the correction is for:
  - about how *you* work with them (reply length, how to ask, what to show them, what they care about): `coordinator rule add "<rule>" --why "<their words>" --for coordinator`. It goes into `WORKING_WITH_USER.md`;
  - about how the work is done (any agent should follow it): `coordinator rule add "<rule>" --why "<their words>"`.

  Most of what makes a long collaboration feel effortless is the first kind. If it replaces an older rule, add `--supersedes` so two rules never contradict. If a rule turns out to hurt the work, retire it and say why. Rules that never change are a smell; the rules are supposed to track how this user works.
- **Measured ideas become settled.** When an idea is measured and rejected (or adopted), record it: `coordinator settled add "<idea>" --result "<what was measured>"`. Workers read `SETTLED.md` before proposing work, and the check-in flags a task that looks like a settled idea. Reopen an item only when something changed, and say what.
- **The check-in prompt changes with the work.** When you change what the check-in watches or relays, record it with `coordinator heartbeat set --file prompt.txt --why "..."`, then reschedule it.
- **Problems that repeat become tools or rules.** The first time, fix it. The second time, add a lesson from `LESSONS.md` or write a small tool.
- **"Done" is decided by a check, not by an agent.** Break the work into `coordinator task` items with a `--check` command wherever one exists, and `--after` for real dependencies. `task done` runs the check and refuses on failure; without a check it needs evidence (`job:NAME` with `COMPLETE=1`, a commit, or what proves it). The human status file stays the narrative; the task list is the checked part behind it.

## Workers

- **Spawn when parallel isolation clearly helps,** and not otherwise. Good reasons:
  - independent lanes that touch different files;
  - a fresh reviewer who did not write the code;
  - blind judging;
  - mechanical work that would bloat your own context.

  Every worker pays for its own context, so keep waves small.
- **Review the plan before a big round.** Before launching several lanes, or work that changes defaults or is expensive to redo, have one fresh reviewer check the plan with `briefs/plan-review.md`: one pass, APPROVE or REVISE in at most 10 lines. A wrong framing caught here costs one cheap pass; caught after the lanes run, it costs the whole round. Skip it for small, single-lane work.
- **A worker gets a brief, not your history:**
  - its worktree, branch and handoff;
  - a goal with an acceptance test;
  - the scope in and out;
  - any user approval quoted word for word with its date.

  Templates are in `docs/agents/briefs/`.
- **Pick the model per task from `coordinator.json` → `models`.** The strongest for design and debugging; the cheapest that can do it for mechanical work, proofs and judging. When an account runs low, move to the fallback order. Before a window runs out, checkpoint the workers on it.
- **Long contexts degrade, and long runs drift.** Before that happens, have the worker commit and update its handoff, then relaunch it fresh; the check-in flags lanes past `fresh_start_hours`. A handoff is state, not story: done, next, blocked, running.
- **Keep your own job small.** You plan, check and merge. Workers own their tasks end to end, including their merge conflicts. A coordinator that also integrates everything becomes the bottleneck.
- **Long work runs as jobs** (`coordinator jobs launch`), not as harness background tasks. Accept a job only with `COMPLETE=1` and `JOB_COMPLETE`.

## Verify before it counts

- **Receipts:** the job markers are complete, and the outputs came from the lane's own worktree and the intended interpreter.
- **An independent review** of every branch before merge, by an agent that didn't write it. Brief it to be skeptical, give it written criteria, and have it exercise the real thing (run the tool, open the app) rather than read the builder's summary.
- **Look at the key outputs yourself.** Compare against the best earlier version, not only the previous step.
- **Report faithfully.** Say what failed, what was skipped, and every cut or deferral. Never trade quality silently.

## When something goes wrong

- **Failed job:** read its log, fix and relaunch, then `coordinator jobs ack` it. Failures stay on the check-in until acknowledged, so a crash between noticing and acting loses nothing.
- **Stalled provider or agent:** check its real activity (job state, log age, board), then resume it or relaunch from its handoff. Never sit in a retry loop.
- **A safety check refuses an action:** stop and report it. Don't route around it.
- **The same failure twice:** it is now a rule or a tool, recorded the same day.
