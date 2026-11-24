# Heartbeat

The coordinator keeps working, unattended, by checking in on a fixed beat (`orrin.json` → `heartbeat.every_minutes`, 30 by default) and acting on what changed. Schedule the prompt below with whatever your agent harness offers: a recurring loop or cron command, a scheduled task, or an OS scheduler that sends the prompt to a running session.

## Check-in prompt

<!-- orrin:prompt -->
> Check-in. Run `orrin checkin --quiet`. Act on every item under NEEDS ATTENTION:
> - fix or relaunch failed jobs, then `orrin jobs ack` them;
> - nudge a quiet lane or agent, or resume it from its handoff;
> - make the status file and the lead handoff true;
> - checkpoint and relaunch lanes flagged as running too long or with too large a context;
> - plan the next work against the usage that is left, starting from the ready tasks (`orrin task list`) and skipping anything in SETTLED.md.
>
> When a lane hands back: verify its result (markers, receipts, an independent review), merge it if allowed, and start the next work.
> Stay inside the decision boundary in AGENT_RULES.md, and follow WORKING_WITH_USER.md. Ask the user only about what the boundary lists.
> Reply in 1–3 lines; one line if nothing changed.
<!-- /orrin:prompt -->

## Adapting the beat
- **Change the prompt** when the work changes, e.g. which lanes to watch or which proofs to relay: `orrin heartbeat set --file prompt.txt --why "<what changed>"`. The current prompt is rendered above, and every earlier version's reason is listed below. Reschedule the check-in with the new text.
- **Shorten the beat** while something time-sensitive runs. Lengthen it when everything is waiting on long jobs or on the user.
- **When usage runs low,** checkpoint the agents (commit, update the handoff) and plan around the reset instead of stopping cold.
