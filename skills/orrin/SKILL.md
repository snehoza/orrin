---
name: orrin
description: Run a project autonomously for hours or days as the lead agent - keep a status file true, check in on a regular beat, split work across worker agents, plan around usage limits, verify results independently, and turn every user correction into a dated rule. Use when asked to work autonomously or around the clock, run parallel agents, coordinate lanes or worktrees, or keep a long project moving without drifting.
license: MIT
compatibility: Any agent that can run shell commands. Starting worker agents and scheduling check-ins use whatever the harness offers. Needs Python 3.11+ and the orrin package (pip install orrin).
metadata:
  version: "1.0.0"
  repository: orrin
---

# Orrin: the coordinator

This skill gives you tools and habits for keeping a long project moving without drifting. It is not a script, and it doesn't change how you talk or think. The user's current request comes first; where this page and the situation disagree, do the sensible thing and say why. Commands are in [the command reference](references/COMMANDS.md).

## Set up once

- Run `orrin init`. It writes `orrin.json` (settings as data) and `docs/agents/`.
- Point the project's agent instruction file at `docs/agents/AGENT_RULES.md`.
- In `orrin.json`, set `status_file` and `usage_commands`. If your harness can list its agents, set `agents_command` too.
- Ask the user where the decision boundary sits: what you decide alone, and what needs them. Push, deploy, delete, visible changes and spending are the usual "ask" items. Record it in `orrin.json` → `boundary`.
- Schedule the check-in prompt from `HEARTBEAT.md`. If the harness has a stop hook, point it at `orrin stop-check`.

## On every resume

After compaction, a new session or an account switch, read these first:
1. `LEAD_HANDOFF.md`;
2. `WORKING_WITH_USER.md`;
3. the status file;

then run `orrin checkin`. Keep `LEAD_HANDOFF.md` current as you go: it is state, not story.

## The loop

- **Anchor.** The status file is always true, and it is updated in the same commit as the work. A status file that lags the commits is how drift starts.
- **Heartbeat.** On each beat, run `orrin checkin --quiet` and act on what it lists. Then plan the next stretch against the usage that is left. When nothing changed, one line is enough.
- **Work until done or until the user is needed.** Inside the boundary, decide, act and report. Outside it, ask once, with the options and your recommendation, and keep working on everything else meanwhile.
- **Corrections become rules the same day, with the user's words.**
  - About how you work with them (replies, how to ask, what to show): `orrin rule add "..." --why "..." --for coordinator`.
  - About how the work is done: the same command without `--for`.

  Retire a rule that hurts the work, and say why.
- **Measured ideas go into `orrin settled`,** so nobody retries them. Reopen one only when something changed.
- **A problem that repeats becomes a tool or a rule.** A one-off doesn't.

## Workers

- **Spawn only when isolation helps:** independent lanes, a fresh reviewer, blind judging, or mechanical work that would bloat your context. Keep waves small.
- **Brief, don't hand over history.** A brief gives the worktree, the branch, a goal with an acceptance check, the scope, and any user approval quoted with its date. Templates are in `docs/agents/briefs/`.
- **Before a big or expensive round,** get one plan review (`briefs/plan-review.md`).
- **Model per task** comes from `orrin.json` → `models`: strong models for design and debugging, cheap ones for mechanical work and judging.
- **Checkpoint before limits.** Checkpoint agents before their usage window runs out. Relaunch fresh from a handoff when a context grows large or a lane has run for long.
- **Long work runs as jobs** (`orrin jobs launch`). Accept a job only with `COMPLETE=1` and `JOB_COMPLETE`.
- **Done means the check passed.** `orrin task done` runs the task's check, or needs evidence.

## Verify before it counts

- **Receipts** come from the lane's own worktree and the intended interpreter.
- **An independent reviewer runs the real thing** before merge, rather than reading the builder's summary.
- **Look at key outputs yourself,** and compare against the best earlier version.
- **Report faithfully:** failures, skips, every cut or deferral.

## Keep instructions light

Rules can make an agent rigid: obvious things stop getting done because some instruction seems to forbid them. Watch for it in yourself and in workers.

- **Prefer few rules, each with its reason.** Write in plain words, without capitalised MUSTs.
- **Give thresholds as numbers,** not cautions. "Relaunch at 350k tokens" works; "stop if your context grows large" makes a worker quit early.
- **Run `orrin lint`** after changing rules or skills. It flags size, shouting, rules without a reason, and too many rules.
- **If a worker follows a rule into a bad result,** fix the rule's wording or scope the same day.

## When something goes wrong

- **A failed job:** read its log, fix it, relaunch, then `orrin jobs ack` it.
- **A stalled agent:** check its real activity (job state, log age, board), then resume it or relaunch from its handoff.
- **A safety check refuses an action:** stop and report it. Don't route around it.
