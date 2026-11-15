"""Benchmark safety and metrics use fixtures; no real media or production calls."""

from itertools import product
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.ytbot import flow_benchmark as bench


class BenchmarkSafety(unittest.TestCase):
    def test_active_or_unknown_manager_denies_heavy_work(self):
        for response in (subprocess.CompletedProcess([], 1, stdout=""),
                         subprocess.CompletedProcess([], 0, stdout="youtubebot-fixture.service loaded active running description")):
            with patch.object(bench, "PAUSE_PERMIT", None), patch.object(bench.subprocess, "run", return_value=response):
                with self.assertRaises(bench.ProductionBusy):
                    bench.assert_idle(Path("/fixture"))

    def test_owner_pause_permit_expires_and_resumption_stops_benchmarks(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "partial.mp4"
            partial.write_bytes(b"owner's unfinished file")
            permit = {"operation_id": "fixture", "pid": 123, "process_identity": "identity",
                      "partial_video": str(partial), "partial_size": partial.stat().st_size,
                      "deadline_unix": time.time() + 60}
            with patch.object(bench, "PAUSE_PERMIT", permit), patch.object(bench, "process_stat", return_value={"state": "R", "identity": "identity"}):
                with self.assertRaises(bench.ProductionBusy):
                    bench.paused_operation()
            with patch.object(bench, "PAUSE_PERMIT", {**permit, "deadline_unix": 0}):
                with self.assertRaises(bench.ProductionBusy):
                    bench.paused_operation()
            self.assertEqual(partial.read_bytes(), b"owner's unfinished file")

    def test_private_root_and_input_symlink_cannot_target_production(self):
        with tempfile.TemporaryDirectory() as directory:
            production = Path(directory) / "production"
            production.mkdir()
            with self.assertRaises(ValueError):
                bench.private_root(production / "work", production)
            root = Path(directory) / "benchmark"
            (root / "inputs/input-1").mkdir(parents=True)
            original = production / "narration.aac"
            original.write_bytes(b"private original")
            (root / "inputs/input-1/narration.aac").symlink_to(original)
            with self.assertRaises(ValueError):
                bench.input_audio(root, 1)

    def test_snapshot_excludes_operation_records_uploads_and_partial_video(self):
        with tempfile.TemporaryDirectory() as directory:
            production, root = Path(directory) / "production", Path(directory) / "benchmark"
            for slug in bench.INPUTS:
                source = production / ".local/ytbot/runs" / slug
                source.mkdir(parents=True)
                for name in ("article.txt", "narration.aac", "record.json", "upload.json", "video.mp4", "owner.lock"):
                    (source / name).write_bytes(name.encode())
            with patch.object(bench.subprocess, "check_output", return_value="synthetic-revision\n"):
                bench.snapshot(root, production)
            for index in (1, 2):
                names = {path.name for path in (root / "inputs" / f"input-{index}").iterdir()}
                self.assertEqual(names, {"article.txt", "narration.aac"})
                self.assertEqual(stat.S_IMODE((root / "inputs" / f"input-{index}/article.txt").stat().st_mode), 0o600)


class BenchmarkMetrics(unittest.TestCase):
    def test_word_and_character_edit_distance_matches_exact_dynamic_programming(self):
        def distance(a, b):
            previous = list(range(len(b) + 1))
            for index, item in enumerate(a, 1):
                current = [index]
                for position, other in enumerate(b, 1):
                    current.append(min(current[-1] + 1, previous[position] + 1,
                                       previous[position - 1] + (item != other)))
                previous = current
            return previous[-1]
        strings = ["".join(items) for n in range(4) for items in product("ab", repeat=n)]
        for left, right in product(strings, repeat=2):
            self.assertEqual(bench.edit_distance(left, right), distance(left, right), (left, right))
        self.assertEqual(bench.error_rates("A calm mind.", "a calm mind"), {"wer": 0, "cer": 0})

    def test_timing_or_interpolated_timestamps_alone_cannot_approve_quality(self):
        segments = [{"start": 0, "end": 2, "text": "A calm mind."}]
        quality = bench.compare_asr("A calm mind.", segments, segments)
        self.assertEqual(quality["wer_delta_pp"], 0)
        self.assertEqual(quality["median_interpolated_token_deviation_seconds"], 0)
        self.assertFalse(quality["approved"])
        self.assertEqual(quality["missing_or_duplicated_blocks_review"], "pending")

    def test_missing_trials_do_not_create_speed_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            result = bench.summarize(Path(directory))
            self.assertEqual(result["timings"], [])
            self.assertFalse(result["approved"])
