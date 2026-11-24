# coordinator-kit

Run several coding agents on one machine without them tripping over each other.

- **Detached jobs** survive the agent that started them and write completion markers that can't lie.
- **Short blocking waits** keep agents cheap and still able to hear messages.
- **A fair machine lock**, first come first served, has an exclusive mode for heavy work and a shared mode for tests. It is safe when a holder crashes.
- **A lane board** shows who is doing what. **One status screen** covers the machine, the lock, jobs and the board. **Tidy** repairs stale state without losing data.
- **A protected-data registry** keeps sources and self-contained goldens safe, and cleanup only ever archives.
- **Agent rules, briefs and a handoff template** come with the method written in, plus two [Agent Skills](https://agentskills.io): one for the lead session, one for the workers.

Standard-library Python 3.11+, no daemon, state in plain files. Linux, macOS and Windows.

The method, and the failures behind each part of it, are in [the write-up](https://github.com/snehoza/coordinator-kit/blob/main/docs/WRITEUP.md).

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

## For agents

`coordinator init docs/agents` writes:
- `AGENT_RULES.md`: the working rules, with placeholders for your project;
- `briefs/`: lane round, research round, review/judging round and finish;
- `HANDOFF.md`;
- an `AGENTS.md` pointer;
- an example `protected_data.json`.

The skills in [`skills/`](https://github.com/snehoza/coordinator-kit/tree/main/skills) follow the open Agent Skills format:
- `coordinator` is for the lead session: plan lanes, brief, checkpoint, validate, merge.
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
