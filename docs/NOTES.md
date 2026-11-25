# Notes behind the write-up

The reference version of [the write-up](WRITEUP.md): numbers, comparisons, and nine failures with the fix for each.

For about three months I built a project with a lead coding agent that ran around the clock and a rotating set of worker agents, each in its own git worktree, on one workstation:
- a 6 GB laptop GPU;
- a Linux VM with about 7.6 GB of RAM;
- several model accounts, each with its own usage window.

The work was a heavy GPU pipeline: model inference, rendering, long regression gates and careful timing runs.

The lead agent ran for days at a time, unattended between my messages. It:
- recovered from stalls;
- planned around the usage left on each account;
- launched, checkpointed and replaced workers;
- verified their results;
- merged clean work;
- stopped only when the work was done or genuinely needed me.

Over that time it stayed on what I wanted. These notes are about why. My first guess was "good rules", and the history says otherwise.

## Part 1: the loop

| From the project's history | Count |
|---|---|
| Commits | 2,484 |
| Commits that also updated the status file | 1,183, nearly half |
| Rewrites of the agent rules | 51, plus 26 of the instruction file and 23 of the brief templates |
| Dated quotes of my words inside the rules | 29, from 12 different days |
| Notes recording my corrections | 64, about 58 mentions of a rule being superseded |
| Small tools written along the way | 115 |
| Worker and helper agent transcripts | about 1,440, up to 140 in a day, across nine model families |

The rules were never stable, and most of the important ones were reversed at least once:
- "never darken" became "follow the physics";
- a strict test-set-only rule became "use any input, say which";
- a scheduler was built and dropped the next day;
- a memory setting was raised and reverted;
- a model provider was banned and another became the fallback;
- the context size at which workers are relaunched moved from 200k to 350k tokens;
- one model family was retired from judging;
- "don't over-test" arrived;
- and eventually a rule about the rules: they serve the work, and one that would cause a regression is flagged, not followed.

A fixed rule set would have been wrong within a week. What held still was a small loop:

1. **An anchor that is always true.** One status file says what is done, what is running and what waits on me. It is updated in the same commit as the work it describes, which is why it changed in nearly half of all commits. Every resume and every check-in starts by reading it, so a wrong belief can't survive long.
2. **A heartbeat.** Every 30 minutes a scheduled check-in looks at the same few things: usage left on each account, finished and failed jobs, quiet workers, and whether the status file is still true. Then it acts. Most check-ins are one line: nothing changed. This is what "autonomous" means in practice. It isn't a long plan executed blindly; it's a short look, repeated.
3. **Corrections become rules the same day,** in my words, with the date and the reason. The rule they replace is superseded in place, so two rules never contradict. Changing a rule is cheap, so rules stay right instead of just staying put. Most corrections were not about the code at all, but about how to work with me: how long a reply should be, when to ask and how, what to show before a decision, what not to bring up. Those live in the lead's own memory, separate from the agents' rules, and they are what makes a long collaboration feel effortless.
4. **A record of what was settled.** Ideas that were measured and rejected, with the number that rejected them, so nobody tries them again a week later. Every new round read it before proposing anything.
5. **The lead keeps its own handoff.** The lead's context gets compacted or the session ends, so a short state file says what runs, what waits on me and what comes next. Every resume starts there.
6. **A clear decision boundary.** The agent decides technical matters: design, tools, tests, which worker does what, which model, how many. It asks me only about push, deploy, deleting anything and changes users can see. That line is what makes unattended work safe: drift can't reach anything expensive without passing me.
7. **Checking is separate from building.** Receipts from the right checkout, a reviewer who didn't write the code, blind judges with controls. An autonomous system without this drifts into confident nonsense.
8. **Resources are chosen as the work goes.** Which model, how many workers, how much effort: decided per task, from the usage left. The strongest model does design and debugging, the cheapest one that can do the job does the rest, and the fallback order changed several times as accounts and providers changed.
9. **A problem that repeats becomes a tool or a rule.** Everything in Part 2 started as a failure that happened at least once.

