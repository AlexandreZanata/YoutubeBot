import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image

from tools.ytbot import community, logic


class CommunityPostTests(unittest.TestCase):
    def test_post_text_keeps_the_topic_as_a_question(self):
        text = community.post_text("Why Do We Obey Rules When Nobody Is Watching?", "en")
        self.assertTrue(text.startswith("Why Do We Obey Rules When Nobody Is Watching?\n\n"))
        self.assertIn("Tell me in the comments.", text)
        self.assertNotIn("—", text)
        self.assertNotIn("–", text)

    def test_portuguese_post_text_uses_the_channel_language(self):
        text = community.post_text("Por que obedecemos regras?", "pt-BR")
        self.assertIn("Conte nos comentários.", text)

    def test_square_image_is_cropped_for_the_community_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "thumbnail.png"
            destination = Path(directory) / "post.png"
            Image.new("RGB", (1280, 720), "gray").save(source)
            community.square_image(source, destination)
            with Image.open(destination) as image:
                self.assertEqual(image.size, (1080, 1080))
                self.assertEqual(image.mode, "RGB")

    def test_relative_post_time_crosses_midnight(self):
        now = datetime(2026, 11, 15, 0, 30)
        for label in ("há 40 minutos", "40 minutes ago"):
            minutes = community.relative_minutes(label)
            self.assertEqual(minutes, 40)
            self.assertNotEqual((now - community.timedelta(minutes=minutes)).date(), now.date())
        self.assertEqual(community.relative_minutes("há 2 horas"), 120)
        self.assertEqual(community.relative_minutes("1 day ago"), 1440)
        self.assertEqual(community.relative_minutes("há 3 dias"), 4320)

    def test_post_type_catalog_covers_the_community_options(self):
        self.assertEqual(set(community.POST_TYPES), {
            "text", "image", "gif", "poll-text", "poll-image", "quiz", "video", "playlist",
        })


class ThumbnailStyleTests(unittest.TestCase):
    def test_twelve_videos_split_six_dense_and_six_classic(self):
        styles = [logic.thumbnail_style(index) for index in range(12)]
        self.assertEqual(styles.count("dense"), 6)
        self.assertEqual(styles.count("classic"), 6)
        self.assertEqual(styles[:2], ["dense", "classic"])


if __name__ == "__main__":
    unittest.main()
