"""Execution profiles never select content, browser accounts or publication behavior."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from tools.ytbot import config, flow_media, flow_profiles, render, service, service_jobs
from tools.ytbot.accounts_store import AccountStore, read_private
from src.engine.transcription_cache import cached_transcription


SEGMENTS = [{"id": 0, "start": 0.2, "end": 2.4, "text": "A complete sentence.", "avg_logprob": -0.1}]


class ProfileSelection(unittest.TestCase):
    def tearDown(self):
        flow_profiles.activate("standard")

    def test_standard_is_default_and_pending_fast_cannot_change_media(self):
        self.assertEqual(flow_profiles.resolve().effective, "standard")
        selected = flow_profiles.resolve("fast")
        self.assertEqual(selected.requested, "fast")
        self.assertEqual(selected.effective, "standard")
        self.assertEqual(selected.reason, "quality_validation_pending")
        with self.assertRaises(ValueError):
            flow_profiles.resolve("auto")

    def test_cli_overrides_environment_and_legacy_actor_ignores_it(self):
        from tools.ytbot.cli import build_parser

        with patch.dict(os.environ, {flow_profiles.ENVIRONMENT: "fast"}):
            self.assertEqual(flow_profiles.name(environment=True), "fast")
            self.assertEqual(flow_profiles.name("standard", environment=True), "standard")
            self.assertEqual(flow_profiles.activate_request({})["effective"], "standard")
        for parser, argv in [(build_parser(), ["run", "--channel", "fallem-prince"]),
                             (service.parser(), ["generate", "--operation-id", str(uuid.uuid4()),
                                                 "--channel", "fallem-prince", "--count", "1"])]:
            self.assertIsNone(parser.parse_args(argv).flow_profile)
            self.assertEqual(parser.parse_args(argv + ["--flow-profile", "fast"]).flow_profile, "fast")

    def test_admitted_standard_fallback_cannot_silently_upgrade_after_qualification(self):
        admitted = flow_profiles.resolve("fast").record()
        with patch.object(flow_profiles, "FAST_QUALIFIED", True):
            result = flow_profiles.activate_request({"flow_profile": "fast"}, admitted)
            self.assertEqual(result["requested"], "fast")
            self.assertEqual(result["effective"], "standard")
            self.assertEqual(flow_profiles.current().reason, "admitted_profile_unavailable")

    def test_service_keeps_legacy_fingerprint_and_profile_collisions_are_fenced(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "ROOT", Path(folder)):
            store = AccountStore()
            store.create("work", "Synthetic")
            operation = str(uuid.uuid4())
            launch = Mock()
            args = (operation, "fallem-prince", "work", 1, True)
            kwargs = dict(store=store, launcher=launch, unit_probe=lambda _id: False)
            first = service_jobs.submit(*args, **kwargs)
            second = service_jobs.submit(*args, **kwargs, flow_profile="standard")
            self.assertEqual(first, second)
            self.assertEqual(launch.call_count, 1)
            stored = read_private(service_jobs.jobs_root() / f"{operation}.json")
            legacy = {"channel": "fallem-prince", "account": "work", "count": 1, "approved_schedule": True}
            self.assertEqual(stored["request"], legacy)
            self.assertEqual(stored["fingerprint"], hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest())
            with self.assertRaises(ValueError):
                service_jobs.submit(*args, **kwargs, flow_profile="fast")

    def test_fast_request_and_effective_fallback_are_durably_recorded(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "ROOT", Path(folder)):
            store = AccountStore()
            operation = str(uuid.uuid4())
            result = service_jobs.submit(operation, "fallem-prince", "legacy", 1, True,
                                         flow_profile="fast", store=store, launcher=Mock(), unit_probe=lambda _: False)
            stored = read_private(service_jobs.jobs_root() / f"{operation}.json")
            self.assertEqual(stored["request"]["flow_profile"], "fast")
            self.assertEqual(result["flow_selection"]["effective"], "standard")
            self.assertTrue(stored["request"]["approved_schedule"])
            legacy = {**stored, "request": {"channel": "fallem-prince", "account": "legacy", "count": 1}}
            legacy.pop("flow_selection")
            self.assertEqual(service_jobs.public(legacy)["flow_profile"], "standard")

    def test_run_journal_records_requested_effective_and_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "run"
            run.mkdir()
            with patch.object(config, "RECORDS", Path(folder) / "records"), patch.object(render, "_render_video", return_value=run / "video.mp4"):
                flow_profiles.activate("fast")
                render.render_video(run)
            record = json.loads((run / "record.json").read_text())
            self.assertEqual(record["flow_profile"], flow_profiles.resolve("fast").record())
            self.assertEqual(record["stages"][-1]["stage"], "flow_profile")


class MediaFallback(unittest.TestCase):
    def test_candidate_cache_cannot_reuse_or_poison_standard_results(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "voice.wav"
            audio.write_bytes(b"synthetic audio")
            engine = Mock(return_value=SEGMENTS)
            args = (audio, "large-v3-turbo", "en", False, engine, Path(folder) / "cache")
            cached_transcription(*args)
            cached_transcription(*args, options={"cpu_threads": 2, "batch_size": 4})
            cached_transcription(*args)
            self.assertEqual(engine.call_count, 2)

    def test_batched_engine_receives_fixed_language_beam_threads_and_batch(self):
        from src.core.ai_transcriber import _transcribe_uncached

        pipeline = Mock()
        pipeline.transcribe.return_value = ([SimpleNamespace(id=0, start=0.2, end=2.4, text=" A complete sentence. ", avg_logprob=-0.1)], None)
        whisper = SimpleNamespace(WhisperModel=Mock(), BatchedInferencePipeline=Mock(return_value=pipeline))
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        with patch.dict("sys.modules", {"faster_whisper": whisper, "torch": torch}):
            result = _transcribe_uncached("voice.wav", "large-v3-turbo", "en", False, cpu_threads=2, batch_size=4)
        self.assertEqual(result, SEGMENTS)
        self.assertEqual(whisper.WhisperModel.call_args.kwargs["cpu_threads"], 2)
        self.assertEqual(pipeline.transcribe.call_args.kwargs,
                         dict(language="en", beam_size=1, vad_filter=True, word_timestamps=False,
                              batch_size=4, without_timestamps=False))

    def test_failed_or_empty_candidate_reuses_standard_transcription(self):
        fallback, notify = Mock(return_value=SEGMENTS), Mock()
        for outcome in ([], RuntimeError("unavailable")):
            with self.subTest(outcome=outcome), patch.object(flow_media, "FAST_ASR", "turbo-t2"), patch("src.engine.transcription_cache.cached_transcription", side_effect=outcome if isinstance(outcome, Exception) else None, return_value=outcome):
                self.assertEqual(flow_media.transcribe_fast("voice.wav", "en", fallback, notify), SEGMENTS)
        self.assertEqual(fallback.call_count, 2)
        self.assertEqual(notify.call_count, 2)

    def test_missing_gpu_tools_or_unsupported_language_never_changes_standard_recognition(self):
        fallback, notify = Mock(return_value=SEGMENTS), Mock()
        with tempfile.TemporaryDirectory() as directory, patch.object(flow_media, "runtime_tools", return_value=Path(directory)), patch.object(flow_media.subprocess, "run") as worker:
            self.assertEqual(flow_media.transcribe_fast("voice.wav", "en", fallback, notify), SEGMENTS)
            self.assertEqual(flow_media.transcribe_fast("voice.wav", "pt", fallback, notify), SEGMENTS)
            worker.assert_not_called()
        self.assertEqual(fallback.call_count, 2)
        notify.assert_any_call("asr", "unsupported_language")

    def test_private_gpu_worker_receives_only_fixed_local_paths_and_clean_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "ROOT", Path(directory)):
            root = Path(directory)
            tooling = root / ".local/flow-tools/tooling"
            (tooling / "intel/root/usr/lib/x86_64-linux-gnu").mkdir(parents=True)
            (tooling / "openvino-toolchain.json").write_text(json.dumps({"openvino_model": {"revision": "b568445dd5dc8c695bde596f8acbb4694fd6ba64"}}))
            audio = root / "voice.aac"
            audio.write_bytes(b"original private audio")

            def execute(command, **options):
                self.assertEqual(command[command.index("--device")+1], "GPU")
                self.assertEqual(command[command.index("--audio")+1], str(audio))
                self.assertEqual(options["env"]["HF_HUB_OFFLINE"], "1")
                self.assertNotIn("SYNTHETIC_API_KEY", options["env"])
                Path(command[command.index("--output")+1]).write_text(json.dumps(SEGMENTS))

            with patch.dict(os.environ, {"SYNTHETIC_API_KEY": "private-value"}), patch.object(flow_media.subprocess, "run", side_effect=execute):
                self.assertEqual(flow_media.local_openvino(audio, "en"), SEGMENTS)
            self.assertEqual(audio.read_bytes(), b"original private audio")

    def test_standard_cache_key_remains_byte_compatible_with_old_results(self):
        from src.engine.transcription_cache import cache_key

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "voice.aac"
            audio.write_bytes(b"identical audio bytes")
            settings = ["asr-cache-v1-beam1-vad", "large-v3-turbo", "en", False, ["1.2.1", "4.9.0"]]
            expected = hashlib.sha256(json.dumps(settings, sort_keys=True).encode() + audio.read_bytes()).hexdigest()
            with patch("src.engine.transcription_cache.engine_versions", return_value=["1.2.1", "4.9.0"]):
                self.assertEqual(cache_key(audio, "large-v3-turbo", "en", False), expected)

    def test_candidate_changes_only_video_options_and_failure_preserves_existing_result(self):
        from src.engine.video_composer import build_single_pass_command

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "video.mp4"
            output.write_bytes(b"previous complete video")
            arguments = dict(image_path=Path("background.mp4"), narr_path=Path("voice.aac"), bgm_path=None,
                             subtitle_path=None, output_path=output, narr_vol=2.0, bgm_vol=0.0,
                             width=1920, height=1080, fps=30, progress_callback=None,
                             total_duration=4305.16, background_is_video=True)
            original = build_single_pass_command(Path("background.mp4"), Path("voice.aac"), None, None, output,
                                                  fps=30, duration=4305.16, background_is_video=True)
            for candidate in flow_media.RENDER_CANDIDATES:
                command = flow_media.encoding_command(original, candidate)
                for flag in ("-af", "-r", "-g", "-t", "-c:a", "-b:a"):
                    self.assertEqual(command[command.index(flag)+1], original[original.index(flag)+1])
                self.assertEqual(command[-1], str(output))
            fallback, notify = Mock(return_value=False), Mock()
            with patch("src.engine.video_composer.execute_ffmpeg", return_value=(False, "encoder failed")):
                self.assertFalse(flow_media.render_fast(arguments, fallback, notify))
            fallback.assert_called_once()
            notify.assert_called_once_with("render", "candidate_failed")
            self.assertEqual(output.read_bytes(), b"previous complete video")

    def test_standard_fallback_replaces_output_only_after_a_complete_success(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "video.mp4"
            output.write_bytes(b"previous")
            arguments = dict(image_path=Path("background.mp4"), narr_path=Path("voice.aac"), bgm_path=None,
                             subtitle_path=None, output_path=output, total_duration=10,
                             progress_callback=None)

            def standard(target):
                self.assertEqual(output.read_bytes(), b"previous")
                target.write_bytes(b"complete standard result")
                return True

            with patch("src.engine.video_composer.execute_ffmpeg", return_value=(False, "encoder unavailable")):
                self.assertTrue(flow_media.render_fast(arguments, standard, Mock()))
            self.assertEqual(output.read_bytes(), b"complete standard result")

    def test_successful_candidate_atomically_replaces_output_without_standard_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "video.mp4"
            output.write_bytes(b"previous")
            arguments = dict(image_path=Path("background.mp4"), narr_path=Path("voice.aac"), bgm_path=None,
                             subtitle_path=None, output_path=output, total_duration=10,
                             progress_callback=None)

            def encode(command, *_, **_options):
                Path(command[-1]).write_bytes(b"complete optimized result")
                return True, ""

            fallback = Mock()
            with patch("src.engine.video_composer.execute_ffmpeg", side_effect=encode):
                self.assertTrue(flow_media.render_fast(arguments, fallback, Mock()))
            fallback.assert_not_called()
            self.assertEqual(output.read_bytes(), b"complete optimized result")
