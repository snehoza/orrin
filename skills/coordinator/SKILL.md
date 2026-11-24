---
name: coordinator
description: Lead several coding agents working in parallel on one machine - split work into lanes, write briefs, launch and checkpoint agents, validate their results and merge. Use when asked to run parallel agents, coordinate lanes or worktrees, plan a multi-agent round, or review and merge work that other agents did.
license: MIT
compatibility: Any agent that can run shell commands and start other agents. Needs Python 3.11+ and the coordinator-kit package (pip install coordinator-kit). Uses git worktrees.
metadata:
  version: "1.0.0"
  repository: coordinator-kit
---

# Coordinator

You are the lead session. You plan and check; lane agents do the hands-on work. Every command is in [the command reference](references/COMMANDS.md).

Decisions marked **ask the user** belong to the person who owns the project. Stop and ask; don't decide them yourself.

## Set up once

1. `coordinator init docs/agents` writes the agent rules, the briefs, the handoff template, an `AGENTS.md` pointer and an example data registry.
2. Fill in the placeholders in `AGENT_RULES.md`: test commands, full checks, things never to do, the handoff path. Point the project's agent instruction file (`AGENTS.md`, `CLAUDE.md`, …) at it. Rules live in one place.
3. List the irreplaceable data and the goldens in `protected_data.json`, then run `coordinator data check`.
4. **Ask the user** which actions need their word every time. Push, deploy, delete and visible changes are the usual ones.

## Plan a round

1. Read `coordinator status`: what is running, who holds the machine lock, what the board says.
2. Split the work into **lanes** that touch different files. Give each lane one git worktree and branch.
3. Write each brief from `docs/agents/briefs/` with:
   - the worktree, the branch and the handoff path;
   - a goal with a concrete acceptance test;
   - the scope in and out;
   - any owner approval, quoted word for word with its date.

   An approval that is not in the brief doesn't count. Agents may not relay approvals to each other.
4. Pick the model per lane by the work:
   - the strongest model for design, debugging and changes to defaults;
   - a cheap model for mechanical work, proof runs and judging.

   Prefer the cheap one whenever it can do the job.
5. Size a lane from measured run times of similar lanes, never from human-style hour estimates.

## While lanes run

- Lanes own their rounds. Don't stop and resume an agent after every job.
- Wait on markers, not on agents: `coordinator wait <job> --timeout-min 3` in a background call, or let the lane hand back.
- **Quota and context checkpoints.** When an account nears its usage limit, or an agent's context is large enough that it starts re-reading or forgetting its brief:
  1. ask it to commit and update its handoff;
  2. relaunch it fresh from the handoff.

  A fresh agent with a 40-line handoff beats a degraded one.
- **Check activity before declaring a stall:** look at the job state, the log age and the board.
- **Machine sharing is solved by the lock, not by you.** Exclusive jobs queue first come, first served. Shared commands yield to them. Nobody needs to ask you for a slot.

## Accept a result

1. **Markers:** every job the lane relies on shows `COMPLETE=1` and `JOB_COMPLETE`.
2. **Receipts:** they come from the lane's own worktree and the intended interpreter, and the counts match. A receipt from the wrong checkout is invalid; this mistake is easy to make and silent.
3. **Evidence:** look at the key outputs yourself. Compare against the best earlier version, not only the previous step.
4. **Independent review:** a fresh agent that did not write the code reviews the branch diff. Use the cheap model for mechanical changes and the strong one for logic.
5. **Merge** when clean and allowed. Run the full checks on the merged result. **Ask the user** before anything visible, any push or any deploy.
6. At round end: `coordinator tidy`, then `coordinator tidy --apply` for its safe repairs.

## Judging outputs

Use the review brief that `coordinator init` writes (`docs/agents/briefs/review-round.md`):
- one item at a time, each ballot written before the next item is opened;
- batches of at most about 9 items, one fresh judge per batch;
- blind arms, with the key kept outside the pack;
- one unchanged control pair;
- a canary image first for any model whose image reading you haven't verified.

Spot-check the judges.

## Keep the rules healthy

- One place per fact. Rules live in `AGENT_RULES.md`, launch templates in `briefs/`, lane state in handoffs, history in an archive.
- To change a rule:
  1. quote the user's words with the date;
  2. replace the old rule in place;
  3. update the briefs in the same commit.
- When something goes wrong twice, turn the fix into a rule or a tool, not a reminder.
