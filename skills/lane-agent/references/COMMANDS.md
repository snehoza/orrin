# coordinator command reference

Global options go before the subcommand: `coordinator [--home DIR] [--out JOBS_DIR] [--config FILE] <command> ...`.
- `--home`: shared machine state (default `$COORDINATOR_HOME`, else `~/.coordinator`). Every agent on the machine must use the same one.
- `--out`: jobs folder (default `<home>/jobs`).
- `--config`: project settings (default: `coordinator.json` in the current folder or a parent).

## The loop
| Command | What it does |
|---|---|
| `coordinator init [ROOT] [--agents-dir docs/agents]` | Set up a project, never overwriting. Writes `coordinator.json` (settings as data) and, in the agents dir: `AGENT_RULES.md` (a short frame plus a generated block), `HEARTBEAT.md` (the check-in prompt), `LESSONS.md` (rules to adopt when their problem shows up), `HANDOFF.md`, an `AGENTS.md` pointer, an example `protected_data.json`, and `briefs/` (lane, research, review, finish). |
| `coordinator checkin [--quiet] [--no-usage] [--json]` | The heartbeat. Shows the output of each `usage_commands` entry ("unavailable" if one fails, never zero) and the jobs that finished OK since the last check-in. NEEDS ATTENTION lists:<br>• a usage line at or above `checkpoint_usage_percent`;<br>• failed, stopped or stalled jobs, kept until `jobs ack`;<br>• lanes quiet longer than `silent_lane_minutes` (unless their bound job is still running);<br>• stale lanes, and lanes running longer than `fresh_start_hours`;<br>• lock waits over 30 minutes;<br>• a status file that missed the last `status_stale_commits` commits;<br>• ready tasks when nothing is running.<br>`--quiet` prints one line when nothing needs attention. |
| `coordinator task add "TITLE" [--check CMD] [--after T1,T2] [--lane L]` | Add a task to `<agents_dir>/tasks.json`. `--check` is a shell command that must exit 0 before the task can be marked done. |
| `coordinator task claim T3 --lane L` | Claim a task. Refused while its dependencies are open or another lane holds it. |
| `coordinator task done T3 [--evidence job:NAME\|TEXT]` | Runs the check and refuses unless it passes. Without a check, evidence is required; `job:NAME` must be a job with `COMPLETE=1`. The evidence and the check's last output lines are recorded. |
| `coordinator task reopen T3 --why "REASON"` | It wasn't done after all. |
| `coordinator task list [--all] [--json]` | Open, claimed and blocked tasks; `--all` adds the done ones. |
| `coordinator rule add "TEXT" --why "WORDS" [--by user] [--section S] [--supersedes R3,R5]` | Record a rule with the user's words and the date, superseding older rules. Re-renders the rules. |
| `coordinator rule retire R7 --why "REASON"` | Drop a rule that no longer serves the work. |
| `coordinator rule list [--all] [--json]` | Live rules; `--all` adds the superseded and retired ones. |
| `coordinator rule render` | Rewrite the generated block of `AGENT_RULES.md` (decision boundary, models and budget, live rules) and `RULES_HISTORY.md`. Text outside the markers is kept. |
| `coordinator policy` | The settings in effect: `coordinator.json` merged with the defaults. |

`coordinator.json` keys:
- `agents_dir`, `status_file`;
- `heartbeat`: `every_minutes`, `silent_lane_minutes`, `status_stale_commits`, `fresh_start_hours`;
- `usage_commands`: a list of commands, each a string or a list of arguments;
- `boundary`: `decide` and `ask` lists;
- `models`: `roles`, `fallback`, `checkpoint_usage_percent`, `relaunch_context_tokens`.

## Jobs
| Command | What it does |
|---|---|
| `coordinator jobs launch --name N [options] -- CMD ARGS...` | Start CMD detached. Writes `job.json`, `N.pid`, `N.log`, `N.done` under `<jobs>/N/`. |
| `coordinator jobs status N` | State of one job: `starting`, `waiting-lock`, `waiting-ram`, `running`, `done`, `failed`, `stopped` or `stalled` (the runner died without a marker). Shows progress and ETA. |
| `coordinator jobs list` | All jobs. |
| `coordinator jobs log N [-n 20] [--grep RE]` | The last lines of the log, optionally filtered. |
| `coordinator jobs stop N` | Stop the job and its whole process tree. Its marker gets `REASON=stopped`. |
| `coordinator jobs ack N [--note TEXT]` | Mark a failed, stopped or stalled job as handled, so check-ins stop raising it. |

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
