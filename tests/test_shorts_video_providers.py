"""Hermetic tests for Shorts-only AI video scope, providers, credits and resumability."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.ytbot import batch, channels, config, faith_shorts, pipeline, shorts
from tools.ytbot.shorts_video import (
    ChannelPolicyError,
    CreditBudgetExceededError,
    ProviderAuthRequiredError,
    ProviderUnavailableError,
    ShortsOnlyViolationError,
    assert_channel_policy,
    assert_shorts_scope,
    assert_video_scope,
    credits,
    flow_browser,
    settings,
)
from tools.ytbot.shorts_video.models import ClipValidationResult
from tools.ytbot.shorts_video.pipeline import render_ai_short
from tools.ytbot.shorts_video.providers import (
    GeminiVideoAPIProvider,
    GoogleFlowProvider,
    ManualVideoImportProvider,
    VideoGenerationProvider,
    get_provider,
)
from tools.ytbot.shorts_video.storyboard import plan_short_storyboard, save_storyboard


class FakeValidProvider(VideoGenerationProvider):
    name = "google-flow"

    def __init__(self, *, fail_scenes=None, timeout_scenes=None, auth_fail_at=None, credit_cost=10.0):
        self.fail_scenes = set(fail_scenes or ())
        self.timeout_scenes = set(timeout_scenes or ())
        self.auth_fail_at = auth_fail_at
        self.credit_cost = credit_cost
        self.calls = []
        self.reconcile_calls = []

    def check_availability(self, active_settings):
        return {"provider": self.name, "available": True, "paid_api": False, "state": "ready"}

    def reconcile_scene(self, scene, run_dir, active_settings):
        self.reconcile_calls.append(scene.scene_id)
        if scene.scene_id in self.timeout_scenes:
            clip = run_dir / "clips" / f"{scene.scene_id}.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"SYNTHETIC_MP4_" * 60)
            return clip
        return super().reconcile_scene(scene, run_dir, active_settings)

    def generate_scene(self, scene, run_dir, active_settings):
        self.calls.append(scene.scene_id)
        if self.auth_fail_at == scene.scene_id:
            raise ProviderAuthRequiredError("Google Flow session expired")
        if scene.scene_id in self.timeout_scenes:
            raise TimeoutError("Flow generation timed out")
        if scene.scene_id in self.fail_scenes:
            raise ProviderUnavailableError("Scene generation failed")
        clip = run_dir / "clips" / f"{scene.scene_id}.mp4"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"SYNTHETIC_MP4_" * 60)
        return clip, self.credit_cost


def _ok_validation(path, **_kwargs):
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 512:
        return ClipValidationResult(valid=False, path=str(p), reason="missing")
    return ClipValidationResult(
        valid=True,
        path=str(p),
        width=1080,
        height=1920,
        duration_sec=6.0,
        fps=30.0,
        has_video=True,
        codec="h264",
        file_size=p.stat().st_size,
        reason="ok",
    )


class ShortsOnlyScopeAndPolicyTests(unittest.TestCase):
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

    def test_scope_guard_blocks_long_form_and_landscape_dimensions(self):
        for ctx in ("long", "long-form", "run", "batch", "distribute", "documentary", "generate"):
            with self.subTest(ctx=ctx), self.assertRaises(ShortsOnlyViolationError):
                assert_shorts_scope(ctx, visual_mode="ai-video")
        with self.assertRaises(ShortsOnlyViolationError):
            assert_shorts_scope("shorts", width=1920, height=1080, visual_mode="ai-video")
        assert_shorts_scope("shorts", width=1080, height=1920, visual_mode="ai-video")

    def test_long_video_scope_accepts_landscape_movie_only(self):
        assert_video_scope("long-video", width=1920, height=1080, visual_mode="ai-video")
        assert_video_scope("movie", width=1920, height=1080, visual_mode="ai-video")
        with self.assertRaises(ShortsOnlyViolationError):
            assert_video_scope("long-video", width=1080, height=1920, visual_mode="ai-video")
        with self.assertRaises(ShortsOnlyViolationError):
            assert_video_scope("movie", width=1920, height=1080, visual_mode="hologram")

    def test_movie_storyboard_plans_horizontal_scenes(self):
        from tools.ytbot.shorts_video.storyboard import plan_movie_storyboard

        storyboard = plan_movie_storyboard(
            "infinite-random-worlds",
            "The City That Sold Its Shadows",
            "A girl follows a stolen shadow through a drowned city.",
            total_duration_sec=32.0,
            settings={**settings.load_settings(), "max_scenes_per_short": 4},
        )
        self.assertEqual(storyboard.scope, "long-video")
        self.assertEqual(storyboard.aspect_ratio, "16:9")
        self.assertLessEqual(len(storyboard.scenes), 4)
        self.assertIn("1920x1080", storyboard.scenes[0].generation_prompt)
        self.assertNotIn("9:16", storyboard.scenes[0].generation_prompt)

    def test_long_form_batch_and_pipeline_refuse_ai_video_mode(self):
        with self.assertRaises(ShortsOnlyViolationError):
            batch.run_batch(1, visual_mode="ai-video")
        with self.assertRaises(ShortsOnlyViolationError):
            pipeline.asset_stage(object(), "Topic", visual_mode="ai-video")

    def test_documentary_channels_disable_ai_video_by_default(self):
        for slug in ("sepia-atlas", "bathylora"):
            with self.subTest(slug=slug):
                with self.assertRaises(ChannelPolicyError):
                    assert_channel_policy(slug, {"allow_documentary_illustrative": False})
                assert_channel_policy(slug, {"allow_documentary_illustrative": True})


class ProviderAndFlowReadinessTests(unittest.TestCase):
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

    def test_provider_selection_and_paid_api_disabled_by_default(self):
        self.assertIsInstance(get_provider("google-flow"), GoogleFlowProvider)
        self.assertIsInstance(get_provider("gemini-api"), GeminiVideoAPIProvider)
        self.assertIsInstance(get_provider("manual-import"), ManualVideoImportProvider)
        with self.assertRaises(ValueError):
            get_provider("unknown-provider")

        api = GeminiVideoAPIProvider()
        avail = api.check_availability(settings.load_settings())
        self.assertFalse(avail["available"])
        self.assertEqual(avail["state"], "disabled")
        self.assertTrue(api.is_paid_api())

    def test_flow_profile_isolation_and_readiness_inspection(self):
        self.assertNotEqual(flow_browser.FLOW_CDP_PORT, config.CDP_PORT)
        self.assertNotIn(flow_browser.FLOW_CDP_PORT, range(9301, 9321))

        page = Mock()
        page.url = "https://accounts.google.com/v3/signin"
        self.assertEqual(flow_browser.inspect_flow_page(page)["state"], "login_required")

        page.url = "https://labs.google/fx/tools/flow"
        page.locator.return_value.first.is_visible.side_effect = [False, False, False, True]
        page.locator.return_value.inner_text.return_value = "Google Flow · 850 credits"
        result = flow_browser.inspect_flow_page(page)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["credits_reported"], 850.0)

        entry = flow_browser.record_flow_login_needed("Google Flow session expired")
        self.assertEqual(entry["state"], "login_required")
        marker = json.loads((config.DATA / "needs-login.json").read_text())
        self.assertIn("labs.google", marker["url"])
        self.assertNotIn("cookie", json.dumps(marker).lower())

    def test_manual_import_provider_stages_local_clips_at_zero_credits(self):
        run_dir = self.root / "run"
        clips = run_dir / "clips"
        clips.mkdir(parents=True)
        (clips / "scene_01.mp4").write_bytes(b"SYNTHETIC_MP4_" * 60)

        storyboard = plan_short_storyboard("zaflas", "Solo e raiz", "O solo precisa de cuidado.")
        with patch("tools.ytbot.shorts_video.providers.validate_clip", side_effect=_ok_validation):
            provider = ManualVideoImportProvider()
            path, charged = provider.generate_scene(storyboard.scenes[0], run_dir, {"channel": "zaflas"})
        self.assertEqual(charged, 0.0)
        self.assertTrue(path.is_file())


class StoryboardCreditsAndResumablePipelineTests(unittest.TestCase):
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

    def test_channel_specific_storyboards_preserve_identity_and_language(self):
        zaflas_sb = plan_short_storyboard(
            "zaflas",
            "Compactação do solo",
            "Quando o trator passa no solo úmido, as raízes sofrem. Veja como corrigir no campo.",
            total_duration_sec=36.0,
        )
        self.assertEqual(zaflas_sb.language, "pt-BR")
        self.assertEqual(zaflas_sb.aspect_ratio, "9:16")
        self.assertGreaterEqual(len(zaflas_sb.scenes), 3)
        self.assertIn("Brazilian", zaflas_sb.scenes[0].generation_prompt)

        whispers_sb = plan_short_storyboard(
            "whispers-from-heaven",
            "A Quiet Dawn Prayer",
            "When night feels long, a quiet prayer rises before dawn. Hope returns gently.",
            total_duration_sec=40.0,
        )
        self.assertEqual(whispers_sb.language, "en")
        self.assertIn("Sacred Brown Engraving", whispers_sb.visual_identity)
        self.assertIn("no text", whispers_sb.scenes[0].generation_prompt.lower())

    def test_dry_run_estimates_without_spending_credits_or_calling_provider(self):
        run_dir = self.root / "short-run"
        run_dir.mkdir()
        provider = FakeValidProvider()
        summary = render_ai_short(
            run_dir,
            "whispers-from-heaven",
            "Hope at Dawn",
            "First sentence. Second sentence. Third sentence.",
            visual_mode="ai-video",
            video_provider="google-flow",
            video_model="veo-2-fast",
            max_scenes=3,
            dry_run=True,
            provider_instance=provider,
            narration_duration_sec=24.0,
        )
        self.assertEqual(summary["status"], "dry_run")
        self.assertEqual(summary["scene_count"], 3)
        self.assertEqual(summary["estimated_credits"], 30.0)
        self.assertEqual(provider.calls, [])
        self.assertEqual(credits.ledger_summary()["total_credits_used"], 0.0)
        self.assertTrue((run_dir / "storyboard.json").is_file())
        self.assertTrue((run_dir / "flow-prompts.md").is_file())

    def test_credit_budget_enforced_and_reconciles_resumed_scenes_without_double_charge(self):
        run_dir = self.root / "resume-run"
        run_dir.mkdir()
        (run_dir / "narration.aac").write_bytes(b"SYNTHETIC_AUDIO")
        (run_dir / "thumbnail.png").write_bytes(b"SYNTHETIC_PNG")

        # 3 scenes at 10 credits each, budget max_credits_per_short=20 -> 2 clips generated, 3rd skipped by budget.
        provider = FakeValidProvider(credit_cost=10.0)
        with (
            patch("src.engine.audio_mixer.get_audio_duration", return_value=24.0),
            patch("tools.ytbot.render.transcribe_narration", return_value=[{"start": 0.0, "end": 24.0, "text": "One two three."}]),
            patch("tools.ytbot.shorts_video.pipeline.validate_clip", side_effect=_ok_validation),
            patch("tools.ytbot.shorts_video.pipeline.assemble_short_video", return_value=run_dir / "video.mp4"),
        ):
            first = render_ai_short(
                run_dir,
                "midnight-tales",
                "Moonlit Harbor",
                "Sentence one. Sentence two. Sentence three.",
                visual_mode="ai-video",
                max_scenes=3,
                max_credits_per_short=20.0,
                fallback_to_static=True,
                provider_instance=provider,
                narration_duration_sec=24.0,
            )
            self.assertEqual(first["validated_scenes"], 2)
            self.assertTrue(first["budget_exhausted"])
            self.assertTrue(first["fallback_used"])
            self.assertEqual(first["credits_used"], 20.0)
            self.assertEqual(provider.calls, ["scene_01", "scene_02"])

            # Re-running with higher budget reuses scene_01 and scene_02 without re-calling provider for them!
            provider.calls.clear()
            second = render_ai_short(
                run_dir,
                "midnight-tales",
                "Moonlit Harbor",
                "Sentence one. Sentence two. Sentence three.",
                visual_mode="ai-video",
                max_scenes=3,
                max_credits_per_short=40.0,
                fallback_to_static=True,
                provider_instance=provider,
                narration_duration_sec=24.0,
            )
            self.assertEqual(second["validated_scenes"], 3)
            self.assertEqual(provider.calls, ["scene_03"])
            self.assertEqual(second["credits_used"], 30.0)

    def test_timeout_reconciles_before_retry_and_auth_error_pauses_job(self):
        run_dir = self.root / "timeout-run"
        run_dir.mkdir()
        (run_dir / "narration.aac").write_bytes(b"SYNTHETIC_AUDIO")
        provider = FakeValidProvider(timeout_scenes={"scene_01"})
        with (
            patch("src.engine.audio_mixer.get_audio_duration", return_value=15.0),
            patch("tools.ytbot.render.transcribe_narration", return_value=[{"start": 0.0, "end": 15.0, "text": "Hello."}]),
            patch("tools.ytbot.shorts_video.pipeline.validate_clip", side_effect=_ok_validation),
            patch("tools.ytbot.shorts_video.pipeline.assemble_short_video", return_value=run_dir / "video.mp4"),
        ):
            res = render_ai_short(
                run_dir,
                "vocal-pages",
                "Quiet Room",
                "A quiet room.",
                visual_mode="ai-video",
                max_scenes=1,
                provider_instance=provider,
                narration_duration_sec=15.0,
            )
        self.assertEqual(res["validated_scenes"], 1)
        self.assertEqual(provider.calls, ["scene_01"])
        self.assertEqual(provider.reconcile_calls, ["scene_01"])

        auth_run = self.root / "auth-run"
        auth_run.mkdir()
        (auth_run / "narration.aac").write_bytes(b"SYNTHETIC_AUDIO")
        auth_provider = FakeValidProvider(auth_fail_at="scene_01")
        with (
            patch("src.engine.audio_mixer.get_audio_duration", return_value=15.0),
            patch("tools.ytbot.render.transcribe_narration", return_value=[{"start": 0.0, "end": 15.0, "text": "Hello."}]),
            self.assertRaises(ProviderAuthRequiredError),
        ):
            render_ai_short(
                auth_run,
                "vocal-pages",
                "Quiet Room",
                "A quiet room.",
                visual_mode="ai-video",
                max_scenes=1,
                provider_instance=auth_provider,
                narration_duration_sec=15.0,
            )

    def test_all_failed_scenes_fallback_to_static_when_enabled(self):
        run_dir = self.root / "fallback-run"
        run_dir.mkdir()
        (run_dir / "narration.aac").write_bytes(b"SYNTHETIC_AUDIO")
        provider = FakeValidProvider(fail_scenes={"scene_01", "scene_02", "scene_03"})
        static_calls = []

        def fake_static(path):
            static_calls.append(path)
            out = path / "video.mp4"
            out.write_bytes(b"STATIC_MP4")
            return out

        with (
            patch("src.engine.audio_mixer.get_audio_duration", return_value=24.0),
            patch("tools.ytbot.render.transcribe_narration", return_value=[{"start": 0.0, "end": 24.0, "text": "Text."}]),
        ):
            res = render_ai_short(
                run_dir,
                "fallem-prince",
                "Shadow King",
                "One. Two. Three.",
                visual_mode="ai-video",
                max_scenes=3,
                max_retries=0,
                fallback_to_static=True,
                provider_instance=provider,
                static_fallback_fn=fake_static,
                narration_duration_sec=24.0,
            )
        self.assertTrue(res["fallback_used"])
        self.assertEqual(res["visual_mode"], "static")
        self.assertEqual(static_calls, [run_dir])

    def test_cli_shorts_dry_run_accepts_new_flags_without_breaking_legacy(self):
        from tools.ytbot.cli import build_parser

        parser = build_parser()
        legacy = parser.parse_args(["shorts", "--channel", "zaflas", "--count", "1"])
        self.assertIsNone(legacy.visual_mode)
        self.assertFalse(legacy.dry_run)

        ai_args = parser.parse_args([
            "shorts",
            "--channel",
            "zaflas",
            "--count",
            "1",
            "--visual-mode",
            "ai-video",
            "--video-provider",
            "google-flow",
            "--dry-run",
        ])
        self.assertEqual(ai_args.visual_mode, "ai-video")
        self.assertEqual(ai_args.video_provider, "google-flow")
        self.assertTrue(ai_args.dry_run)
        result = shorts.run_shorts(
            "zaflas",
            count=1,
            visual_mode="ai-video",
            video_provider="google-flow",
            dry_run=True,
        )
        self.assertEqual(result, [])
        faith_res = faith_shorts.run(
            "whispers-from-heaven",
            count=1,
            visual_mode="ai-video",
            video_provider="google-flow",
            dry_run=True,
        )
        self.assertEqual(faith_res, [])

    def test_concurrent_scene_lock_prevents_duplicate_scene_generation(self):
        from tools.ytbot.shorts_video.pipeline import _file_lock

        lock_path = self.root / "scenes" / "scene_01.lock"
        with _file_lock(lock_path):
            with self.assertRaises(RuntimeError):
                with _file_lock(lock_path):
                    pass

    def test_paid_gemini_api_requires_explicit_approval_and_reconciles_operations(self):
        run_dir = self.root / "gemini-run"
        run_dir.mkdir()
        sb = plan_short_storyboard("vocal-pages", "Quiet Light", "Light fades slowly.", total_duration_sec=10.0)
        scene = sb.scenes[0]
        api = GeminiVideoAPIProvider()

        with self.assertRaises(ProviderUnavailableError):
            api.generate_scene(scene, run_dir, {"allow_paid_api": False})

        cfg = api.config_path()
        cfg.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"api_key": "synthetic-key"}))
        cfg.chmod(0o600)

        calls = []

        def fake_http(url, *, payload=None, api_key):
            calls.append((url, payload is not None))
            if payload is not None:
                return {"name": "operations/synthetic-op-1"}
            return {
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [{"video": {"uri": "https://example.invalid/clip.mp4"}}]
                    }
                },
            }

        def fake_download(_uri, dest, _api_key):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"SYNTHETIC_MP4_" * 60)
            return dest

        approved = {"allow_paid_api": True, "max_credits_per_short": 40.0, "max_credits_per_batch": 200.0}
        with (
            patch.object(api, "_http_json", side_effect=fake_http),
            patch.object(api, "_download_video", side_effect=fake_download),
            patch("tools.ytbot.shorts_video.providers.validate_clip", side_effect=_ok_validation),
        ):
            clip, cost = api.generate_scene(scene, run_dir, approved)
        self.assertTrue(clip.is_file())
        self.assertGreater(cost, 0.0)
        self.assertEqual(scene.operation_name, "operations/synthetic-op-1")
        # Reconcile reuses existing clip without starting another API operation.
        calls.clear()
        with (
            patch.object(api, "_http_json", side_effect=fake_http),
            patch("tools.ytbot.shorts_video.providers.validate_clip", side_effect=_ok_validation),
        ):
            reconciled = api.reconcile_scene(scene, run_dir, approved)
        self.assertEqual(reconciled, clip)
        self.assertEqual(calls, [])

    def test_distribute_shorts_preserves_documentary_static_policy(self):
        from tools.ytbot import shorts_distribute

        invoked = []

        def fake_run(cmd, **_kwargs):
            invoked.append(cmd)
            return SimpleNamespace(returncode=0)

        plan = {slug: 0 for slug in shorts_distribute.SHORTS_CHANNELS}
        plan.update({"zaflas": 1, "sepia-atlas": 1})
        with (
            patch.object(shorts_distribute, "scheduled_shorts", return_value=0),
            patch.object(shorts_distribute, "allocate", return_value=plan),
            patch("tools.ytbot.comments.answer_all"),
            patch.object(shorts_distribute.subprocess, "run", side_effect=fake_run),
        ):
            failures = shorts_distribute.run_distribution(
                2,
                visual_mode="ai-video",
                video_provider="google-flow",
            )
        self.assertEqual(failures, [])
        by_channel = {cmd[cmd.index("--channel") + 1]: cmd for cmd in invoked}
        self.assertEqual(by_channel["zaflas"][by_channel["zaflas"].index("--visual-mode") + 1], "ai-video")
        self.assertEqual(by_channel["sepia-atlas"][by_channel["sepia-atlas"].index("--visual-mode") + 1], "static")
