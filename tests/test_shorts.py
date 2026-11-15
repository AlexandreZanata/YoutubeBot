import unittest
from datetime import date

from tools.ytbot import shorts


class ShortsTests(unittest.TestCase):
    def test_slots_are_two_per_day(self):
        slots = shorts.short_slots(4, 2, date(2026, 11, 16))
        self.assertEqual([slot.strftime("%Y-%m-%d %H:%M") for slot in slots], [
            "2026-11-16 09:00", "2026-11-16 18:00",
            "2026-11-17 09:00", "2026-11-17 18:00",
        ])

    def test_metadata_keeps_the_site_and_shorts_tag(self):
        meta = shorts.short_metadata(shorts.SHORT_TOPICS[0], "Texto curto.")
        self.assertIn("https://zaflas.com.br/", meta["description"])
        self.assertIn("#Shorts", meta["title"])
        self.assertIn("#zaflasagro", meta["description"])
        self.assertIn("TAGS:", meta["description"])

    def test_twelve_topics_are_available(self):
        self.assertEqual(len(shorts.SHORT_TOPICS), 12)


if __name__ == "__main__":
    unittest.main()
