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
