import unittest
from datetime import date, datetime
from unittest.mock import patch

from tools.ytbot import channels, chat, config, logic, youtube


META = """TITLE OPTIONS:

1. Why Your Mind Fears Silence — More Than You Realize
2. Second title
3. Third title

DESCRIPTION:

First paragraph with an em dash — like this.

#psychology #silence #mind #philosophy #neuroscience

TAGS: one, two, three, four
"""


class MetadataTests(unittest.TestCase):
    def test_title_has_no_em_dash(self):
        parsed = logic.parse_metadata(META)
        self.assertNotIn("—", parsed["title"])
        self.assertNotIn("–", parsed["title"])
        self.assertIn(":", parsed["title"])
        self.assertNotIn(" :", parsed["title"])

    def test_description_matches_channel_pattern(self):
        parsed = logic.parse_metadata(META)
        self.assertIn("#psychology", parsed["description"])
        self.assertIn("TAGS: one, two, three, four", parsed["description"])
        self.assertNotIn("—", parsed["description"])

    def test_escaped_list_markers_from_the_chatgpt_browser_are_stripped(self):
        escaped = META.replace("1. Why", "1\\. Why").replace("#psychology", "\\#psychology")
        parsed = logic.parse_metadata(escaped)
        self.assertTrue(parsed["title"].startswith("Why Your Mind Fears Silence"))
        self.assertNotIn("\\", parsed["title"])
        self.assertIn("#psychology", parsed["description"])

    def test_tags_limit(self):
        parsed = logic.parse_metadata(META)
        self.assertLessEqual(len(parsed["tags"]), 425)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.slots = config.SLOT_HOURS

    def tearDown(self):
        config.SLOT_HOURS = self.slots

    def test_existing_scheduled_times(self):
        payload = {"x": {"scheduledPublishingDetails": {"scheduledPublishings": [
            {"scheduledTimeSeconds": "1796227200"}]}}}
        slots = logic.scheduled_slots(payload)
        self.assertEqual(len(slots), 1)
        day, hour = next(iter(slots))
        self.assertEqual((day.month, day.day, hour), (12, 2, 12))

    def test_fills_missing_slot_and_skips_occupied(self):
        config.SLOT_HOURS = (0, 12)
        start = datetime(2026, 11, 9, 9, 0)
        occupied = {(date(2026, 11, 9), 12)}
        slots = logic.next_slots(3, occupied, start=start, lead_minutes=60)
        labels = [logic.slot_label(slot) for slot in slots]
        self.assertEqual(labels, ["2026-11-10 00:00", "2026-11-10 12:00", "2026-11-11 00:00"])

    def test_interval_days_skips_the_days_between_slots(self):
        config.SLOT_HOURS = (0,)
        slots = logic.next_slots(3, set(), start=datetime(2026, 11, 16, 0, 0), interval_days=2)
        self.assertEqual([logic.slot_label(slot) for slot in slots],
                         ["2026-11-16 00:00", "2026-11-18 00:00", "2026-11-20 00:00"])

    def test_start_date_includes_its_midnight_slot(self):
        config.SLOT_HOURS = (0,)
        slots = logic.next_slots(1, set(), start=datetime(2026, 11, 16, 0, 0))
        self.assertEqual([logic.slot_label(slot) for slot in slots], ["2026-11-16 00:00"])

    def test_fills_middle_slots_for_four_per_day(self):
        config.SLOT_HOURS = (0, 6, 12, 18)
        start = datetime(2026, 11, 15, 0, 0)
        occupied = {
            (date(2026, 11, 15), 0), (date(2026, 11, 15), 12),
            (date(2026, 11, 16), 0), (date(2026, 11, 16), 12),
        }
        slots = logic.next_slots(4, occupied, start=start, lead_minutes=60)
        labels = [logic.slot_label(slot) for slot in slots]
        self.assertEqual(labels, [
            "2026-11-15 06:00", "2026-11-15 18:00",
            "2026-11-16 06:00", "2026-11-16 18:00",
        ])

    def test_portuguese_date(self):
        self.assertEqual(logic.format_pt_date(date(2026, 12, 2)), "2 de dez. de 2026")


class TopicTests(unittest.TestCase):
    def test_similar_topic_detection(self):
        catalog = [{"title": "Why We Fall in Love With People Who Are Wrong for Us"}]
        self.assertTrue(logic.similar_topics("Why We Fall in Love With the Wrong Person", catalog))
        self.assertFalse(logic.similar_topics("The Mathematics of Loneliness", catalog))


