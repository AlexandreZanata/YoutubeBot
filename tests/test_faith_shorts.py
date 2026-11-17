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

    def test_each_channel_has_five_topics(self):
        for spec in faith_shorts.CHANNELS.values():
            self.assertEqual(len(spec["topics"]), 5)


if __name__ == "__main__":
    unittest.main()
