"""Frame-exact static caption caching retains the existing ASS and audio contract."""

from pathlib import Path
import tempfile
import unittest

from tools.ytbot import flow_media
from tools.ytbot.subtitle_cache import event_frame, preparation
from src.engine.subtitle_generator import save_ass_subtitles
from src.engine.video_composer import build_single_pass_command


class SubtitleCache(unittest.TestCase):
    def test_transition_occurs_on_first_frame_at_or_after_original_centisecond(self):
        self.assertEqual(event_frame("0:00:00.04", 30), 2)
        self.assertEqual(event_frame("0:00:05.34", 30), 161)
        self.assertEqual(event_frame("1:00:00.00", 30), 108000)

    def test_static_state_changes_preserve_gaps_and_the_final_empty_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subtitle = save_ass_subtitles([
                {"start": 0.04, "end": 1, "text": "First phrase."},
                {"start": 1.01, "end": 2, "text": "Second phrase."}], root / "captions.ass")
            original = subtitle.read_bytes()
            command, movie, changes = preparation(subtitle, root / "cache", 3)
            self.assertEqual(changes, [0, 2, 30, 31, 60, 90])
            self.assertEqual(subtitle.read_bytes(), original)
            self.assertIn("passthrough", command)
            self.assertEqual(movie.suffix, ".mov")
            concat = (root / "cache/states.ffconcat").read_text()
            self.assertEqual(concat.count("file '"), len(changes))
            self.assertTrue((root / "cache/transparent.png").exists())

    def test_animated_overrides_require_standard_instead_of_freezing_an_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subtitle = save_ass_subtitles([{"start": 0, "end": 1, "text": r"{\fad(100,100)}Animated"}], root / "captions.ass")
            with self.assertRaisesRegex(ValueError, "standard"):
                preparation(subtitle, root / "cache", 3)

    def test_cached_composition_keeps_audio_mix_fps_duration_and_original_ass(self):
        args = dict(image_path=Path("background.mp4"), narr_path=Path("voice.aac"), bgm_path=None,
                    subtitle_path=None, output_path=Path("video.mp4"), narr_vol=2.0,
                    bgm_vol=0.0, width=1920, height=1080, fps=30, total_duration=4305.16,
                    background_is_video=True)
        baseline = build_single_pass_command(Path("background.mp4"), Path("voice.aac"), None, None,
                    Path("video.mp4"), narr_vol=2.0, fps=30, duration=4305.16, background_is_video=True)
        cached = flow_media.cached_video_command(args, Path("captions.mov"), "vaapi-qp20-cached-ass")
        for option in ("-af", "-r", "-g", "-t", "-c:a", "-b:a"):
            self.assertEqual(cached[cached.index(option)+1], baseline[baseline.index(option)+1])
        graph = cached[cached.index("-filter_complex")+1]
        self.assertIn("[2:v]", graph)
        self.assertIn("overlay=alpha=straight", graph)
        self.assertNotIn("subtitles=", graph)
        self.assertEqual(cached[-1], "video.mp4")

    def test_qsv_quality_is_video_scoped_and_cqp_uses_cli_qscale_units(self):
        baseline = build_single_pass_command(Path("background.mp4"), Path("voice.aac"), None, None, Path("video.mp4"))
        cqp = flow_media.encoding_command(baseline, "qsv-qp22")
        icq = flow_media.encoding_command(baseline, "qsv-icq18")
        self.assertNotIn("-global_quality", cqp)
        self.assertNotIn("-global_quality", icq)
        self.assertEqual(cqp[cqp.index("-q:v")+1], "22")
        self.assertEqual(icq[icq.index("-global_quality:v")+1], "18")
