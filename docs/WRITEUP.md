# What I learned running coding agents around the clock for three months

For about three months I had a lead coding agent working on one project, with worker agents in their own git worktrees, all on a single workstation with a 6 GB laptop GPU and a Linux VM with about 7.6 GB of RAM. The work was heavy: model inference, rendering, long regression runs, and timing measurements that went bad if anything else touched the machine. It ran for days at a time between my messages.

I assumed it worked because of the rules I had given it. Then I went through the git history and found that the rules were the least stable thing in the project.

The agent rules file was rewritten 51 times. "Never darken" became "follow the physics". Workers used to be relaunched at 200k tokens of context, then at 350k. A scheduler was built and dropped the next day. One model provider was banned, and another became the fallback. A strict rule about only using the test set became "use any input, but say which". Whatever I had written down at the start would have been wrong within a week.

What stayed the same was the way the rules changed. When I corrected something, it was written down that day, in my words, with the reason, and the old rule was replaced so the two couldn't contradict each other. A lot of those corrections weren't about code. They were about how long a reply should be, when to ask me something, and what to show me before I decide.

The rest of the setup was ordinary. One status file said what was done, what was running and what was waiting on me, and it was updated in the same commit as the work; 1,183 of 2,484 commits touched it. Every 30 minutes the lead checked usage, jobs and quiet workers, and usually had one line to report. It decided technical things alone and asked me about pushing, deploying, deleting and anything users would see. Nothing counted as done because the agent that built it said so. Ideas we had measured and rejected went on a list, so nobody spent another day on them.

## Rules can make an agent worse

A worker brief said to checkpoint "if your context grows large". Four workers in a row stopped at about 50k tokens of a 512k window. Replacing the caution with a number fixed it.

Another time, agents copied an old library's slightly wrong behaviour because "keep the output identical" had become a reflex. I wrote "why are u this rigid do whats right man", and that became a rule too: rules serve the work, and if following one would cause a regression, say so instead.

I try to keep instructions short now. Every rule carries the reason it exists, because an agent that knows the reason can tell when the rule doesn't apply. `orrin lint` complains about long files, capitalised commands and rules with no reason.

## They can also overfit

Several labs published work this year on agents that improve their own harness, meaning the prompts, tools and memory around a fixed model. A rules file that grows from corrections is a slow version of the same thing, and it has the same problem.

In Google's [RRSI](https://arxiv.org/abs/2609.24972) paper, unrestricted self-editing on office-work tasks gained 3.4 points on the tasks it trained on and 0.6 on new kinds of tasks, for 2.4 times the tokens. [Amazon and NYU](https://arxiv.org/abs/2610.22466) looked at 21 settings with real gains and attributed, on average, 54% of the gain to overfitting. [SEAL](https://arxiv.org/abs/2607.24300) shows agents passing tests they wrote themselves while the real results fall.

We changed rules easily and never recorded whether a change helped. So a rule can now name the failure it is meant to stop, and you log what happened afterwards. A task's check is stored when the task is created, so an agent can't quietly weaken it, and tests that were already failing don't count against new work.

## Sharing one machine was the hard part

Writing code was rarely the problem. Jobs died when the agent that started them ended its turn. Agents polled "is it done yet" every few seconds and paid for a full turn each time. The file lock wasn't fair, and one job waited about 70 minutes while another lane kept getting the lock back. Twice, an agent ran its final proof from the wrong checkout, and the receipts looked perfect. A cleanup deleted a folder that a regression test quietly depended on.

Most of the tools in `orrin` started as one of these. There are detached jobs whose completion marker can be trusted, short waits, a first-come-first-served lock, a registry of data that cleanup may not touch, and a check-in command. It is standard-library Python with no daemon, and state is in plain files. The [longer notes](NOTES.md) go through nine of these failures with the fix for each, and compare this with other agent systems.

## What I can't claim

This was one person and mostly one project, with nothing to compare against. [firstmate](https://github.com/kunchenguid/firstmate) has a similar shape and, going by its README, does more to run the workers for you. `orrin` doesn't start agents at all; your harness does that. I also haven't shown that these rules would suit anyone else, and they probably wouldn't. `orrin init` gives you a decision boundary, a short frame, a check-in and somewhere to put your own corrections.