class ChannelProfileTests(unittest.TestCase):
    def test_zaflas_has_one_noon_slot_per_day(self):
        self.assertEqual(channels.get("zaflas").slots, (12,))
        self.assertEqual(channels.get("zaflas").max_article_chars, 100000)
        self.assertEqual(channels.get("zaflas").min_article_chars, 26000)

    def test_fallem_uses_two_daily_slots(self):
        # Owner decision 2026-11-20: 2/day at 00:00 and 12:00 (was 4/day until 2026-11-15).
        self.assertEqual(channels.get("fallem-prince").slots, (0, 12))

    def test_only_zaflas_uses_brazilian_portuguese(self):
        self.assertEqual(channels.get("zaflas").language, "pt-BR")
        self.assertEqual(channels.get("fallem-prince").language, "en")
        self.assertEqual(channels.get("whispers-from-heaven").language, "en")
        self.assertEqual(channels.get("infinite-random-worlds").language, "en")

    def test_vocal_pages_uses_its_generated_background(self):
        channel = channels.get("vocal-pages")
        self.assertEqual(channel.background, "vocal_pages")
        self.assertEqual(channel.channel_id, "UCm13oIPS1W43j9BYo0kewcQ")
        self.assertEqual(channel.slots, (0,))
        self.assertEqual(channel.interval_days, 2)
        self.assertEqual(channel.language, "en")

    def test_reflection_is_the_biblical_story_channel(self):
        channel = channels.get("reflection")
        self.assertEqual(channel.channel_id, "UCISw6UDaFINPRuuMr0s7tpA")
        self.assertEqual(channel.language, "en")
        self.assertEqual(channel.slots, (5, 17))

    def test_zanata_is_the_daily_book_summary_channel(self):
        channel = channels.get("zanata")
        self.assertEqual(channel.channel_id, "UCx0AE-elCyDhfY0d1hQIwdw")
        self.assertEqual(channel.language, "en")
        self.assertEqual(channel.slots, (16,))
        self.assertEqual(channel.max_article_chars, 100000)

    def test_infinite_uses_the_thumbnail_as_background(self):
        channel = channels.get("infinite-random-worlds")
        self.assertEqual(channel.background, "thumbnail")
        self.assertEqual(channel.channel_id, "UCY3Zp50I6Y6semQQccJxRPg")


class VideoIdTests(unittest.TestCase):
    class Page:
        def __init__(self, url: str, body: str):
            self.url = url
            self._body = body

        def locator(self, _selector):
            body = self._body

            class Body:
                def inner_text(self):
                    return body

            return Body()

    def test_reads_the_id_from_the_edit_url(self):
        page = self.Page("https://studio.youtube.com/video/kK_wyNBAxgg/edit", "")
        self.assertEqual(youtube.video_id_from(page), "kK_wyNBAxgg")

    def test_reads_a_shorts_share_link(self):
        page = self.Page("https://studio.youtube.com/channel/UC/videos/upload",
                         "Link do vídeo https://youtube.com/shorts/abc12345678")
        self.assertEqual(youtube.video_id_from(page), "abc12345678")

    def test_reads_the_share_link_from_the_dialog(self):
        page = self.Page("https://studio.youtube.com/channel/UC/videos/upload",
                         "Link do vídeo https://youtu.be/blAcpdN9bVg")
        self.assertEqual(youtube.video_id_from(page), "blAcpdN9bVg")


class CaptureStatusTests(unittest.TestCase):
    def test_missing_extension_worker_is_reported_without_waiting(self):
        class Context:
            service_workers = []
        self.assertEqual(chat._extension_status(Context(), "https://chatgpt.com/x"),
                         {"worker": False})


class DiskSpaceTests(unittest.TestCase):
    def test_low_space_is_rejected_before_media_starts(self):
        usage = type("Usage", (), {"free": int(1.5 * 1024 ** 3)})
        with patch.object(logic.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(RuntimeError, "at least 2.00 GB"):
                logic.require_free_space(config.RUNS, 2.0, "batch")

    def test_enough_space_returns_free_gigabytes(self):
        usage = type("Usage", (), {"free": int(3 * 1024 ** 3)})
        with patch.object(logic.shutil, "disk_usage", return_value=usage):
            self.assertEqual(logic.require_free_space(config.RUNS, 2.0, "batch"), 3.0)


if __name__ == "__main__":
    unittest.main()
