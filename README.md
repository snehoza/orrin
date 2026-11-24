# coordinator-kit

Keep a coding agent working on a project around the clock, alone or with a team of worker agents, without it drifting from what you want.

What makes that work isn't a fixed rule set. It is a small loop:
- **An anchor:** a status file that is always true.
- **A heartbeat:** a check-in on a regular beat that looks at usage, jobs and workers, then acts.
- **Rules from corrections:** each correction becomes a dated rule the same day, and the rule it replaces is superseded.
- **A decision boundary:** what the agent decides alone, and what needs you.
- **Independent verification** of every result.

The kit gives you that loop and the tools that grew out of running it:

- **`coordinator checkin`**: the heartbeat. Usage from any provider, failed or stalled jobs, quiet workers, a status file that fell behind the commits.
- **A memory layer for the lead:** `WORKING_WITH_USER.md` (how this user wants to be worked with, built from their corrections with `rule add --for coordinator`), `LEAD_HANDOFF.md` (the lead's own state, flagged when stale), `SETTLED.md` (ideas already measured, so nobody retries them; the check-in flags lookalike tasks) and the check-in prompt's own history.
- **Agents from your harness:** `agents_command` wraps any harness's agent list. The check-in then sees agents that never post: quiet ones, ones with too large a context, and two strong models on one account.
- **`coordinator stop-check`** for a harness stop hook: the lead keeps going when it still has work it can do (at most three short items, capped, never for things that need you), instead of idling until the next beat.
- **`coordinator task`**: a task list where "done" needs a passing check or a completed job as evidence, so agents can't declare victory early.
- **`coordinator rule add/retire`**: rules that evolve, with your words, the date and their history. Rendered into the agents' rules file along with the decision boundary and model policy from `coordinator.json`.
- **Detached jobs** survive the agent that started them, and their completion markers can't lie. **Short blocking waits** keep agents cheap and still able to hear messages.
- **A fair machine lock,** first come first served, with an exclusive mode for heavy work and a shared mode for tests. It is safe when a holder crashes.
- **A lane board, one status screen, and tidy,** which repairs stale state without losing data.
- **A protected-data registry:** cleanup only ever archives.
- **Two [Agent Skills](https://agentskills.io):** one for the lead session, one for workers. Plus brief and handoff templates, and a list of lessons to adopt when their problem shows up.

Standard-library Python 3.11+, no daemon, state in plain files. Linux, macOS and Windows.

Why it works, with numbers from a three-month project, and the failures behind each tool, are in [the write-up](https://github.com/snehoza/coordinator-kit/blob/main/docs/WRITEUP.md).

## Install

    pip install coordinator-kit

This gives you the `coordinator` command (`python -m coordinator_kit` works too).

## Thirty seconds of it

```sh
# run a long job detached, holding the machine lock (exclusive by default)
coordinator jobs launch --name lane1-tests --min-free-mb 2000 -- python -m pytest -q

# wait up to 3 minutes; exit 0 done, 1 failed, 3 still running (call again)
coordinator wait lane1-tests

# a short command that must not run beside heavy jobs
coordinator lock run --shared -- python scripts/check.py

# who is doing what
coordinator board set --lane lane1 --worktree ../proj-lane1 --activity "speed round" --next "timing run" --eta 15:30
coordinator status
```

What `status` looks like:

```
MACHINE: 16 CPUs | available 6120 MiB | load 38%
LOCK machine: held by lane2-gate (exclusive, 12m)
  queued: lane1-timing (exclusive, waiting 3m)
JOBS (3 active or recent):
  lane2-gate: running [lane2] 41/99 eta 17m
  lane1-timing: waiting-lock [lane1]
  lane3-smoke: done [lane3]
LANE BOARD (information only; decisions go through the coordinator)
lane1: live | gpt-x | speed round | next timing run eta 15:30 | updated 4m ago
```

## Jobs

`coordinator jobs launch --name N -- CMD` starts CMD detached, so it survives the agent's turn, terminal and session. Its files go in `~/.coordinator/jobs/N/`:

| File | Contents |
|---|---|
| `N.log` | Everything CMD prints |
| `N.pid` | The runner's PID and process start time |
| `N.done` | `EXIT=<code> COMPLETE=<0|1> REASON=<ok|failed|fail-fast|stopped|lock-timeout|ram-guard|...> <time>` |

A job is accepted only with `COMPLETE=1` in the marker **and** `JOB_COMPLETE N` in the log.

Before CMD runs, the runner:
- waits for the machine lock (`--lock exclusive|shared|none`);
- waits for free memory (`--min-free-mb`).

While CMD runs:
- a line starting `ERROR `, `FATAL ` or `JOB_FATAL ` stops it at once;
- `PROGRESS n/N` lines feed the ETA;
- `--smoke 1` sets `COORDINATOR_SMOKE=1`, so a batch job can run one item first.

`coordinator jobs stop N` stops CMD's whole process tree.

## The lock

`exclusive` holders run alone. `shared` holders run together, but never beside an exclusive holder and never ahead of an exclusive ticket that is already waiting. Waiters are served in arrival order. Holders that die are noticed by PID and start time, and dropped. Nesting is refused, because it would deadlock.

From Python:

```python
from coordinator_kit.lock import FairLock

with FairLock(label="benchmark", timeout=600):
    run_benchmark()
```

## Set up the loop

```sh
coordinator init                      # coordinator.json + docs/agents/
```

`coordinator init` writes:
- `coordinator.json`: settings as data:
  - the status file;
  - the heartbeat (beat, quiet-lane minutes, status drift);
  - `usage_commands`;
  - the decision `boundary` (`decide` and `ask`);
  - `models` (roles, fallback order, checkpoint threshold).
- `docs/agents/AGENT_RULES.md`: a short frame plus a generated block (decision boundary, models and budget, live rules). Point your `AGENTS.md` or `CLAUDE.md` at it.
- `docs/agents/HEARTBEAT.md`: the check-in prompt. Schedule it with your harness's loop or cron.
- `docs/agents/LESSONS.md`: rules from a real project, each tied to the symptom that calls for it. Adopt one when you see its symptom, not on day one.
- `docs/agents/briefs/` (lane, research, review/judging, finish), `HANDOFF.md`, and an example `protected_data.json`.

Then the coordinator records corrections as they come:

```sh
coordinator rule add "Wait in 3-minute blocking calls" --why "long waits left agents deaf for 10 min" --supersedes R4
coordinator rule list --all
coordinator checkin --quiet
```

The skills in [`skills/`](https://github.com/snehoza/coordinator-kit/tree/main/skills) follow the open Agent Skills format:
- `coordinator` is for the lead session: anchor, heartbeat, corrections, workers, verification.
- `lane-agent` is for workers: jobs, waits, the lock, the board, handoffs.

To install them, copy the folders into your agent's skills directory, e.g. `.claude/skills/` for Claude Code; other agents document where skills live. They need only a shell and Python. Every command is listed in [`COMMANDS.md`](https://github.com/snehoza/coordinator-kit/blob/main/skills/coordinator/references/COMMANDS.md).

## Protected data

```sh
coordinator data --registry protected_data.json check              # sources exist; goldens are self-contained
coordinator data --registry protected_data.json scan ./outputs     # size, age, and why each folder is kept
coordinator data --registry protected_data.json archive ./outputs/old-run --to ../archive --apply
```

`archive` moves folders and logs each move. It refuses sources, goldens, their inputs and any folder that contains one. Nothing is ever deleted.

## State

Shared state lives in `~/.coordinator`. Set `COORDINATOR_HOME` or `--home` to put it elsewhere. Every agent on the machine must use the same location, so the default is per user, not per repository. On Windows with WSL, pick one side for jobs and locks: a Windows process and a Linux process do not see each other's PIDs.

## Related

[speedloop](https://github.com/snehoza/speedloop) does noise-aware speed measurement. It came out of the same project, and works well inside `coordinator jobs`.

## License

MIT