The same shape turned up in the always-on personal agents that shipped in autumn 2026: OpenAI's dots, Anthropic's Claude Duet, xAI's Grok Bot and Meta's Muse. Each gives an agent its own computer, memory carried across sessions, and periodic check-ins instead of a live stream; Duet briefs you in the morning, then stays quiet until something needs you. Each also asks for approval before sensitive actions, and Grok Bot can run several bots that split the work. For coding, three things matter that those products don't advertise:
- **The state lives in git,** so every rule change is auditable.
- **The path from a correction to a rule is explicit.**
- **Every claimed result has to pass an evidence gate** before it counts.

## What other long-running agent systems found

Others building agents that run for hours or weeks arrived at the same parts, often by the same failures:

| System | What it found | Where it lives in the kit |
|---|---|---|
| Anthropic, [long-running harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | An initializer sets up the environment; later sessions read a progress file and git log, take one feature from a JSON list, verify it, commit. Agents only flip a feature to passing, which stops early "done" claims. | The status file and handoffs; `orrin task` with checks |
| Anthropic, [planner / generator / evaluator](https://www.anthropic.com/engineering/harness-design-long-running-apps) | Agents overrate their own work. A separate, skeptical evaluator with criteria that tests the live app beats self-critique. Context resets with structured handoffs beat compaction alone. | Independent review and blind judging; fresh relaunch from handoffs |
| OpenAI, [long-horizon Codex](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex) | A plan with milestones and validations, an operating manual, and a live status log that keeps the run inspectable. | Brief, `AGENT_RULES.md`, the status file |
| Cursor, [scaling agents](https://cursor.com/blog/scaling-agents) | A flat swarm churned. Planners that create tasks plus workers that own them end to end worked. A central integrator became a bottleneck. Periodic fresh starts are still needed against drift and tunnel vision. | Coordinator plans and checks; lanes own their work; `fresh_start_hours` |
| [Ralph loop](https://www.thoughtworks.com/radar/techniques/ralph-loop) | A fixed prompt in a loop, a fresh context each pass, and completion decided by tests rather than by the agent. | The heartbeat; `task done` runs the check |
| [Gas Town](https://cloudnativenow.com/features/gas-town-what-kubernetes-for-ai-coding-agents-actually-looks-like/) | Many agents with defined roles, and work state in git so restarts lose nothing. | Lanes, handoffs and rules in git; markers on disk |

| [firstmate](https://github.com/kunchenguid/firstmate) | You talk to one lead agent. It runs workers in separate worktrees, supervises them, keeps its state on disk and asks only for real decisions. A script waits on the workers, so waiting costs no tokens. | The same shape: a lead, lanes, a decision boundary, state on disk |
| [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) | Ready-made workflows with fixed stages and specialist roles. Its Ralph skill records which checks already fail before work starts. | `orrin task baseline` takes that one idea |

firstmate is the closest, and going by its README it does more to run the workers themselves. `orrin` doesn't start agents; your harness does. It adds the parts that grow with one person and one machine:
- **Rules are expected to change with the person.** Each correction is recorded with its date and reason, and replaces the rule it contradicts.
- **The machine is shared and small,** so fair locking, memory guards and quiet timing matter more than raw parallelism.

I compared against public descriptions, not by running the other systems.

## Rules that disable the agent

The opposite failure is just as real: instructions that make a capable agent worse. We hit it repeatedly:
- A worker brief said to checkpoint "if your context grows large". Four successive workers read that so cautiously that each stopped at about 50k tokens of a 512k window. The fix was a number: relaunch at about 350k.
- A hand-back tool described as "report when done" was used as a progress report, and the worker ended its run after setup, twice. The fix was to say what calling it does: it ends the run.
- Agents reproduced an old library's slightly wrong behaviour because "keep the output identical" had become a reflex. My words: "why are u this rigid do whats right man". It became a rule about the rules: they serve the work, and a rule that would cause a regression is flagged, not followed.

Research says the same thing:
- **Instruction-following drops as instructions pile up.** In IFScale, even the best models follow about 68% of 500 simultaneous instructions.
- **Long contexts degrade unevenly** (Chroma's context-rot study).
- **Newer models follow the system prompt closely.** Anthropic's guidance now says capitalised CRITICAL/MUST, written for older models, makes them over-trigger, and that instructions with their reasons generalise better than bare rules.
- **Skills should be short.** Anthropic's skill-authoring guide treats a skill's tokens as shared space and matches strictness to how fragile the task is.
- **Minimal harnesses** such as Pi go furthest: four tools and a system prompt under 1,000 tokens.

So the kit keeps instructions light on purpose:
- Every rule carries the user's words.
- The rules and skills say plainly that they are defaults, not a script, and that the user's current request comes first.
- Thresholds are numbers, not cautions.
- `orrin lint` flags instruction files over their token budget, capitalised commands, rules without a reason, rules tied to one case, and rule sets that have grown past about 40 rules.

## Rules that evolve can overfit

In 2026 several labs published work on agents that improve their own harness: the prompts, tools, memory and control flow around a fixed model. A rules file that grows from corrections is a small, slow version of that, so their failures apply here.

| Work | What it found |
|---|---|
| [RRSI](https://arxiv.org/abs/2609.24972), Google Cloud AI Research | Unrestricted self-editing overfits. On office-work tasks it gained 3.4 points on the tasks it trained on and 0.6 on new kinds, using 2.4 times the tokens. Small edits, a noise threshold, a critic and pruning raised new kinds by 3.9 at 1.6 times the tokens. |
| [Harness-Delta Attribution](https://arxiv.org/abs/2610.22466), Amazon and NYU | Across 21 settings with significant gains, on average 54% of the gain was overfitting and 14% was extra compute. |
| [SkillBoost](https://arxiv.org/abs/2607.26643), Alibaba and Zhejiang University | Learned skills overfit to a few cases. Accept a change only when it helps within a regression limit. |
| [CIG](https://arxiv.org/abs/2610.05039), NTU and Alibaba's Tongyi Lab | Link evidence, hypothesis, change and outcome, so a new result can overturn an old belief. |
| [VERSE](https://arxiv.org/abs/2610.02616), MIT and Amazon | In a controlled study, an optimizer that improved itself did not get better without checks that actually run. |
| [SEAL](https://arxiv.org/abs/2607.24300), Chinese Academy of Sciences | An agent that writes its own tests can pass them while real results fall. |
| [Cordis](https://arxiv.org/abs/2608.25512), Peking University and DeepSeek | Every component's effects should be fully reversible, so a running harness can change safely. |

The results are the authors' own. They exposed a gap: our rules changed easily, but nothing recorded whether a change worked. Four small additions came from this:
- **A rule can name the failure it should stop,** and `orrin rule outcome` logs whether it helped, hurt, or let the failure come back.
- **`orrin lint` lists rules to review.** My own preferences need no proof.
- **Rules tied to one file or case are flagged.** The general cause belongs in the rule; the case belongs in its reason.
- **A task's check is recorded when the task is added.** Changing it needs a reason, and changes to the files it runs are noted. This catches shortcuts, not a determined attacker.

There is no automatic harness search. It needs benchmarks and many runs, and the risk is paying for complexity that doesn't carry over.

The same caution applies to these notes. The evidence is one person, mostly one project, with no control group. The loop worked there; I haven't shown that it generalises.

## Part 2: what the loop produced

Writing code was not the hard part. Sharing one machine was: agents killed each other's measurements, waited on locks that never came free, burned their budgets polling, and trusted results that came from the wrong checkout. Each failure below happened at least once. Each fix is now a command in `orrin`, or a lesson you can adopt when its problem shows up.

## 1. Jobs died with the agent

**What happened:** an agent started a long job in the background and ended its turn. The job died with it. On Windows the agent's shell runs inside a job object, so `nohup` and `setsid` inside the Linux VM did not help: when the shell that started the VM process exited, the whole tree went with it.

**The fix:** a launcher that detaches properly:
- POSIX: a double fork and `setsid`;
- Windows: a hidden console, a new process group, and a break-away from the job object.

The detached runner writes its state to files: `.pid`, `.log`, and a `.done` marker with the exit code.

**The rule that came with it:** accept a job only when the marker says `COMPLETE=1` *and* the log ends with `JOB_COMPLETE <name>`. Exit codes alone lied more than once: a waiter that timed out, or a wrapper shell, reported its own status, not the job's.

```
orrin jobs launch --name lane1-gate -- python run_gate.py
orrin wait lane1-gate --timeout-min 3
```

## 2. Waiting cost more than working

I audited agent time across 12 lanes and 14.4 agent-hours:

| Where the time went | Share |
|---|---|
| Model turns (2,310 turns, median 6.4 s each) | ~33% |
| Provider stalls | ~23% |
| Waiting on jobs | ~22% |
| Actual commands and edits | ~13% |

Every turn re-sends the whole context, so the number of turns is the cost an agent controls. Two habits made it worse:
- **Polling.** "Is it done yet?" every few seconds. Each check is a full turn.
- **Long blocking waits.** Agents that blocked on a job for a long stretch left the coordinator's messages unread for up to ten minutes.

**The fix** is a middle path: `orrin wait` blocks for about three minutes, returns early when the job finishes or fails, and tells the agent to call again if it is still running (exit 3). With nothing else in that turn, an hour-long job costs about twenty cheap turns, and the agent hears messages between them. Jobs print `PROGRESS n/N`, which gives the status an ETA. A line starting `ERROR` stops the job at once instead of after the whole batch.

Alongside it, a written rule: **fewer, bigger turns.**
- Batch independent reads and edits into one response.
- Chain dependent shell steps.
- Read a file once, with a range big enough to cover what you need.

## 3. The lock was not fair

Heavy jobs shared one `flock`. It is correct, but not fair. A lane that released the lock and immediately relaunched usually got it back, and another lane's job waited **about 70 minutes** behind it.

**The fix:** FIFO tickets in front of the lock. Every waiter writes a numbered ticket, and only the head of the queue may enter. Short commands such as test suites take the lock in *shared* mode:
- shared holders run together;
- they never run beside an exclusive job;
- they never pass an exclusive ticket that is already waiting.

A stream of quick test runs therefore cannot starve a measurement. A holder that crashes is noticed by PID and process start time, so a reused PID does not count, and its ticket is dropped.

The shared mode exists because of a specific failure: a timing run was spoiled by another lane's test suite. Spoiled timing is the most expensive rerun there is. It costs the run, and it costs the hours of decisions taken from a wrong number before anyone notices.

## 4. The scheduler that was not needed

Before the FIFO lock, I built a real admission scheduler:
- per-job RAM and CPU budgets;
- thread grants;
- priorities;
- leases.

It was 779 lines. It worked, and it was dropped the next day. The jobs were too varied to budget accurately, and every misjudged budget either wasted the machine or overcommitted it. What replaced it was simpler and better:
- one exclusive lock for heavy work;
- a shared mode for light work;
- a **RAM guard** that *waits* for memory, up to 30 minutes, instead of refusing to start or letting the kernel kill something.

`orrin` ships only the simple version.

## 5. Proofs from the wrong checkout

Twice, an agent ran its final proof by calling the *main* checkout's copy of a tool instead of its own worktree's. The receipts looked perfect and proved nothing about the branch.

**The rule:** run tools from your own worktree, and check every receipt's root path and interpreter before trusting it. The coordinator checks the same two fields again before merging.

## 6. A cleanup broke the regression gate

A routine disk cleanup deleted a cache folder. The folder looked derived and rebuildable, but a regression golden quietly depended on it. The gate broke.

**The fix:** three tiers of data.

| Tier | What it is | What may happen to it |
|---|---|---|
| **Source** | Irreplaceable inputs | Never moved |
| **Golden** | Reference outputs | Must be self-contained: every input lives inside its own folder |
| **Cache** | Rebuildable outputs | The only tier that may move, and only to an archive, never deleted |

A registry file lists the sources and goldens. `orrin data check` fails when a golden reaches outside itself. `orrin data archive` refuses anything protected, and logs every move so it can be undone.

## 7. Approvals that were not approvals

Agents may message each other. That helps with machine scheduling and shared findings. But one agent passed on "the owner says it's fine" to another, and a safety check rightly refused to act on it.

**The rule:** an approval counts only when it is quoted word for word, with its date, in the agent's brief from the coordinator. Messages between agents are information, never instructions.

## 8. Judges that guessed

Visual comparisons were judged by separate agents. Three failures showed up:
- **One judge with a whole pack** stalled after 4 items.
- **Judges that opened every image first** and wrote their answers at the end mixed up items held together in context, and lost everything when they stalled.
- **One model reported that its image tool returned no pixels.** It had in fact read the images correctly; it did not trust that the attachment was its own result.

**The protocol now:**
1. One item at a time, with each ballot written to a file before the next image is opened.
2. At most about 9 items per judge.
3. Blind arms, with the answer key kept outside the pack.
4. One unchanged control pair. It measured judge noise at about ±0.05 rank.
5. A canary image first for any model whose image reading hasn't been verified.

## 9. Budgets and long contexts

**Usage windows.** Two strong-model agents on one account took its 5-hour window from 0 to 96% in about 50 minutes.

The fixes:
- **One strong agent per account.**
- **Cheap models for mechanical work:** installs, proof runs, receipts, judging. A 90-minute cheap-model lane moved its window about 3 points.
- **Checkpoints instead of degradation.** Before an agent's context grows large enough that it re-reads or forgets its brief, it commits and updates its handoff, and a fresh agent continues from there. The handoff's top section is kept to about 40 lines: state, next step, blockers, running jobs. It is cheap to read and complete enough to continue from.
- **Lanes hand back proofs; they don't babysit them.** A finished lane launches its final proof jobs, writes their names into the handoff and stops. The coordinator watches the markers, validates the receipts, gets an independent review of the diff, and merges.

## What is in the kit

| Command | Problem it solves |
|---|---|
| `orrin checkin` | The heartbeat: usage, failed jobs, quiet lanes, status-file drift (Part 1) |
| `orrin rule add / outcome / retire / render` | Rules that change with the user, with dates, quotes and history; `--for coordinator` for how to work with them (Part 1) |
| `orrin settled`, `orrin handoff`, `orrin heartbeat set` | What was already measured; the lead's own state; the check-in prompt's history (Part 1) |
| `orrin task` | Done decided by a check, not by the agent; old failures don't count, changed checks are refused |
| `orrin.json`, `orrin policy` | The decision boundary, models and budget, as data (Part 1) |
| `orrin jobs launch / status / log / stop` | Jobs that survive the agent, with markers that can't lie (§1, §2) |
| `orrin wait` | Short blocking waits (§2) |
| `orrin lock run [--shared]` | A fair, crash-safe machine lock (§3, §4) |
| `orrin board`, `status`, `tidy` | Who is doing what; one screen; stale state repaired without data loss |
| `orrin data` | Protected sources, self-contained goldens, archive-only cleanup (§6) |
| `orrin init` | The rules frame, heartbeat prompt, lessons, briefs and handoff template |
| `skills/orrin`, `skills/orrin-lane` | The method as Agent Skills, for the lead and for the workers |

The tools are small: standard-library Python, no daemon, state in plain files. They aren't the point. The kit starts you with almost no rules, a heartbeat and a way to record corrections, and lets your own rules grow from the way you work.
