import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.ytbot import documentary


class DocumentaryTests(unittest.TestCase):
    def test_license_allowlist_keeps_public_domain_and_open_licenses(self):
        self.assertTrue(documentary.license_allowed("Public domain"))
        self.assertTrue(documentary.license_allowed("CC BY-SA 4.0"))
        self.assertTrue(documentary.license_allowed("CC0"))
        self.assertFalse(documentary.license_allowed("All rights reserved"))
        self.assertFalse(documentary.license_allowed(""))

    def test_timeline_covers_the_audio_without_gaps(self):
        sources = [{"file": "a.jpg"}, {"file": "b.jpg"}, {"file": "c.jpg"}]
        rows = documentary.timeline("one two three four five six seven eight nine ten", 30.0, sources)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["start"], 0.0)
        self.assertAlmostEqual(rows[-1]["end"], 30.0)
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous["end"], current["start"], places=2)

    def test_aligned_timeline_puts_each_photo_where_it_is_narrated(self):
        article = ("Mulberry Street crowded with immigrants. "
                   "The tenement kitchen was small. "
                   "The steel mill roared with workers.")
        sources = [
            {"file": "a.jpg", "title": "Mulberry Street New York",
             "narration_segment": "A crowded immigrant street", "place": "New York"},
            {"file": "b.jpg", "title": "Tenement kitchen interior",
             "narration_segment": "A tenement kitchen", "place": "New York"},
            {"file": "c.jpg", "title": "Steel mill workers",
             "narration_segment": "Steel mill", "place": "United States"},
        ]
        rows = documentary.timeline_aligned(article, 90.0, sources)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["start"], 0.0)
        self.assertAlmostEqual(rows[-1]["end"], 90.0)
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous["end"], current["start"], places=2)
            self.assertLess(previous["start"], current["start"])
        # The mill photo must not cover the opening street passage.
        self.assertGreater(rows[2]["start"], 30.0)

    def test_generic_subjects_share_dense_passages_evenly(self):
        article = " ".join(["street"] * 40 + ["market"] * 40 + ["school"] * 40)
        sources = [
            {"file": f"{name}.jpg", "title": name, "narration_segment": name,
             "place": "United States"}
            for name in ("street", "market", "school")
        ]
        rows = documentary.timeline_aligned(article, 90.0, sources, min_seconds=6.0)
        for row in rows:
            self.assertGreaterEqual(row["end"] - row["start"], 6.0)
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous["end"], current["start"], places=2)

    def test_aligned_timeline_resists_outlier_drift(self):
        article = ("Mulberry Street crowded with immigrants. "
                   + " ".join(["city"] * 30) + " "
                   + "Electric streetcar wires crossed the avenue. "
                   + " ".join(["work"] * 30) + " "
                   + "Baseball drew crowds to the park.")
        sources = [
            {"file": "a.jpg", "title": "Mulberry Street", "narration_segment": "Mulberry Street", "place": "New York"},
            {"file": "b.jpg", "title": "Unknown alley", "narration_segment": "Unmentioned alley", "place": "Boston"},
            {"file": "c.jpg", "title": "Streetcar", "narration_segment": "Electric streetcar", "place": "Chicago"},
            {"file": "d.jpg", "title": "Baseball", "narration_segment": "Baseball", "place": "United States"},
        ]
        rows = documentary.timeline_aligned(article, 100.0, sources, min_seconds=5.0)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0]["start"], 0.0)
        self.assertAlmostEqual(rows[-1]["end"], 100.0)
        # Baseball is near the end (~90%+ of article), must not be dragged earlier.
        self.assertGreater(rows[3]["start"], 60.0)

    def test_render_with_crossfade_and_analog_texture(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            photos = []
            for name, color in (("p1.jpg", "red"), ("p2.jpg", "blue")):
                p = run / name
                Image.new("RGB", (640, 360), color).save(p)
                photos.append(p)
            narration = run / "narration.aac"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "sine=frequency=440:duration=10", "-c:a", "aac", str(narration)],
                check=True,
            )
            rows = [
                {"photo": str(photos[0]), "start": 0.0, "end": 5.0},
                {"photo": str(photos[1]), "start": 5.0, "end": 10.0},
            ]
            out = documentary.render(run, rows, narration=narration, output_name="out.mp4",
                                     crossfade=1.0, analog_texture=True, voice_filter=True, workers=2)
            self.assertTrue(out.is_file())
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(out)],
                capture_output=True, text=True, check=True,
            )
            dur = float(probe.stdout.strip())
            self.assertAlmostEqual(dur, 10.0, delta=0.5)
            # Re-mux with voice filter only via mux_audio (-c:v copy)
            remuxed = documentary.mux_audio(
                run / "silent.mp4", narration, run / "out-voice-only.mp4", 10.0,
                voice_filter=True, analog_texture=False,
            )
            self.assertTrue(remuxed.is_file())

    def test_sepia_atlas_defaults_lock_speed_voice_filter_and_duration_bounds(self):
        import inspect
        from tools.ytbot import channels

        self.assertEqual(inspect.signature(documentary.slow_narration).parameters["factor"].default, 0.9)
        render_params = inspect.signature(documentary.render).parameters
        self.assertTrue(render_params["voice_filter"].default)
        self.assertTrue(render_params["analog_texture"].default)
        channel = channels.CHANNELS["sepia-atlas"]
        self.assertEqual(channel.min_article_chars, 13000)
        self.assertEqual(channel.max_article_chars, 36000)

    def test_thumbnail_is_a_1280x720_episode_specific_title(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            photo = run / "photo.jpg"
            Image.new("RGB", (1200, 800), "gray").save(photo)
            destination = documentary.thumbnail(run, photo, "AMERICA IN 1900")
            with Image.open(destination) as image:
                self.assertEqual(image.size, (1280, 720))


if __name__ == "__main__":
    unittest.main()
