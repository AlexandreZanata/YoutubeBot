"""Bounded upload concurrency and bounded render concurrency behave as contracted."""
import os
import threading
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from tools.ytbot import batch, channels, render


class UploadPhaseTests(TestCase):
    def test_sequential_upload_runs_every_job_in_slot_order(self):
        calls = []
        def fake_upload(_context, topic, slot):
            calls.append((topic, slot))
        jobs = [("topic-a", 10), ("topic-b", 21), ("topic-c", 10)]
        with patch.object(batch.pipeline, "upload_stage", side_effect=fake_upload):
            batch._upload_phase(Mock(), None, jobs, 1)
        self.assertEqual(calls, jobs)

    def test_upload_failure_is_recorded_and_the_queue_continues(self):
        def fake_upload(_context, topic, slot):
            if topic == "broken":
                raise RuntimeError("studio timeout")
        jobs = [("broken", 10), ("healthy", 21)]
        with patch.object(batch.pipeline, "upload_stage", side_effect=fake_upload), \
             patch.object(batch.logic, "record_event") as record:
            failures = batch._upload_phase(Mock(), None, jobs, 1)
        self.assertEqual(failures, [("broken", "studio timeout")])
        self.assertEqual(record.call_count, 1)
        self.assertIn("upload", str(record.call_args))

    def test_two_upload_tabs_overlap_the_studio_wait_with_own_connections(self):
        inside = threading.Barrier(2, timeout=30)
        def fake_upload(_context, topic, slot):
            inside.wait()          # only passes when a second worker is inside
        playwright = MagicMock()   # each worker opens its own CDP connection
        playwright.__enter__.return_value = playwright
        jobs = [("topic-a", 10), ("topic-b", 21)]
        with patch.object(batch, "sync_playwright", return_value=playwright), \
             patch.object(batch.pipeline, "upload_stage", side_effect=fake_upload):
            batch._upload_phase(Mock(), 9301, jobs, 2)   # no deadlock == real overlap
        playwright.chromium.connect_over_cdp.assert_called_with(
            "http://127.0.0.1:9301", timeout=60000)

    def test_empty_queue_does_nothing(self):
        with patch.object(batch.pipeline, "upload_stage") as upload:
            batch._upload_phase(Mock(), None, [], 2)
        upload.assert_not_called()


class BatchDefaultsTests(TestCase):
    def setUp(self):
        channels.apply("fallem-prince")

    def test_default_parallel_is_one_tab_per_video(self):
        topics = ["topic-x", "topic-y", "topic-z"]
        with patch.object(batch.runtime, "setup_profile"), \
             patch.object(batch.runtime, "start_hidden_chrome"), \
             patch.object(batch, "sync_playwright"), \
             patch.object(batch.runtime, "connect_hidden", return_value=(Mock(), Mock())), \
             patch.object(batch.runtime, "configure_downloads"), \
             patch.object(batch.runtime, "configure_extension"), \
             patch.object(batch.account, "ensure_channel"), \
             patch.object(batch, "_refresh_catalog"), \
             patch.object(batch.catalog, "fetch_creator_videos", return_value={}), \
             patch.object(batch, "_local_state", return_value=(set(), [])), \
             patch.object(batch, "prepare_topics", return_value=topics), \
             patch.object(batch, "_asset_phase", return_value=[]) as assets, \
             patch.object(batch, "_upload_phase", return_value=[]) as uploads, \
             patch.object(batch.community, "ensure_post"), \
             patch.object(batch.logic, "write_records_markdown"), \
             patch.object(batch, "_summary"):
            batch.run_batch(3)
        # documented shape: 0 means one asset tab per video
        self.assertEqual(assets.call_args.args[2], 3)
        # upload pool receives the upload cdp so each worker connects itself
        self.assertIsNone(uploads.call_args.args[1])
        self.assertEqual(uploads.call_args.args[3], 2)


class RenderJobsTests(TestCase):
    def test_render_jobs_default_is_two_and_env_overrides(self):
        os.environ.pop("YTBOT_RENDER_JOBS", None)
        self.assertEqual(render._render_jobs(), 2)
        os.environ["YTBOT_RENDER_JOBS"] = "3"
        try:
            self.assertEqual(render._render_jobs(), 3)
        finally:
            del os.environ["YTBOT_RENDER_JOBS"]
        self.assertEqual(render._render_jobs(), 2)

    def test_invalid_or_zero_render_jobs_stay_bounded(self):
        for value in ("nope", "0", "-4"):
            os.environ["YTBOT_RENDER_JOBS"] = value
            try:
                self.assertGreaterEqual(render._render_jobs(), 1)
            finally:
                del os.environ["YTBOT_RENDER_JOBS"]

    def test_two_renders_enter_the_semaphore_concurrently(self):
        jobs = threading.Semaphore(2)
        both = threading.Barrier(2, timeout=30)
        def worker():
            with jobs:
                both.wait()
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads))


if __name__ == "__main__":
    import unittest
    unittest.main()
