"""Bounded cross-channel distribution and shared generation slots behave as contracted."""
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.ytbot import channels, config, distribute
from tools.ytbot.accounts_store import AccountStore


class GenerationSlotsTests(unittest.TestCase):
    def setUp(self):
        self.store = AccountStore()
        for index in range(4):
            path = self.store.root / "locks" / f"generation-slot-{index}.lock"
            if path.exists():
                path.unlink()

    def test_two_batches_share_the_generation_browser_and_a_third_queues(self):
        both = threading.Barrier(2, timeout=30)
        release = threading.Event()
        acquired = []

        def first_two():
            with self.store.generation_slots() as slot:
                acquired.append(slot)
                both.wait()            # proves both slots are held at once
                release.wait(timeout=30)

        threads = [threading.Thread(target=first_two) for _ in range(2)]
        for thread in threads:
            thread.start()
        deadline = time.time() + 30
        while len(acquired) < 2 and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(sorted(acquired), [0, 1])   # both slots held at once

        third = []
        def queued():
            with self.store.generation_slots() as slot:
                third.append(slot)

        waiter = threading.Thread(target=queued)
        waiter.start()
        time.sleep(1.0)
        self.assertFalse(third)          # every slot busy: the third batch waits
        release.set()
        for thread in threads:
            thread.join(timeout=30)
        waiter.join(timeout=30)
        self.assertEqual(third, [0])     # queued on slot 0 like the old exclusive lock

    def test_slot_count_env_is_bounded_to_one(self):
        with patch.dict("os.environ", {"YTBOT_GENERATION_SLOTS": "1"}):
            with self.store.generation_slots() as first:
                self.assertEqual(first, 0)
            # the slot is released, so a second acquisition works
            with self.store.generation_slots() as second:
                self.assertEqual(second, 0)


class DistributionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        channels.apply("fallem-prince")

    def test_two_channels_run_at_the_same_time(self):
        together = threading.Barrier(2, timeout=60)

        def fake_run(command, cwd=None, stdout=None, stderr=None):
            together.wait()              # only passes when both channels are running
            return unittest.mock.Mock(returncode=0)

        plan = {"whispers-from-heaven": 1, "vocal-pages": 1}
        with patch.object(distribute, "audit", return_value={}), \
             patch.object(distribute, "audit_dates", return_value={}), \
             patch.object(distribute, "allocate_by_date", return_value=plan), \
             patch.object(distribute.subprocess, "run", side_effect=fake_run), \
             patch.object(distribute.time, "sleep", lambda seconds: None), \
             patch.object(distribute.config, "DATA", Path(self.tmp.name)), \
             patch("tools.ytbot.comments.answer_all"):
            failures = distribute.run_distribution(2, concurrency=2)
        self.assertEqual(failures, [])    # no deadlock == real cross-channel overlap

    def test_sequential_concurrency_keeps_one_channel_at_a_time(self):
        active = []
        peak = []
        def fake_run(command, cwd=None, stdout=None, stderr=None):
            active.append(1)
            peak.append(len(active))
            time.sleep(0.2)
            active.pop()
            return unittest.mock.Mock(returncode=0)

        plan = {"whispers-from-heaven": 1, "vocal-pages": 1}
        with patch.object(distribute, "audit", return_value={}), \
             patch.object(distribute, "audit_dates", return_value={}), \
             patch.object(distribute, "allocate_by_date", return_value=plan), \
             patch.object(distribute.subprocess, "run", side_effect=fake_run), \
             patch.object(distribute.config, "DATA", Path(self.tmp.name)), \
             patch("tools.ytbot.comments.answer_all"):
            distribute.run_distribution(2, concurrency=1)
        self.assertEqual(max(peak), 1)

    def test_a_failed_channel_is_reported(self):
        def fake_run(command, cwd=None, stdout=None, stderr=None):
            return unittest.mock.Mock(returncode=1)

        plan = {"whispers-from-heaven": 2}
        with patch.object(distribute, "audit", return_value={}), \
             patch.object(distribute, "audit_dates", return_value={}), \
             patch.object(distribute, "allocate_by_date", return_value=plan), \
             patch.object(distribute.subprocess, "run", side_effect=fake_run), \
             patch.object(distribute.config, "DATA", Path(self.tmp.name)), \
             patch("tools.ytbot.comments.answer_all"):
            failures = distribute.run_distribution(2, concurrency=2)
        self.assertEqual(failures, [("whispers-from-heaven", 1)])


if __name__ == "__main__":
    unittest.main()


class DateBasedAllocationTests(unittest.TestCase):
    def test_queue_that_ends_first_receives_the_next_videos(self):
        dates = {
            "reflection": datetime(2026, 12, 4, 21, 0),
            "whispers-from-heaven": datetime(2026, 12, 4, 22, 0),
            "bathylora": datetime(2026, 12, 9, 21, 0),
            "sepia-atlas": datetime(2026, 12, 10, 21, 0),
        }
        plan = distribute.allocate_by_date(10, dates)
        self.assertEqual(plan["reflection"] + plan["whispers-from-heaven"], 10)
        self.assertEqual(plan["bathylora"], 0)
        self.assertEqual(plan["sepia-atlas"], 0)

    def test_empty_queue_goes_before_any_scheduled_channel(self):
        dates = {"reflection": None, "whispers-from-heaven": datetime(2026, 12, 4, 22, 0)}
        plan = distribute.allocate_by_date(1, dates)
        self.assertEqual(plan, {"reflection": 1, "whispers-from-heaven": 0})
