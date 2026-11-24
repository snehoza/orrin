import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from coordinator_kit import board, checkin, cli, data, jobs, lock, procs, rules, tasks, tidy, wait
from coordinator_kit.config import Config

PY = sys.executable
ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p))


def dead_pid() -> int:
    p = subprocess.Popen([PY, "-c", "pass"])
    p.wait()
    return p.pid


class Home(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"

    def tearDown(self):
        for row in jobs.list_jobs(root=self.home):
            if row["state"] not in ("done", "failed", "stopped", "stalled"):
                jobs.stop(Path(row["dir"]))
                wait.wait([Path(row["dir"])], 20, 0.2)
        self._tmp.cleanup()

    def waiter(self, label, shared=False, timeout=30):
        """A separate process that takes the lock, prints its label, holds briefly, releases."""
        code = (f"import time;from coordinator_kit.lock import FairLock\n"
                f"with FairLock(shared={shared}, label={label!r}, root={str(self.home)!r}, poll=0.05, timeout={timeout}):\n"
                f"    print('IN', {label!r}, time.time(), flush=True); time.sleep(0.4)\n"
                f"    print('OUT', {label!r}, time.time(), flush=True)\n")
        return subprocess.Popen([PY, "-c", code], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def wait_queue(self, n, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(lock.state(root=self.home)["queue"]) >= n:
                return
            time.sleep(0.05)
        self.fail(f"queue never reached {n}")


class LockTests(Home):
    def test_exclusive_is_first_come_first_served(self):
        held = lock.FairLock(root=self.home, label="me").acquire()
        procs_ = []
        for i, label in enumerate(["a", "b", "c"]):
            procs_.append(self.waiter(label))
            self.wait_queue(i + 1)
        held.release()
        events = []
        for p in procs_:
            out, _ = p.communicate(timeout=30)
            events += [(float(t), kind, lab) for kind, lab, t in (line.split() for line in out.splitlines())]
        order = [lab for _, kind, lab in sorted(events) if kind == "IN"]
        self.assertEqual(order, ["a", "b", "c"])
        # never two exclusive holders at once
        spans = {lab: [t for t, k, l2 in events if l2 == lab] for lab in "abc"}
        for x, y in (("a", "b"), ("b", "c")):
            self.assertLessEqual(max(spans[x]), min(spans[y]) + 1e-3)

    def test_shared_holders_overlap_but_yield_to_a_queued_exclusive(self):
        s1 = lock.FairLock(shared=True, root=self.home, label="s1").acquire()
        s2 = self.waiter("s2", shared=True, timeout=5)  # enters beside s1
        out, _ = s2.communicate(timeout=30)
        self.assertEqual(s2.returncode, 0)
        self.assertIn("IN s2", out)
        ex = self.waiter("ex")
        self.wait_queue(1)
        late = self.waiter("late", shared=True, timeout=1)  # may not jump ahead of the waiting exclusive job
        out, _ = late.communicate(timeout=30)
        self.assertNotEqual(late.returncode, 0)
        self.assertNotIn("IN late", out)
        s1.release()
        out, _ = ex.communicate(timeout=30)
        self.assertIn("IN ex", out)
        self.assertEqual(lock.state(root=self.home)["queue"], [])

    def test_dead_holder_is_dropped(self):
        base = lock.lock_dir(root=self.home)
        (base / "holders").mkdir(parents=True)
        (base / "holders" / "00000000000000000001-1-dead.json").write_text(
            json.dumps({"pid": dead_pid(), "ident": None, "mode": "exclusive", "label": "crashed", "since": 0}))
        with lock.FairLock(root=self.home, timeout=5, poll=0.05):
            pass
        self.assertEqual(lock.state(root=self.home)["holders"], [])

    def test_nesting_is_refused(self):
        with lock.FairLock(root=self.home):
            with self.assertRaises(lock.NestedLock):
                lock.FairLock(root=self.home, shared=True).acquire()


class JobTests(Home):
    def launch(self, name, code, **kw):
        kw.setdefault("lock", "none")
        jobs.launch(name, [PY, "-c", code], root=self.home, **kw)
        return jobs.resolve(name, root=self.home)

    def test_success_writes_both_markers(self):
        folder = self.launch("ok", "print('PROGRESS 1/2');print('PROGRESS 2/2')", lock="exclusive")
        code, rows = wait.wait([folder], 30, 0.1)
        self.assertEqual(code, wait.EXIT_OK, rows)
        self.assertTrue(rows[0]["complete"])
        self.assertEqual(rows[0]["progress"]["done"], 2)
        self.assertIn("JOB_COMPLETE ok", (folder / "ok.log").read_text())
        self.assertEqual(lock.state(root=self.home)["holders"], [])

    def test_nonzero_exit_is_failed(self):
        folder = self.launch("bad", "import sys; sys.exit(3)")
        code, rows = wait.wait([folder], 30, 0.1)
        self.assertEqual((code, rows[0]["exit_code"], rows[0]["reason"]), (wait.EXIT_FAILED, 3, "failed"))

    def test_fail_fast_stops_the_job(self):
        t0 = time.monotonic()
        folder = self.launch("ff", "import time; print('FATAL broke', flush=True); time.sleep(60)")
        code, rows = wait.wait([folder], 30, 0.1)
        self.assertEqual((code, rows[0]["reason"]), (wait.EXIT_FAILED, "fail-fast"))
        self.assertLess(time.monotonic() - t0, 25)

    def test_stop_kills_the_tree(self):
        folder = self.launch("long", "import time; print('PROGRESS 0/1', flush=True); time.sleep(120)")
        code, _ = wait.wait([folder], 2, 0.1)
        self.assertEqual(code, wait.EXIT_RUNNING)
        jobs.stop(folder)
        code, rows = wait.wait([folder], 30, 0.1)
        self.assertEqual((code, rows[0]["state"], rows[0]["exit_code"]), (wait.EXIT_FAILED, "stopped", jobs.EXIT_STOPPED))

    def test_ram_guard_gives_up_with_75(self):
        folder = self.launch("ram", "print('never')", min_free_mb=10**9, ram_wait_s=0)
        _, rows = wait.wait([folder], 30, 0.1)
        if procs.available_mb() is None:
            self.skipTest("free memory unknown on this platform")
        self.assertEqual((rows[0]["exit_code"], rows[0]["reason"]), (jobs.EXIT_RAM, "ram-guard"))

    def test_lock_timeout_gives_76_and_smoke_env(self):
        with lock.FairLock(root=self.home):
            folder = self.launch("locked", "print('never')", lock="exclusive", lock_timeout_s=0.5)
            _, rows = wait.wait([folder], 30, 0.1)
        self.assertEqual((rows[0]["exit_code"], rows[0]["reason"]), (jobs.EXIT_LOCK, "lock-timeout"))
        folder = self.launch("smoke", "import os; print('SMOKE', os.environ['COORDINATOR_SMOKE'])", smoke=1)
        wait.wait([folder], 30, 0.1)
        self.assertIn("SMOKE 1", (folder / "smoke.log").read_text())

    def test_dead_runner_is_stalled_and_tidy_marks_it(self):
        folder = jobs.jobs_dir(root=self.home) / "ghost"
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({"name": "ghost", "created": time.time()}))
        (folder / "ghost.pid").write_text(json.dumps({"pid": dead_pid(), "ident": None}))
        self.assertEqual(jobs.status(folder)["state"], "stalled")
        items = tidy.apply(tidy.find(self.home), self.home)
        self.assertTrue(any(i["kind"] == "job-stalled" and i["applied"] for i in items))
        self.assertEqual(jobs.status(folder)["reason"], "stalled")

    def test_duplicate_name_refused(self):
        self.launch("dup", "pass")
        with self.assertRaises(FileExistsError):
            self.launch("dup", "pass")
        with self.assertRaises(ValueError):
            self.launch("../escape", "pass")


class BoardTests(Home):
    def test_set_note_stale_done(self):
        board.update("alpha", {"activity": "tests", "worktree": "/w/a"}, root=self.home)
        board.update("alpha", note="found the slow step", root=self.home)
        board.update("beta", {"activity": "idle"}, pid=dead_pid(), root=self.home)
        rows = {r["lane"]: r for r in board.read(self.home)}
        self.assertFalse(rows["alpha"]["stale"])
        self.assertEqual(rows["alpha"]["notes"][-1]["text"], "found the slow step")
        self.assertIn("process gone", rows["beta"]["stale_reasons"])
        later = {r["lane"]: r for r in board.read(self.home, now=time.time() + 3 * 3600)}
        self.assertTrue(later["alpha"]["stale"])
        self.assertIn("LANE BOARD", board.render(board.read(self.home)))
        board.update("gamma", {"job": "never-launched"}, root=self.home)
        gamma = next(r for r in board.read(self.home) if r["lane"] == "gamma")
        self.assertIn("bound job missing", gamma["stale_reasons"])
        board.done("gamma", self.home)
        moved = board.done("alpha", self.home)
        self.assertTrue(moved.exists())
        self.assertEqual([r["lane"] for r in board.read(self.home)], ["beta"])


class DataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for d in ("data/raw", "goldens/v1/inputs", "cache/a", "cache/b", "loose"):
            (self.root / d).mkdir(parents=True)
            (self.root / d / "f.bin").write_bytes(b"x" * 10)
        self.reg_path = self.root / "protected_data.json"
        self.write([{"id": "raw", "path": "data/raw", "kind": "source"},
                    {"id": "g1", "path": "goldens/v1", "kind": "golden", "inputs": ["goldens/v1/inputs"]},
                    {"id": "c", "path": "cache", "kind": "cache"}])

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, entries):
        self.reg_path.write_text(json.dumps({"entries": entries}))

    def test_check_flags_missing_and_not_self_contained(self):
        self.assertEqual(data.Registry(self.reg_path).check(), [])
        self.write([{"id": "g2", "path": "goldens/v1", "kind": "golden", "inputs": ["cache/a", "goldens/v1/gone"]}])
        problems = data.Registry(self.reg_path).check()
        self.assertTrue(any("outside the golden" in p for p in problems))
        self.assertTrue(any("input missing" in p for p in problems))

    def test_archive_moves_cache_and_refuses_protected(self):
        reg = data.Registry(self.reg_path)
        arch = self.root / "archive"
        plan = data.archive(reg, [self.root / "cache/a", self.root / "data/raw", self.root / "data",
                                  self.root / "goldens/v1/inputs"], arch, apply=True)
        refused = {Path(r["path"]).name: r["refused"] for r in plan}
        self.assertIsNone(refused["a"])
        self.assertIn("source", refused["raw"])
        self.assertIn("contains", refused["data"])
        self.assertIn("golden", refused["inputs"])
        self.assertTrue((arch / "a" / "f.bin").exists())
        self.assertFalse((self.root / "cache/a").exists())
        self.assertTrue((self.root / "data/raw/f.bin").exists())
        self.assertEqual(len((arch / "ARCHIVE_LOG.jsonl").read_text().splitlines()), 1)

    def test_scan_and_dry_run(self):
        reg = data.Registry(self.reg_path)
        rows = {Path(r["path"]).name: r for r in data.scan(reg, self.root)}
        self.assertIsNotNone(rows["data"]["protected"])
        self.assertIsNone(rows["loose"]["protected"])
        data.archive(reg, [self.root / "loose"], self.root / "archive")
        self.assertTrue((self.root / "loose").exists())

    def test_bad_kind_rejected(self):
        self.write([{"id": "x", "path": "p", "kind": "precious"}])
        with self.assertRaises(ValueError):
            data.Registry(self.reg_path)


class CliTests(Home):
    def run_cli(self, *args):
        return subprocess.run([PY, "-m", "coordinator_kit", "--home", str(self.home), *args], env=ENV,
                              capture_output=True, text=True, timeout=60)

    def test_end_to_end(self):
        r = self.run_cli("jobs", "launch", "--name", "e2e", "--lane", "alpha", "--", PY, "-c", "print('PROGRESS 1/1')")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("wait", "e2e", "--timeout-min", "0.5", "--interval", "0.1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("COMPLETE=1", r.stdout)
        self.run_cli("board", "set", "--lane", "alpha", "--activity", "e2e", "--job", "e2e")
        r = self.run_cli("status")
        self.assertIn("e2e: done", r.stdout)
        self.assertIn("bound job done", r.stdout)
        r = self.run_cli("lock", "run", "--shared", "--", PY, "-c", "import sys; sys.exit(4)")
        self.assertEqual(r.returncode, 4)
        r = self.run_cli("jobs", "log", "e2e", "--grep", "JOB_")
        self.assertIn("JOB_COMPLETE e2e", r.stdout)
        self.assertIn("would fix", self.run_cli("tidy").stdout)

    def test_init_writes_every_template_once(self):
        root = Path(self._tmp.name) / "proj"
        self.assertEqual(cli.main(["init", str(root)]), 0)
        target = root / "docs" / "agents"
        for rel in cli.TEMPLATES:
            self.assertTrue((target / rel).is_file(), rel)
        self.assertTrue((root / "coordinator.json").is_file())
        rules_text = (target / "AGENT_RULES.md").read_text()
        self.assertIn("## Decision boundary", rules_text)
        self.assertIn("None yet", rules_text)
        (target / "HANDOFF.md").write_text("mine")
        cli.main(["init", str(root)])
        self.assertEqual((target / "HANDOFF.md").read_text(), "mine")
        json.loads((target / "protected_data.json").read_text())


class RuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "coordinator.json").write_text(json.dumps({"models": {"fallback": ["a", "b"]}}))
        self.cfg = Config.load(self.root / "coordinator.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_supersede_retire_render(self):
        r1 = rules.add(self.cfg, "Never dim the floor.", "no darker floors", section="Quality", date="2026-10-01")
        r2 = rules.add(self.cfg, "Wait 10 minutes per call.", date="2026-10-02")
        r3 = rules.add(self.cfg, "Follow real-life lighting.", "the old rule is dumb", supersedes=[r1["id"]],
                       section="Quality", date="2026-10-21")
        rules.retire(self.cfg, r2["id"], "agents went deaf", date="2026-10-29")
        st = rules.state(self.cfg)
        self.assertEqual(st["R1"]["status"], "superseded")
        self.assertEqual(st["R1"]["superseded_by"], "R3")
        self.assertEqual(st["R1"]["by"], "user")
        self.assertEqual((st["R2"]["status"], st["R3"]["status"]), ("retired", "live"))
        target, history = rules.render(self.cfg)
        text = target.read_text()
        self.assertIn('Follow real-life lighting. (R3; user 2026-10-21: "the old rule is dumb")', text)
        self.assertNotIn("Never dim", text)
        self.assertIn("a -> b", text)
        h = history.read_text()
        self.assertIn("superseded by R3", h)
        self.assertIn("retired: agents went deaf", h)
        # rendering twice is stable and keeps hand-written text outside the markers
        target.write_text("# Mine\nhand text\n" + text[text.index(rules.BEGIN):] + "\nafter\n")
        rules.render(self.cfg)
        again = target.read_text()
        self.assertTrue(again.startswith("# Mine\nhand text\n"))
        self.assertTrue(again.rstrip().endswith("after"))
        self.assertEqual(again.count(rules.BEGIN), 1)
        with self.assertRaises(ValueError):
            rules.add(self.cfg, "x", supersedes=["R99"])
        with self.assertRaises(ValueError):
            rules.retire(self.cfg, "R1", "already superseded")


class CheckinTests(Home):
    def test_flags_failures_quiet_lanes_and_status_drift(self):
        proj = Path(self._tmp.name) / "proj"
        proj.mkdir()
        (proj / "coordinator.json").write_text(json.dumps({
            "heartbeat": {"status_stale_commits": 2, "silent_lane_minutes": 1},
            "usage_commands": [[PY, "-c", "print('5h 40% used')"], ["definitely-not-a-command-xyz"]]}))
        git = lambda *a: subprocess.run(["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                        capture_output=True, check=True)
        git("init", "-q")
        (proj / "TODO.md").write_text("status")
        git("add", "-A")
        git("commit", "-q", "-m", "status")
        for i in range(2):
            (proj / f"f{i}").write_text(str(i))
            git("add", "-A")
            git("commit", "-q", "-m", f"work {i}")
        cfg = Config.load(proj / "coordinator.json")
        jobs.launch("broke", [PY, "-c", "import sys; sys.exit(2)"], root=self.home, lock="none")
        wait.wait([jobs.resolve("broke", root=self.home)], 30, 0.1)
        board.update("alpha", {"activity": "x"}, root=self.home)
        row = json.loads((board.board_dir(self.home) / "alpha.json").read_text())
        row["updated"] -= 600
        (board.board_dir(self.home) / "alpha.json").write_text(json.dumps(row))
        d = checkin.collect(cfg, self.home)
        text = "\n".join(d["attention"])
        self.assertIn("job broke failed", text)
        self.assertIn("lane alpha quiet", text)
        self.assertIn("not updated in the last 2 commits", text)
        self.assertTrue(d["usage"][0]["ok"])
        self.assertIn("40% used", d["usage"][0]["lines"][0])
        self.assertFalse(d["usage"][1]["ok"])
        # a failure stays on the list until it is acknowledged
        d2 = checkin.collect(cfg, self.home, run_usage=False)
        self.assertTrue(any("broke" in a for a in d2["attention"]))
        jobs.ack(jobs.resolve("broke", root=self.home))
        board.update("alpha", {"activity": "y"}, root=self.home)
        (proj / "TODO.md").write_text("status 2")
        git("add", "-A")
        git("commit", "-q", "-m", "status")
        d3 = checkin.collect(cfg, self.home, run_usage=False)
        self.assertEqual(d3["attention"], [])
        self.assertIn("nothing needs attention", checkin.render(d3, quiet=True))


class TaskTests(Home):
    def setUp(self):
        super().setUp()
        self.proj = Path(self._tmp.name) / "proj"
        self.proj.mkdir()
        (self.proj / "coordinator.json").write_text("{}")
        self.cfg = Config.load(self.proj / "coordinator.json")

    def test_done_needs_a_passing_check_or_valid_evidence(self):
        t1 = tasks.add(self.cfg, "build", check=f'"{PY}" -c "import sys; sys.exit(1)"')
        t2 = tasks.add(self.cfg, "ship", after=[t1["id"]])
        with self.assertRaises(tasks.TaskError):  # dependency open
            tasks.claim(self.cfg, t2["id"], "beta")
        tasks.claim(self.cfg, t1["id"], "alpha")
        with self.assertRaises(tasks.TaskError):  # another lane holds it
            tasks.claim(self.cfg, t1["id"], "beta")
        with self.assertRaisesRegex(tasks.TaskError, "check failed"):
            tasks.done(self.cfg, t1["id"])
        data = json.loads(tasks.path(self.cfg).read_text())
        data["tasks"][0]["check"] = f'"{PY}" -c "print(42)"'
        tasks.path(self.cfg).write_text(json.dumps(data))
        done = tasks.done(self.cfg, t1["id"])
        self.assertEqual((done["status"], done["check_output"]), ("done", ["42"]))
        with self.assertRaisesRegex(tasks.TaskError, "needs --evidence"):
            tasks.done(self.cfg, t2["id"])
        jobs.launch("bad", [PY, "-c", "import sys; sys.exit(1)"], root=self.home, lock="none")
        wait.wait([jobs.resolve("bad", root=self.home)], 30, 0.1)
        with self.assertRaisesRegex(tasks.TaskError, "not a job with COMPLETE=1"):
            tasks.done(self.cfg, t2["id"], "job:bad", root=self.home)
        jobs.launch("good", [PY, "-c", "pass"], root=self.home, lock="none")
        wait.wait([jobs.resolve("good", root=self.home)], 30, 0.1)
        self.assertEqual(tasks.done(self.cfg, t2["id"], "job:good", root=self.home)["status"], "done")
        tasks.reopen(self.cfg, t2["id"], "regressed")
        self.assertEqual(tasks.summary(self.cfg)["ready"][0]["id"], t2["id"])


class HeartbeatDetailTests(Home):
    def setUp(self):
        super().setUp()
        self.proj = Path(self._tmp.name) / "proj"
        self.proj.mkdir()
        (self.proj / "TODO.md").write_text("status")
        (self.proj / "coordinator.json").write_text(json.dumps({
            "heartbeat": {"silent_lane_minutes": 1, "fresh_start_hours": 1},
            "usage_commands": [[PY, "-c", "print('5h 93% used | week 40% used')"]]}))
        self.cfg = Config.load(self.proj / "coordinator.json")

    def age_lane(self, lane, seconds, started=0):
        f = board.board_dir(self.home) / f"{lane}.json"
        row = json.loads(f.read_text())
        row["updated"] -= seconds
        row["started"] -= started
        f.write_text(json.dumps(row))

    def test_failures_persist_until_acked_and_busy_lanes_are_not_quiet(self):
        jobs.launch("broke", [PY, "-c", "import sys; sys.exit(2)"], root=self.home, lock="none")
        wait.wait([jobs.resolve("broke", root=self.home)], 30, 0.1)
        jobs.launch("long", [PY, "-c", "import time; time.sleep(60)"], root=self.home, lock="none")
        board.update("busy", {"job": "long"}, root=self.home)
        board.update("idle", {}, root=self.home)
        self.age_lane("busy", 600)
        self.age_lane("idle", 600, started=7200)
        first = "\n".join(checkin.collect(self.cfg, self.home)["attention"])
        self.assertIn("usage at 93%", first)
        self.assertIn("job broke failed", first)
        self.assertIn("lane idle quiet", first)
        self.assertIn("lane idle running for", first)
        self.assertNotIn("lane busy quiet", first)
        second = "\n".join(checkin.collect(self.cfg, self.home, run_usage=False)["attention"])
        self.assertIn("job broke failed", second)
        jobs.ack(jobs.resolve("broke", root=self.home), "fixed the import")
        third = "\n".join(checkin.collect(self.cfg, self.home, run_usage=False)["attention"])
        self.assertNotIn("broke", third)


if __name__ == "__main__":
    unittest.main()
