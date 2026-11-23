"""FFmpeg integration tests for Shorts clip validation, vertical adaptation and assembly."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.engine.audio_mixer import get_audio_duration
from src.engine.subtitle_generator import save_ass_subtitles
from tools.ytbot.shorts_video.assembler import adapt_clip_to_vertical, assemble_short_video
from tools.ytbot.shorts_video.models import SceneSpec, ShortsOnlyViolationError, Storyboard
from tools.ytbot.shorts_video.validator import validate_clip


def _probe_streams(path: Path) -> dict:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    return json.loads(out)


def _make_synthetic_clip(path: Path, *, width: int, height: int, duration: float, with_audio: bool) -> None:
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=navy:s={width}x{height}:d={duration:.2f}:r=30",
    ]
    if with_audio:
        cmd.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration:.2f}"])
    cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    if with_audio:
        cmd.extend(["-c:a", "aac", "-shortest"])
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


def _make_synthetic_narration(path: Path, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:duration={duration:.2f}",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


class ShortsAssemblyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_clip_validation_checks_streams_symlinks_and_portrait_orientation(self):
        clip = self.root / "landscape.mp4"
        _make_synthetic_clip(clip, width=640, height=360, duration=2.0, with_audio=True)
        self.assertTrue(validate_clip(clip, require_portrait=False, min_duration=1.0).valid)
        self.assertFalse(validate_clip(clip, require_portrait=True, min_duration=1.0).valid)

        link = self.root / "symlink.mp4"
        link.symlink_to(clip)
        self.assertFalse(validate_clip(link).valid)

        corrupt = self.root / "corrupt.mp4"
        corrupt.write_bytes(b"not a real video file" * 50)
        self.assertFalse(validate_clip(corrupt).valid)

    def test_adapt_clip_to_vertical_crops_to_1080x1920_and_strips_generated_audio(self):
        src = self.root / "wide_with_audio.mp4"
        dst = self.root / "vertical.mp4"
        _make_synthetic_clip(src, width=1280, height=720, duration=2.0, with_audio=True)

        adapt_clip_to_vertical(src, dst, target_duration=2.5, width=1080, height=1920, fps=30)
        check = validate_clip(dst, require_portrait=True, min_duration=2.0)
        self.assertTrue(check.valid, check.reason)
        self.assertEqual((check.width, check.height), (1080, 1920))

        info = _probe_streams(dst)
        stream_types = [s["codec_type"] for s in info["streams"]]
        self.assertEqual(stream_types, ["video"])

        with self.assertRaises(ShortsOnlyViolationError):
            adapt_clip_to_vertical(src, dst, target_duration=2.0, width=1920, height=1080)

    def test_assemble_short_video_mixes_ai_and_static_fallback_with_narration_and_subtitles(self):
        run_dir = self.root / "short-asm"
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(parents=True)

        clip1 = clips_dir / "scene_01.mp4"
        _make_synthetic_clip(clip1, width=720, height=1280, duration=3.0, with_audio=True)

        Image.new("RGB", (1080, 1920), "#1f2937").save(run_dir / "thumbnail.png")

        narration = run_dir / "narration.aac"
        _make_synthetic_narration(narration, duration=6.0)
        narr_duration = get_audio_duration(narration)
        self.assertGreater(narr_duration, 5.0)

        subtitle = save_ass_subtitles(
            [
                {"start": 0.2, "end": 2.8, "text": "First synthetic line"},
                {"start": 3.0, "end": 5.5, "text": "Second synthetic line"},
            ],
            run_dir / "narration.ass",
            font_size=72,
            width=1080,
            height=1920,
            alignment=5,
            outline_width=5,
            margin_horizontal=72,
        )

        storyboard = Storyboard(
            channel="midnight-tales",
            topic="Quiet Harbor",
            language="en",
            total_duration_sec=narr_duration,
            scenes=[
                SceneSpec(
                    scene_id="scene_01",
                    scene_index=1,
                    script_section="First line.",
                    start_sec=0.0,
                    end_sec=3.0,
                    duration_sec=3.0,
                    visual_description="Harbor mist",
                    generation_prompt="Harbor mist",
                    status="validated",
                    output_path=str(clip1),
                ),
                SceneSpec(
                    scene_id="scene_02",
                    scene_index=2,
                    script_section="Second line.",
                    start_sec=3.0,
                    end_sec=6.0,
                    duration_sec=3.0,
                    visual_description="Lantern glow",
                    generation_prompt="Lantern glow",
                    status="fallback_static",
                ),
            ],
        )

        output = assemble_short_video(
            run_dir,
            storyboard,
            narration_path=narration,
            subtitle_path=subtitle,
        )
        self.assertTrue(output.is_file())
        info = _probe_streams(output)
        video_streams = [s for s in info["streams"] if s["codec_type"] == "video"]
        audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
        self.assertEqual(len(video_streams), 1)
        self.assertEqual(len(audio_streams), 1)
        self.assertEqual((video_streams[0]["width"], video_streams[0]["height"]), (1080, 1920))
        out_dur = float(info["format"]["duration"])
        self.assertAlmostEqual(out_dur, narr_duration, delta=0.5)

    def test_assembly_failure_preserves_existing_video_output(self):
        run_dir = self.root / "preserve-run"
        run_dir.mkdir()
        existing = run_dir / "video.mp4"
        existing.write_bytes(b"ORIGINAL_VALID_OUTPUT")
        narration = run_dir / "narration.aac"
        _make_synthetic_narration(narration, duration=3.0)
        storyboard = Storyboard(channel="zaflas", topic="Test", language="pt-BR", scenes=[])

        with self.assertRaises(RuntimeError):
            assemble_short_video(run_dir, storyboard, narration_path=narration)
        self.assertEqual(existing.read_bytes(), b"ORIGINAL_VALID_OUTPUT")
