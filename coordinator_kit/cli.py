"""The ``coordinator`` command."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

from . import __version__, board, checkin, data, jobs, lead, lock, rules, settled, status, stopcheck, tasks, tidy, wait
from .config import NAME as CONFIG_NAME, DEFAULT as CONFIG_DEFAULT, Config
from .home import home, human_age, tail_lines

TEMPLATES = ("AGENT_RULES.md", "HEARTBEAT.md", "LESSONS.md", "LEAD_HANDOFF.md", "HANDOFF.md", "AGENTS.md", "protected_data.json",
             "briefs/README.md", "briefs/lane-round.md", "briefs/research-round.md", "briefs/review-round.md",
             "briefs/finish.md", "briefs/plan-review.md")


def _dump(value) -> None:
    print(json.dumps(value, indent=2, default=str))


def _command(rest: list[str], parser) -> list[str]:
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        parser.error("give the command after --")
    return rest


# --- handlers -------------------------------------------------------------------------------------------

def cmd_init(a) -> int:
    root = Path(a.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cfg_path = root / CONFIG_NAME
    if cfg_path.exists():
        print(f"kept     {cfg_path} (exists)")
    else:
        cfg = dict(CONFIG_DEFAULT, agents_dir=a.agents_dir)
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote    {cfg_path}")
    cfg = Config(cfg_path)
    target = cfg.agents_dir
    src = resources.files("coordinator_kit").joinpath("templates")
    for rel in TEMPLATES:
        dest = target / rel
        if dest.exists():
            print(f"kept     {dest} (exists)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.joinpath(rel).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print(f"wrote    {dest}")
    rules.render(cfg)
    settled.render(cfg)
    print(f"rendered {target / 'AGENT_RULES.md'}, WORKING_WITH_USER.md, SETTLED.md")
    print("Next: point your agent instruction file at AGENT_RULES.md (see AGENTS.md), set status_file and "
          "usage_commands in coordinator.json, and schedule the check-in from HEARTBEAT.md.")
    return 0


def cmd_jobs(a) -> int:
    if a.jobs_cmd == "launch":
        env = {}
        for item in a.env:
            if "=" not in item:
                raise SystemExit(f"--env needs KEY=VALUE, got {item!r}")
            k, v = item.split("=", 1)
            env[k] = v
        rec = jobs.launch(a.name, _command(a.command, a.parser), out=a.out, root=a.home, cwd=a.cwd, env=env,
                          lock=a.lock, lock_name=a.lock_name, lock_timeout_s=a.lock_timeout_min * 60,
                          min_free_mb=a.min_free_mb, ram_wait_s=a.ram_wait_min * 60, fail_fast=a.fail_fast,
                          smoke=a.smoke, lane=a.lane)
        _dump(rec)
        return 0
    if a.jobs_cmd == "list":
        rows = jobs.list_jobs(a.out, a.home)
        if a.json:
            _dump(rows)
        else:
            for r in rows:
                print(wait.summary(r))
            if not rows:
                print("no jobs")
        return 0
    folder = jobs.resolve(a.job, a.out, a.home)
    if not (folder / "job.json").exists():
        print(f"no such job: {a.job}", file=sys.stderr)
        return 2
    if a.jobs_cmd == "status":
        row = jobs.status(folder)
        _dump(row) if a.json else print(wait.summary(row))
        return 0
    if a.jobs_cmd == "stop":
        print(wait.summary(jobs.stop(folder)))
        return 0
    if a.jobs_cmd == "ack":
        print(wait.summary(jobs.ack(folder, a.note or "")) + " (acknowledged)")
        return 0
    if a.jobs_cmd == "log":
        lines = tail_lines(folder / f"{folder.name}.log", 1 << 20)
        if a.grep:
            import re
            pattern = re.compile(a.grep)
            lines = [line for line in lines if pattern.search(line)]
        print("\n".join(lines[-a.lines:]))
        return 0
    raise AssertionError(a.jobs_cmd)


def cmd_wait(a) -> int:
    folders = [jobs.resolve(j, a.out, a.home) for j in a.jobs]
    for f in folders:
        if not (f / "job.json").exists():
            print(f"no such job: {f}", file=sys.stderr)
            return 2
    code, rows = wait.wait(folders, a.timeout_min * 60, a.interval)
    print("\n".join(wait.summary(r) for r in rows))
    if code == wait.EXIT_RUNNING:
        print(f"STILL RUNNING after {a.timeout_min:g} min: call wait again")
    return code


def cmd_lock(a) -> int:
    if a.lock_cmd == "status":
        st = lock.state(a.name, a.home)
        if a.json:
            _dump(st)
            return 0
        now = time.time()
        held = ", ".join(f"{h['label'] or h['pid']} ({h['mode']}, {human_age(now - h['since'])})" for h in st["holders"])
        print(f"LOCK {a.name}: " + (f"held by {held}" if held else "free"))
        for q in st["queue"]:
            print(f"  queued: {q['label'] or q['pid']} ({q['mode']}, waiting {human_age(now - q['since'])})")
        return 0
    cmd = _command(a.command, a.parser)
    timeout = None if a.timeout_min is None else a.timeout_min * 60
    label = a.label or " ".join(cmd)[:60]
    try:
        with lock.FairLock(a.name, shared=a.shared, label=label, timeout=timeout, root=a.home,
                           progress=lambda m: print(m, file=sys.stderr, flush=True)):
            return subprocess.call(cmd)
    except lock.LockTimeout as e:
        print(f"LOCK_TIMEOUT {e}", file=sys.stderr)
        return jobs.EXIT_LOCK


def cmd_board(a) -> int:
    if a.board_cmd == "show":
        rows = board.read(a.home, a.stale_hours, a.out)
        _dump(rows) if a.json else print(board.render(rows))
        return 0
    if a.board_cmd == "done":
        moved = board.done(a.lane, a.home)
        print(f"archived {moved}" if moved else f"no entry for {a.lane}")
        return 0
    if a.board_cmd == "note" and not a.note:
        a.parser.error("note needs --note")
    fields = {k: getattr(a, k, None) for k in board.FIELDS}
    row = board.update(a.lane, fields, a.note, a.pid, a.home)
    print(board.render(board.read(a.home, a.stale_hours, a.out)) if not a.json else json.dumps(row, indent=2))
    return 0


def cmd_status(a) -> int:
    d = status.collect(a.home, a.out, a.recent_hours)
    _dump(d) if a.json else print(status.render(d))
    return 0


def cmd_tidy(a) -> int:
    items = tidy.find(a.home, a.out, a.keep_days)
    if a.apply:
        tidy.apply(items, a.home, a.out)
    if a.json:
        _dump(items)
        return 0
    if not items:
        print("tidy: nothing to do")
    for it in items:
        verb = "fixed" if it.get("applied") else "would fix"
        print(f"{verb}: {it['kind']} {it['what']} ({it['detail']})")
    if items and not a.apply and any(not it.get("applied") for it in items):
        print("dry run: add --apply to make these repairs (nothing is deleted; old jobs move to jobs/archive)")
    return 0


def _cfg(a) -> Config:
    return Config.load(a.config)


def cmd_rule(a) -> int:
    cfg = _cfg(a)
    if a.rule_cmd == "add":
        e = rules.add(cfg, a.text, a.why or "", a.by, a.section,
                      [x.strip() for x in (a.supersedes or "").split(",") if x.strip()], audience=a.audience)
        rules.render(cfg)
        where = "WORKING_WITH_USER.md" if a.audience == "coordinator" else "AGENT_RULES.md"
        print(f"added {e['id']}" + (f", superseding {', '.join(e['supersedes'])}" if e["supersedes"] else "")
              + f"; rendered {cfg.agents_dir / where}")
        return 0
    if a.rule_cmd == "retire":
        rules.retire(cfg, a.id, a.why)
        rules.render(cfg)
        print(f"retired {a.id}; rendered")
        return 0
    if a.rule_cmd == "render":
        paths = rules.render(cfg)
        print("rendered " + ", ".join(map(str, paths)))
        return 0
    rows = [r for r in rules.state(cfg).values() if a.all or r["status"] == "live"]
    if a.json:
        _dump(rows)
        return 0
    for r in rows:
        tag = "" if r["status"] == "live" else f" [{r['status']}]"
        who = " for coordinator" if r.get("audience") == "coordinator" else ""
        print(f"{r['id']}{tag} ({r['section']}{who}, {r['by']} {r['date']}): {r['text']}")
    if not rows:
        print("no rules yet")
    return 0


def cmd_task(a) -> int:
    cfg = _cfg(a)
    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]  # noqa: E731
    try:
        if a.task_cmd == "add":
            t = tasks.add(cfg, a.title, a.check, split(a.after), a.lane)
        elif a.task_cmd == "claim":
            t = tasks.claim(cfg, a.id, a.lane)
        elif a.task_cmd == "done":
            t = tasks.done(cfg, a.id, a.evidence, a.home, a.out, a.check_timeout_min * 60)
        elif a.task_cmd == "reopen":
            t = tasks.reopen(cfg, a.id, a.why)
        else:
            rows = tasks.load(cfg)
            print(tasks.dumps(rows) if a.json else tasks.render(rows, a.all))
            return 0
    except tasks.TaskError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    print(tasks.render([t], show_all=True))
    return 0


def cmd_checkin(a) -> int:
    cfg = _cfg(a)
    d = checkin.collect(cfg, a.home, a.out, run_usage=not a.no_usage)
    _dump(d) if a.json else print(checkin.render(d, quiet=a.quiet))
    return 0


def cmd_settled(a) -> int:
    cfg = _cfg(a)
    if a.settled_cmd == "add":
        e = settled.add(cfg, a.idea, a.result, a.verdict, a.evidence)
        print(f"settled {e['id']} [{e['verdict']}]: {e['idea']}")
        return 0
    if a.settled_cmd == "reopen":
        settled.reopen(cfg, a.id, a.why)
        print(f"reopened {a.id}")
        return 0
    if a.settled_cmd == "check":
        hits = settled.matches(cfg, a.text)
        for h in hits:
            print(f"{h['id']} [{h['verdict']}] {h['idea']} -> {h['result']} (match {h['score']})")
        if not hits:
            print("nothing settled matches")
        return 1 if hits else 0
    rows = list(settled.items(cfg).values())
    if a.json:
        _dump(rows)
    else:
        for r in rows:
            print(f"{r['id']} [{r['verdict'] if r['status'] == 'settled' else 'reopened'}] {r['idea']} -> {r['result']}")
        if not rows:
            print("nothing settled yet")
    return 0


def cmd_heartbeat(a) -> int:
    cfg = _cfg(a)
    if a.hb_cmd == "set":
        text = Path(a.file).read_text(encoding="utf-8")
        lead.set_prompt(cfg, text, a.why)
        print(f"recorded; rendered {cfg.agents_dir / 'HEARTBEAT.md'}. Reschedule the check-in with the new prompt.")
        return 0
    print(lead.current_prompt(cfg) or "no prompt recorded yet")
    return 0


def cmd_handoff(a) -> int:
    cfg = _cfg(a)
    p = lead.handoff_path(cfg)
    if not p.exists():
        print(f"{p} does not exist yet (template: coordinator init)")
        return 1
    print(f"{p} (updated {human_age(time.time() - p.stat().st_mtime)} ago)")
    print(p.read_text(encoding="utf-8"))
    return 0


def cmd_policy(a) -> int:
    cfg = _cfg(a)
    print(f"# {cfg.path or '(no coordinator.json found; defaults)'}")
    _dump(cfg.data)
    return 0


def cmd_data(a) -> int:
    reg = data.Registry(a.registry)
    if a.data_cmd == "check":
        problems = reg.check()
        for p in problems:
            print("FAIL " + p)
        print(f"data check: {'FAILED' if problems else 'ok'} ({len(reg.entries)} entries)")
        return 1 if problems else 0
    if a.data_cmd == "scan":
        rows = data.scan(reg, a.root)
        if a.json:
            _dump(rows)
        for r in rows if not a.json else []:
            mark = f"KEEP ({r['protected']})" if r["protected"] else "archivable"
            print(f"{r['bytes'] / 2**20:10.1f} MiB  {r['age_days']:6.1f} d  {mark:40s} {r['path']}")
        return 0
    plan = data.archive(reg, a.paths, a.to, apply=a.apply)
    for r in plan:
        if r["refused"]:
            print(f"REFUSED  {r['path']}: {r['refused']}")
        else:
            print(f"{'moved  ' if r.get('moved') else 'would move'} {r['path']} -> {r['target']}")
    if not a.apply:
        print("dry run: add --apply to move (logged to ARCHIVE_LOG.jsonl in the archive folder)")
    return 1 if any(r["refused"] for r in plan) else 0


# --- parser ---------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coordinator", description=(
        "Run several coding agents on one machine: detached jobs with markers, a fair machine lock, "
        "short waits, a lane board, status, tidy and protected data."))
    p.add_argument("--version", action="version", version=f"coordinator-kit {__version__}")
    p.add_argument("--home", help="shared state folder (default $COORDINATOR_HOME or ~/.coordinator)")
    p.add_argument("--out", help="jobs folder (default <home>/jobs)")
    p.add_argument("--config", help="project settings (default: coordinator.json in this folder or a parent)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="set up a project: coordinator.json, agent rules, heartbeat, lessons, briefs, handoff")
    s.add_argument("root", nargs="?", default=".", help="project root (default: here)")
    s.add_argument("--agents-dir", default="docs/agents")
    s.set_defaults(func=cmd_init)

    r = sub.add_parser("rule", help="rules that evolve: add, retire, list, render")
    rs = r.add_subparsers(dest="rule_cmd", required=True)
    ra = rs.add_parser("add", help='coordinator rule add "rule" --why "what the user said" [--supersedes R3]')
    ra.add_argument("text")
    ra.add_argument("--why", help="the user's words (or the incident) behind it")
    ra.add_argument("--by", default="user")
    ra.add_argument("--section", default="General")
    ra.add_argument("--for", dest="audience", choices=("agents", "coordinator"), default="agents",
                    help="agents: every agent follows it; coordinator: how the lead works with this user")
    ra.add_argument("--supersedes", help="comma-separated rule ids this replaces")
    rr = rs.add_parser("retire", help="drop a rule that no longer serves the work")
    rr.add_argument("id")
    rr.add_argument("--why", required=True)
    rl = rs.add_parser("list")
    rl.add_argument("--all", action="store_true", help="include superseded and retired rules")
    rl.add_argument("--json", action="store_true")
    rs.add_parser("render", help="rewrite the generated block of AGENT_RULES.md and RULES_HISTORY.md")
    r.set_defaults(func=cmd_rule)

    c = sub.add_parser("checkin", help="the heartbeat: usage, finished/failed jobs, quiet lanes, status-file drift")
    c.add_argument("--quiet", action="store_true", help="one line when nothing needs attention")
    c.add_argument("--no-usage", action="store_true", help="skip the usage commands")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_checkin)

    pol = sub.add_parser("policy", help="show the project settings in effect (coordinator.json merged with defaults)")
    pol.set_defaults(func=cmd_policy)

    se = sub.add_parser("settled", help="ideas already measured: don't redo them")
    ses = se.add_subparsers(dest="settled_cmd", required=True)
    sa = ses.add_parser("add", help='coordinator settled add "idea" --result "what was measured" [--verdict rejected]')
    sa.add_argument("idea")
    sa.add_argument("--result", required=True)
    sa.add_argument("--verdict", default="rejected", choices=("rejected", "adopted", "parked"))
    sa.add_argument("--evidence", default="")
    sr = ses.add_parser("reopen", help="something changed that makes it worth another look")
    sr.add_argument("id")
    sr.add_argument("--why", required=True)
    sc = ses.add_parser("check", help="does this idea match something settled?")
    sc.add_argument("text")
    sl = ses.add_parser("list")
    sl.add_argument("--json", action="store_true")
    se.set_defaults(func=cmd_settled)

    hb = sub.add_parser("heartbeat", help="the check-in prompt, with its history")
    hbs = hb.add_subparsers(dest="hb_cmd", required=True)
    hset = hbs.add_parser("set", help="record a new check-in prompt and why the work needs it")
    hset.add_argument("--file", required=True, help="text file with the new prompt")
    hset.add_argument("--why", required=True)
    hbs.add_parser("show", help="print the current prompt")
    hb.set_defaults(func=cmd_heartbeat)

    ho = sub.add_parser("handoff", help="the lead's own handoff: where it is and how current")
    ho.set_defaults(func=cmd_handoff)

    sc = sub.add_parser("stop-check", help="for a harness stop hook: keep the lead going while it has work it can do")
    sc.set_defaults(func=lambda a: stopcheck.main(_cfg(a), a.home, a.out))

    tk = sub.add_parser("task", help="a task list where done needs evidence: add, claim, done, reopen, list")
    tks = tk.add_subparsers(dest="task_cmd", required=True)
    ta = tks.add_parser("add")
    ta.add_argument("title")
    ta.add_argument("--check", help="shell command that must exit 0 before the task can be marked done")
    ta.add_argument("--after", help="comma-separated task ids that must be done first")
    ta.add_argument("--lane")
    tc = tks.add_parser("claim")
    tc.add_argument("id")
    tc.add_argument("--lane", required=True)
    td = tks.add_parser("done", help="runs the check; refuses unless it passes (or evidence is given and valid)")
    td.add_argument("id")
    td.add_argument("--evidence", default="", help="job:NAME (must be COMPLETE=1), a commit, or what proves it")
    td.add_argument("--check-timeout-min", type=float, default=30)
    tr = tks.add_parser("reopen")
    tr.add_argument("id")
    tr.add_argument("--why", required=True)
    tl = tks.add_parser("list")
    tl.add_argument("--all", action="store_true", help="include done tasks")
    tl.add_argument("--json", action="store_true")
    tk.set_defaults(func=cmd_task)

    j = sub.add_parser("jobs", help="detached jobs with completion markers")
    js = j.add_subparsers(dest="jobs_cmd", required=True)
    jl = js.add_parser("launch", help="start a detached job: coordinator jobs launch --name N -- CMD ...")
    jl.add_argument("--name", required=True)
    jl.add_argument("--lock", choices=("exclusive", "shared", "none"), default="exclusive",
                    help="machine lock while it runs (default exclusive: heavy jobs run one at a time)")
    jl.add_argument("--lock-name", default="machine")
    jl.add_argument("--lock-timeout-min", type=float, default=120)
    jl.add_argument("--min-free-mb", type=int, default=0, help="RAM guard: wait until this much memory is free")
    jl.add_argument("--ram-wait-min", type=float, default=30)
    jl.add_argument("--cwd")
    jl.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    jl.add_argument("--no-fail-fast", dest="fail_fast", action="store_false",
                    help="don't stop on the first ERROR/FATAL/JOB_FATAL line")
    jl.add_argument("--smoke", type=int, help="set COORDINATOR_SMOKE=N for the command (run only N items first)")
    jl.add_argument("--lane", default="")
    jl.add_argument("command", nargs=argparse.REMAINDER)
    jl.set_defaults(parser=jl)
    for name, helptext in (("status", "state of one job"), ("stop", "stop a job and its whole process tree"),
                           ("log", "the last lines of a job's log"),
                           ("ack", "mark a failed/stopped/stalled job as handled so check-ins stop raising it")):
        x = js.add_parser(name, help=helptext)
        x.add_argument("job", help="job name or job folder")
        x.add_argument("--json", action="store_true")
        if name == "ack":
            x.add_argument("--note", help="what was done about it")
        if name == "log":
            x.add_argument("-n", "--lines", type=int, default=20)
            x.add_argument("--grep", help="only lines matching this regular expression")
    jli = js.add_parser("list", help="all jobs")
    jli.add_argument("--json", action="store_true")
    j.set_defaults(func=cmd_jobs)

    w = sub.add_parser("wait", help="block a few minutes on jobs; exit 0 done, 1 failed, 3 still running")
    w.add_argument("jobs", nargs="+")
    w.add_argument("--timeout-min", type=float, default=3)
    w.add_argument("--interval", type=float, default=2)
    w.set_defaults(func=cmd_wait)

    lk = sub.add_parser("lock", help="the fair machine lock")
    lks = lk.add_subparsers(dest="lock_cmd", required=True)
    lr = lks.add_parser("run", help="run a command while holding the lock: coordinator lock run [--shared] -- CMD")
    lr.add_argument("--shared", action="store_true", help="share with other short commands; still yields to exclusive jobs")
    lr.add_argument("--name", default="machine")
    lr.add_argument("--timeout-min", type=float)
    lr.add_argument("--label")
    lr.add_argument("command", nargs=argparse.REMAINDER)
    lr.set_defaults(parser=lr)
    ls = lks.add_parser("status")
    ls.add_argument("--name", default="machine")
    ls.add_argument("--json", action="store_true")
    lk.set_defaults(func=cmd_lock)

    b = sub.add_parser("board", help="the lane board (information only)")
    bs = b.add_subparsers(dest="board_cmd", required=True)
    for name in ("set", "note", "show", "done"):
        x = bs.add_parser(name)
        x.add_argument("--json", action="store_true")
        x.add_argument("--stale-hours", type=float, default=2.0)
        if name != "show":
            x.add_argument("--lane", required=True)
        if name in ("set", "note"):
            for field in board.FIELDS:
                x.add_argument("--" + field)
            x.add_argument("--pid", type=int)
            x.add_argument("--note")
        x.set_defaults(parser=x)
    b.set_defaults(func=cmd_board)

    st = sub.add_parser("status", help="locks, jobs, board and machine on one screen")
    st.add_argument("--json", action="store_true")
    st.add_argument("--recent-hours", type=float, default=24)
    st.set_defaults(func=cmd_status)

    t = sub.add_parser("tidy", help="find stale state; --apply repairs it without losing data")
    t.add_argument("--apply", action="store_true")
    t.add_argument("--keep-days", type=float, default=14)
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_tidy)

    d = sub.add_parser("data", help="protected-data registry and archive-only cleanup")
    d.add_argument("--registry", default="protected_data.json")
    ds = d.add_subparsers(dest="data_cmd", required=True)
    ds.add_parser("check", help="sources and goldens exist; goldens are self-contained")
    dsc = ds.add_parser("scan", help="folders under ROOT with size, age and protection")
    dsc.add_argument("root")
    dsc.add_argument("--json", action="store_true")
    da = ds.add_parser("archive", help="move unprotected folders to an archive (dry run unless --apply)")
    da.add_argument("paths", nargs="+")
    da.add_argument("--to", required=True)
    da.add_argument("--apply", action="store_true")
    d.set_defaults(func=cmd_data)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.home:
        home(a.home)
    try:
        return a.func(a)
    except (ValueError, FileExistsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
