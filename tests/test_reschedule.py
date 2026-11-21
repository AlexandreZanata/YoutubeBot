import unittest
from datetime import datetime, timedelta

from tools.ytbot import channels, reschedule


def entry(video_id, moment):
    return {"videoId": video_id, "title": "", "moment": moment}


class ChannelSlotPolicyTests(unittest.TestCase):
    def test_two_slot_channels_keep_at_least_six_hours_apart(self):
        for channel in channels.CHANNELS.values():
            if len(channel.slots) > 1:
                gaps = [later - earlier for earlier, later in
                        zip(sorted(channel.slots), sorted(channel.slots)[1:])]
                self.assertTrue(all(gap >= 6 for gap in gaps), channel.slug)

    def test_documented_cadence_matches_the_audience_tuned_slots(self):
        expected = {
            "zaflas": ((11,), 1),
            "fallem-prince": ((10, 21), 1),
            "infinite-random-worlds": ((19,), 1),
            "vocal-pages": ((21,), 2),
            "reflection": ((8, 21), 1),
            "zanata": ((10,), 1),
            "sepia-atlas": ((21,), 2),
            "bathylora": ((21,), 2),
            "midnight-tales": ((21,), 2),
            "whispers-from-heaven": ((8, 22), 1),
        }
        for slug, (slots, interval) in expected.items():
            channel = channels.get(slug)
            self.assertEqual(channel.slots, slots, slug)
            self.assertEqual(channel.interval_days, interval, slug)
        self.assertEqual(len(expected), len(channels.CHANNELS))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 20, 8, 0)

    def test_moves_keep_the_date_and_within_day_order(self):
        entries = [entry("a", datetime(2026, 11, 21, 0, 0)),
                   entry("b", datetime(2026, 11, 21, 12, 0))]
        moves = reschedule.plan(entries, (8, 22), 1, self.now)
        self.assertEqual(moves[0]["target"], datetime(2026, 11, 21, 8, 0))
        self.assertEqual(moves[1]["target"], datetime(2026, 11, 21, 22, 0))

    def test_today_uses_a_later_slot_when_the_mapped_hour_is_too_close(self):
        moves = reschedule.plan([entry("a", datetime(2026, 11, 20, 12, 0))],
                                (8, 22), 1, self.now)
        self.assertEqual(moves[0]["target"], datetime(2026, 11, 20, 22, 0))
        self.assertEqual(moves[0]["note"], "late-slot")

    def test_video_with_no_lead_time_stays_at_its_current_slot(self):
        now = datetime(2026, 11, 20, 20, 30)
        moves = reschedule.plan([entry("a", datetime(2026, 11, 20, 21, 0))],
                                 (10, 21), 1, now)
        self.assertIsNone(moves[0]["target"])
        self.assertEqual(moves[0]["note"], "keep")

    def test_days_above_the_frequency_are_rebalanced_two_per_day(self):
        entries = []
        for day in range(21, 24):
            for index, hour in enumerate((0, 6, 12, 18)):
                entries.append(entry(f"v{day}_{index}", datetime(2026, 11, day, hour, 0)))
        moves = reschedule.plan(entries, (10, 21), 1, self.now)
        self.assertEqual(len(moves), 12)
        self.assertTrue(all(move["target"] is not None for move in moves))
        per_day = {}
        for move in moves:
            day = (move["target"] or move["entry"]["moment"]).date()
            per_day[day] = per_day.get(day, 0) + 1
        self.assertTrue(all(count <= 2 for count in per_day.values()), per_day)
        kept = [move for move in moves if move["note"] == "slot"]
        self.assertEqual(len(kept), 6)
        rebalanced = [move for move in moves if move["note"] == "rebalanced"]
        self.assertEqual(len(rebalanced), 6)
        self.assertTrue(all(move["target"] > self.now for move in moves))

    def test_interval_channels_rebalance_on_their_own_cadence(self):
        entries = [entry("a", datetime(2026, 11, 22, 0, 0)),
                   entry("b", datetime(2026, 11, 22, 12, 0))]
        moves = reschedule.plan(entries, (21,), 2, self.now)
        self.assertEqual(moves[0]["target"], datetime(2026, 11, 22, 21, 0))
        self.assertEqual(moves[1]["target"], datetime(2026, 11, 24, 21, 0))
        self.assertEqual(moves[1]["note"], "rebalanced")

    def test_past_videos_are_ignored_and_aligned_videos_are_not_moved(self):
        entries = [entry("past", datetime(2026, 11, 19, 21, 0)),
                   entry("aligned", datetime(2026, 11, 22, 21, 0))]
        moves = reschedule.plan(entries, (21,), 2, self.now)
        self.assertEqual([move["entry"]["videoId"] for move in moves], ["aligned"])
        self.assertEqual(moves[0]["target"], datetime(2026, 11, 22, 21, 0))

    def test_future_slots_respect_the_minimum_lead_minutes(self):
        now = datetime(2026, 11, 20, 9, 30)
        moves = reschedule.plan([entry("a", datetime(2026, 11, 20, 12, 0))],
                                (10, 21), 1, now)
        self.assertEqual(moves[0]["target"], datetime(2026, 11, 20, 21, 0))
        self.assertGreaterEqual(moves[0]["target"], now + timedelta(minutes=60))

    def test_enforce_interval_respaces_consecutive_days(self):
        entries = [entry("a", datetime(2026, 11, 20, 21, 0)),
                   entry("b", datetime(2026, 11, 21, 21, 0)),
                   entry("c", datetime(2026, 11, 23, 21, 0)),
                   entry("d", datetime(2026, 11, 24, 21, 0))]
        moves = reschedule.plan(entries, (21,), 2, self.now, enforce_interval=True)
        self.assertEqual([move["target"] for move in moves],
                         [datetime(2026, 11, 20, 21, 0),
                          datetime(2026, 11, 22, 21, 0),
                          datetime(2026, 11, 24, 21, 0),
                          datetime(2026, 11, 26, 21, 0)])
        self.assertEqual([move["note"] for move in moves],
                         ["aligned", "cadence", "cadence", "cadence"])

    def test_enforce_interval_keeps_the_lead_time(self):
        now = datetime(2026, 11, 20, 20, 30)
        entries = [entry("a", datetime(2026, 11, 20, 21, 0)),
                   entry("b", datetime(2026, 11, 21, 21, 0))]
        moves = reschedule.plan(entries, (21,), 2, now, enforce_interval=True)
        self.assertEqual([move["target"] for move in moves],
                         [datetime(2026, 11, 22, 21, 0),
                          datetime(2026, 11, 24, 21, 0)])


if __name__ == "__main__":
    unittest.main()
