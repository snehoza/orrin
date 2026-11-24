# Heartbeat

The coordinator keeps working, unattended, by checking in on a fixed beat (`coordinator.json` → `heartbeat.every_minutes`, 30 by default) and acting on what changed. Schedule the prompt below with whatever your agent harness offers: a recurring loop or cron command, a scheduled task, or an OS scheduler that sends the prompt to a running session.

## Check-in prompt

> Check-in. Run `coordinator checkin --quiet`. Act on every item under NEEDS ATTENTION:
> - fix or relaunch failed jobs, then `coordinator jobs ack` them;
> - nudge a quiet lane, or resume it from its handoff;
> - make the status file true;
> - checkpoint and relaunch lanes flagged as running too long;
> - plan the next work against the usage that is left, starting from the ready tasks (`coordinator task list`).
>
> When a lane hands back: verify its result (markers, receipts, an independent review), merge it if allowed, and start the next work.
> Stay inside the decision boundary in AGENT_RULES.md, and ask the user only about what is listed there.
> Reply in 1–3 lines; one line if nothing changed.

## Adapting the beat
- **Change the prompt** when the work changes, e.g. which lanes to watch or which proofs to relay. Write down what changed in the status file.
- **Shorten the beat** while something time-sensitive runs. Lengthen it when everything is waiting on long jobs or on the user.
- **When usage runs low,** checkpoint the agents (commit, update the handoff) and plan around the reset instead of stopping cold.
