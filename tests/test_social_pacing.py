import unittest
from datetime import datetime, timedelta

from tools.ytbot.social.x import pacing


class XPacingTests(unittest.TestCase):
    def test_interval_stays_inside_the_configured_bounds(self):
        config = pacing.Pacing()
        for _ in range(50):
            self.assertGreaterEqual(config.between_posts(), 120)
            self.assertLessEqual(config.between_posts(), 300)

    def test_first_publish_does_not_wait(self):
        self.assertEqual(pacing.delay_seconds(None, datetime(2026, 11, 17, 12, 0), 180), 0.0)

    def test_delay_is_only_the_missing_part(self):
        now = datetime(2026, 11, 17, 12, 0)
        self.assertEqual(pacing.delay_seconds(now - timedelta(seconds=60), now, 180), 120.0)

    def test_delay_is_zero_after_the_interval(self):
        now = datetime(2026, 11, 17, 12, 0)
        self.assertEqual(pacing.delay_seconds(now - timedelta(seconds=400), now, 180), 0.0)

    def test_wait_sleeps_the_remainder(self):
        now = datetime(2026, 11, 17, 12, 0)
        slept = []
        remaining = pacing.wait(now - timedelta(seconds=60), pacing.Pacing(120, 120),
                                slept.append, now)
        self.assertEqual(remaining, 60.0)
        self.assertEqual(slept, [60.0])


if __name__ == "__main__":
    unittest.main()
