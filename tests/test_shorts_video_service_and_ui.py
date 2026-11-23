"""Service adapter and PySide6 desktop panel contracts for Shorts AI video."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from src.ui.main_window import VideoGeneratorApp
from src.ui.shorts_video_panel import ShortsVideoPanel
from tools.ytbot import channels, config, service, service_jobs
from tools.ytbot.accounts_store import AccountStore, read_private, write_private
from tools.ytbot.shorts_video import credits, settings
from tools.ytbot.shorts_video.models import GENERATION_STATES, SceneSpec, Storyboard
from tools.ytbot.shorts_video.storyboard import save_storyboard


class ShortsServiceContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(config, "ROOT", self.root)
        self.data_patch = patch.object(config, "DATA", self.root / ".local/ytbot")
        self.root_patch.start()
        self.data_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(lambda: channels.apply("fallem-prince"))
        self.store = AccountStore()
        self.store.create("work", "Work")

    def test_capabilities_and_providers_never_expose_secrets_or_paths(self):
        caps = service.dispatch(service.parser().parse_args(["capabilities"]))
        for cap in (
            "youtube.batch.submit",
            "youtube.batch.generate",
            "youtube.shorts.providers",
            "youtube.shorts.estimate",
            "youtube.shorts.generate",
            "youtube.shorts.resume",
            "youtube.shorts.inspect",
        ):
            self.assertIn(cap, caps["capabilities"])

        providers = service.dispatch(service.parser().parse_args(["shorts-providers"]))
        serialized = json.dumps(providers)
        self.assertNotIn(str(self.root), serialized)
        self.assertFalse(providers["providers"]["gemini-api"]["available"])
        self.assertIn("credits", providers)

    def test_shorts_estimate_respects_documentary_guard_and_spends_zero_credits(self):
        est = service.dispatch(
            service.parser().parse_args([
                "shorts-estimate",
                "--channel",
                "zaflas",
                "--count",
                "2",
                "--visual-mode",
                "ai-video",
                "--video-provider",
                "google-flow",
            ])
        )
        self.assertEqual(est["channel"], "zaflas")
        self.assertGreater(est["estimated_total_credits"], 0.0)
        self.assertEqual(credits.ledger_summary()["total_credits_used"], 0.0)

        with self.assertRaises(ValueError):
            service.dispatch(
                service.parser().parse_args([
                    "shorts-estimate",
                    "--channel",
                    "sepia-atlas",
                    "--count",
                    "1",
                    "--visual-mode",
                    "ai-video",
                ])
            )

    def test_shorts_generate_and_resume_are_bounded_and_never_upload(self):
        op_id = str(uuid.uuid4())
        args = service.parser().parse_args([
            "shorts-generate",
            "--operation-id",
            op_id,
            "--channel",
            "zaflas",
            "--count",
            "1",
            "--approved-generation",
            "--visual-mode",
            "ai-video",
        ])
        with (
            patch.object(service_jobs, "launch_actor"),
            patch.object(service_jobs, "unit_active", return_value=False),
        ):
            submitted = service.dispatch(args)
        self.assertEqual(submitted["mode"], "shorts_generate")
        self.assertEqual(submitted["state"], "accepted")
        stored = read_private(service_jobs.jobs_root() / f"{op_id}.json")
        self.assertFalse(stored["request"]["approved_schedule"])
        self.assertTrue(stored["request"]["approved_generate"])

        # Inspect & resume on a synthetic run directory.
        run_dir = self.root / ".local/ytbot/channels/zaflas/shorts/solo-teste"
        run_dir.mkdir(parents=True)
        sb = Storyboard(
            channel="zaflas",
            topic="Solo teste",
            language="pt-BR",
            scenes=[
                SceneSpec(
                    scene_id="scene_01",
                    scene_index=1,
                    script_section="Solo.",
                    start_sec=0.0,
                    end_sec=5.0,
                    duration_sec=5.0,
                    visual_description="Solo",
                    generation_prompt="Solo",
                    status="failed",
                    error=f"failed reading {self.root}/secret/path.mp4",
                )
            ],
        )
        save_storyboard(run_dir, sb)
        inspected = service.dispatch(
            service.parser().parse_args([
                "shorts-inspect",
                "--channel",
                "zaflas",
                "--run-id",
                "solo-teste",
            ])
        )
        self.assertTrue(inspected["exists"])
        self.assertEqual(len(inspected["failed_scenes"]), 1)
        self.assertNotIn(str(self.root), json.dumps(inspected))

        # Mark the prior accepted job completed so host capacity is released for resume.
        stored["state"] = "completed"
        write_private(service_jobs.jobs_root() / f"{op_id}.json", stored)

        import subprocess

        resume_op = str(uuid.uuid4())
        with (
            patch.object(service_jobs, "process_identity", return_value=None),
            patch.object(
                service_jobs.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout="LoadState=not-found\nActiveState=inactive\n"),
            ),
            patch.object(service_jobs, "launch_actor"),
        ):
            resumed = service.dispatch(
                service.parser().parse_args([
                    "shorts-resume",
                    "--operation-id",
                    resume_op,
                    "--channel",
                    "zaflas",
                    "--run-id",
                    "solo-teste",
                    "--approved-generation",
                ])
            )
        self.assertEqual(resumed["mode"], "shorts_resume")

    def test_shorts_resume_actor_execution_never_calls_youtube_upload(self):
        from tools.ytbot.shorts_video import service_api as shorts_service

        run_dir = self.root / ".local/ytbot/channels/zaflas/shorts/solo-resume"
        run_dir.mkdir(parents=True)
        (run_dir / "topic.txt").write_text("Solo resume", encoding="utf-8")
        (run_dir / "short.txt").write_text("Texto de teste em português.", encoding="utf-8")
        (run_dir / "narration.aac").write_bytes(b"SYNTHETIC_AUDIO")

        op_id = str(uuid.uuid4())
        with (
            patch.object(service_jobs, "launch_actor"),
            patch.object(service_jobs, "unit_active", return_value=False),
        ):
            service.dispatch(
                service.parser().parse_args([
                    "shorts-resume",
                    "--operation-id",
                    op_id,
                    "--channel",
                    "zaflas",
                    "--run-id",
                    "solo-resume",
                    "--approved-generation",
                ])
            )

        def fake_resume(_channel, _run_id, _opts):
            (run_dir / "video.mp4").write_bytes(b"SYNTHETIC_SHORT_MP4")
            return {
                "id": "solo-resume",
                "title": "Solo resume #Shorts",
                "topic": "Solo resume",
                "state": "ready",
                "slot": "",
                "video_id": "",
                "artifacts": ["video.mp4"],
            }

        with (
            patch.object(shorts_service, "resume_short_run", side_effect=fake_resume),
            patch("tools.ytbot.youtube.upload_and_schedule_with_context") as upload,
        ):
            service_jobs.execute(op_id)
        upload.assert_not_called()
        status = service_jobs.status(op_id)
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["result"]["generated_count"], 1)
        self.assertEqual(status["result"]["scheduled_count"], 0)


class ShortsDesktopPanelContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(config, "ROOT", self.root)
        self.data_patch = patch.object(config, "DATA", self.root / ".local/ytbot")
        self.root_patch.start()
        self.data_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.data_patch.stop)

    def test_main_window_embeds_shorts_panel_without_breaking_existing_modes(self):
        window = VideoGeneratorApp()
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.mode_combo.currentIndex(), 0)
        self.assertIsInstance(window.shorts_video_panel, ShortsVideoPanel)
        panel = window.shorts_video_panel

        panel.enable_cb.setChecked(True)
        panel.max_credits_short_spin.setValue(60.0)
        panel.max_scenes_spin.setValue(4)
        saved = settings.load_settings()
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["visual_mode"], "ai-video")
        self.assertEqual(saved["max_credits_per_short"], 60.0)
        self.assertEqual(saved["max_scenes_per_short"], 4)

        for state in GENERATION_STATES:
            panel.set_generation_state(state)
            self.assertEqual(panel.state_label.text(), state)
        window.close()

    def test_non_blocking_short_worker_updates_clips_table(self):
        panel = ShortsVideoPanel()
        self.addCleanup(panel.deleteLater)
        run_dir = self.root / "ui-short"
        run_dir.mkdir()
        sb = Storyboard(
            channel="zaflas",
            topic="Campo",
            language="pt-BR",
            scenes=[
                SceneSpec(
                    scene_id="scene_01",
                    scene_index=1,
                    script_section="Campo.",
                    start_sec=0.0,
                    end_sec=6.0,
                    duration_sec=6.0,
                    visual_description="Campo",
                    generation_prompt="Campo",
                    status="validated",
                    output_path=str(run_dir / "clips/scene_01.mp4"),
                )
            ],
        )
        save_storyboard(run_dir, sb)

        with patch(
            "src.ui.shorts_video_panel.render_ai_short",
            return_value={"status": "dry_run", "visual_mode": "ai-video"},
        ):
            panel.start_short_job(
                run_dir=run_dir,
                channel_slug="zaflas",
                topic="Campo",
                script_text="Campo verde.",
                dry_run=True,
            )
            self.assertIsNotNone(panel._worker)
            panel._worker.wait(5000)
            self.app.processEvents()
        self.assertEqual(panel.clips_table.rowCount(), 1)
        self.assertEqual(panel.clips_table.item(0, 0).text(), "scene_01")
