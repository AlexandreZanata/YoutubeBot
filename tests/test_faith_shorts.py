import unittest
from datetime import date

from tools.ytbot import faith_shorts


class FaithShortsTests(unittest.TestCase):
    def test_reflection_hours_are_apart_from_the_long_videos(self):
        slots = faith_shorts.short_slots(2, (8, 20), date(2027, 1, 1))
        self.assertEqual([slot.strftime("%H:%M") for slot in slots], ["08:00", "20:00"])
        self.assertEqual(slots[0].date(), date(2027, 1, 1))

    def test_skip_slots_leaves_the_first_slot_to_another_run(self):
        slots = faith_shorts.short_slots(2, (8, 20), date(2027, 1, 1), skip=1)
        self.assertEqual([slot.strftime("%m-%d %H:%M") for slot in slots],
                         ["01-01 20:00", "01-02 08:00"])

    def test_metadata_carries_the_shorts_tag(self):
        meta = faith_shorts.metadata("Hannah", "Texto.")
        self.assertIn("#Shorts", meta["title"])
        self.assertIn("#shorts", meta["description"])

    def test_every_channel_now_publishes_shorts(self):
        from tools.ytbot import channels, shorts_distribute

        expected = set(channels.CHANNELS)
        self.assertEqual(set(faith_shorts.CHANNELS), expected)
        self.assertEqual(set(shorts_distribute.SHORTS_CHANNELS), expected)

    def test_midnight_tales_keeps_one_short_every_two_days(self):
        slots = faith_shorts.short_slots(3, (9,), date(2027, 1, 1), interval_days=2)
        self.assertEqual([slot.strftime("%m-%d %H:%M") for slot in slots],
                         ["01-01 09:00", "01-03 09:00", "01-05 09:00"])
        self.assertEqual(faith_shorts.CHANNELS["midnight-tales"]["interval_days"], 2)

    def test_midnight_tales_long_videos_keep_the_two_day_cadence(self):
        from tools.ytbot import channels

        channel = channels.get("midnight-tales")
        self.assertEqual(channel.interval_days, 2)
        self.assertEqual(channel.slots, (21,))
        self.assertEqual(channel.channel_id, "UCLukC7RYzHlXHjtnlkbe4Vw")

    def test_sepia_and_bathylora_keep_every_two_days_for_longs_and_shorts(self):
        from tools.ytbot import channels

        for slug, hours in (("sepia-atlas", (9,)), ("bathylora", (21,))):
            channel = channels.get(slug)
            self.assertEqual(channel.interval_days, 2)
            self.assertEqual(channel.slots, (21,))
            self.assertEqual(faith_shorts.CHANNELS[slug]["interval_days"], 2)
            self.assertEqual(faith_shorts.CHANNELS[slug]["hours"], hours)

    def test_a_copied_background_is_detected_against_other_shorts(self):
        import tempfile
        from pathlib import Path
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            image = Image.new("RGB", (108, 192), "black")
            image.paste("white", (0, 0, 108, 96))
            image.save(first / "thumbnail.png")
            image.save(second / "thumbnail.png")
            self.assertEqual(faith_shorts.background_signature(first / "thumbnail.png"),
                             faith_shorts.background_signature(second / "thumbnail.png"))
            self.assertIsNotNone(faith_shorts.similar_background(root, first))
            image2 = Image.new("RGB", (108, 192), "gray")
            image2.paste("white", (0, 96, 108, 192))
            image2.save(second / "thumbnail.png")
            self.assertIsNone(faith_shorts.similar_background(root, first))

    def test_each_channel_has_a_topic_queue(self):
        for spec in faith_shorts.CHANNELS.values():
            self.assertGreaterEqual(len(spec["topics"]), 5)


if __name__ == "__main__":
    unittest.main()

    def test_shorts_distribution_uses_the_gemini_engine(self):
        from tools.ytbot import shorts_distribute

        command = shorts_distribute.command_for("reflection", 1)
        self.assertIn("--engine", command)
        self.assertEqual(command[command.index("--engine") + 1], "gemini")
