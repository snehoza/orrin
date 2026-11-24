# coordinator command reference

Global options go before the subcommand: `coordinator [--home DIR] [--out JOBS_DIR] <command> ...`.
- `--home`: shared state (default `$COORDINATOR_HOME`, else `~/.coordinator`). Every agent on the machine must use the same one.
- `--out`: jobs folder (default `<home>/jobs`).

## Jobs
| Command | What it does |
|---|---|
| `coordinator jobs launch --name N [options] -- CMD ARGS...` | Start CMD detached. Writes `job.json`, `N.pid`, `N.log`, `N.done` under `<jobs>/N/`. |
| `coordinator jobs status N` | State of one job: `starting`, `waiting-lock`, `waiting-ram`, `running`, `done`, `failed`, `stopped` or `stalled` (the runner died without a marker). Shows progress and ETA. |
| `coordinator jobs list` | All jobs. |
| `coordinator jobs log N [-n 20] [--grep RE]` | The last lines of the log, optionally filtered. |
| `coordinator jobs stop N` | Stop the job and its whole process tree. Its marker gets `REASON=stopped`. |

`jobs launch` options:
- `--lock exclusive|shared|none`: the machine lock held while the job runs. The default, `exclusive`, means heavy jobs run one at a time.
- `--lock-name NAME`: a separate lock, e.g. one per GPU. Default `machine`.
- `--lock-timeout-min M`: give up after M minutes in the queue (exit 76). Default 120.
- `--min-free-mb MB`: RAM guard. Wait until this much memory is available.
- `--ram-wait-min M`: how long to wait for that memory before giving up (exit 75). Default 30.
- `--cwd DIR`, `--env KEY=VALUE` (repeatable), `--lane NAME`.
- `--smoke N`: sets `COORDINATOR_SMOKE=N` for the command, so a batch job can run N items first.
- `--no-fail-fast`: don't stop on a line starting `ERROR `, `FATAL ` or `JOB_FATAL `.

What the job can print:
- `PROGRESS n/N`: per item; feeds status and the ETA.
- `ERROR …`, `FATAL …` or `JOB_FATAL …` at the start of a line: stops the job (fail fast).

The marker (`N.done`) reads `EXIT=<code> COMPLETE=<0|1> REASON=<ok|failed|fail-fast|stopped|lock-timeout|ram-guard|runner-error|stalled> <time>`. A job is accepted only when `COMPLETE=1` AND the log contains `JOB_COMPLETE N`.

## Waiting
`coordinator wait N [N2 ...] [--timeout-min 3] [--interval 2]` blocks until every job is done, any job fails, or the timeout passes.
- Exit 0: all done with `COMPLETE=1`.
- Exit 1: a job failed, was stopped or stalled.
- Exit 3: still running; call again.

Keep the timeout short (about 3 minutes) so messages can reach you between calls.

## Machine lock
| Command | What it does |
|---|---|
| `coordinator lock run [--shared] [--timeout-min M] [--label L] -- CMD` | Run CMD in the foreground while holding the lock. Returns CMD's exit code; 76 on timeout. |
| `coordinator lock status [--name NAME]` | Holders and the queue. |

- First come, first served.
- `exclusive` runs alone.
- `shared` runs beside other shared holders but waits for exclusive holders and never passes a queued exclusive ticket.
- Holders that die are dropped automatically.
- Nesting is refused.

Python API: `from coordinator_kit.lock import FairLock`, then `with FairLock(shared=False, label="bench", timeout=600): ...`.

## Lane board
| Command | What it does |
|---|---|
| `coordinator board set --lane L [--worktree W] [--branch B] [--model M] [--activity A] [--next J] [--eta T] [--job N] [--pid P]` | Create or update a lane's entry. |
| `coordinator board note --lane L --note "text"` | Append a finding. |
| `coordinator board show [--stale-hours 2]` | All entries, stale ones marked. |
| `coordinator board done --lane L` | Move the entry to `board/archive/`. |

An entry is stale when it was last updated more than `--stale-hours` ago, its `--pid` is gone, or its bound `--job` is no longer active. The board is information only.

## Status and tidy
| Command | What it does |
|---|---|
| `coordinator status [--json] [--recent-hours 24]` | Machine, locks, active and recent jobs, and the board. Read-only. |
| `coordinator tidy [--apply] [--keep-days 14]` | Finds dead lock tickets (always dropped), stalled jobs (`--apply` writes `REASON=stalled`), stale board entries (`--apply` archives them) and finished jobs older than the limit (`--apply` moves them to `jobs/archive/`). Deletes nothing. |

## Protected data
`coordinator data [--registry protected_data.json] <check|scan|archive>`
| Command | What it does |
|---|---|
| `check` | Every source and golden exists, and every golden input exists inside its golden. Exits 1 on any problem. |
| `scan ROOT [--json]` | Folders under ROOT with size, age and why each is protected. |
| `archive PATH... --to DIR [--apply]` | Move unprotected folders into DIR. Each move is logged to `DIR/ARCHIVE_LOG.jsonl`. Refuses sources, goldens, their inputs and any folder that contains one. Dry run without `--apply`. |

## Templates
`coordinator init [DIR]` writes these into DIR (default `docs/agents`), never overwriting:
- `AGENT_RULES.md`, `HANDOFF.md`, an `AGENTS.md` pointer and an example `protected_data.json`;
- `briefs/` with `lane-round`, `research-round`, `review-round` and `finish`.
