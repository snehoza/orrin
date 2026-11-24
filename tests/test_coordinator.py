import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from coordinator_kit import board, cli, data, jobs, lock, procs, tidy, wait

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
        target = Path(self._tmp.name) / "agents"
        self.assertEqual(cli.main(["init", str(target)]), 0)
        for rel in cli.TEMPLATES:
            self.assertTrue((target / rel).is_file(), rel)
        (target / "AGENT_RULES.md").write_text("mine")
        cli.main(["init", str(target)])
        self.assertEqual((target / "AGENT_RULES.md").read_text(), "mine")
        json.loads((target / "protected_data.json").read_text())


if __name__ == "__main__":
    unittest.main()
