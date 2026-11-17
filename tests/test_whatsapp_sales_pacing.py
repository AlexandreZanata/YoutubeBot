import random
import unittest

from tools.ytbot.commercial.whatsapp.sales.pacing import SalesPacing
from tools.ytbot.commercial.whatsapp.sales.rules import load


class SalesPacingTests(unittest.TestCase):
    pacing = SalesPacing.from_rules(load())

    def test_delay_grows_with_message_length_inside_the_bounds(self):
        rng = random.Random(7)
        short = [self.pacing.typing("Tudo bem?", rng) for _ in range(30)]
        medium = [self.pacing.typing("x" * 120, rng) for _ in range(30)]
        long = [self.pacing.typing("x" * 2000, rng) for _ in range(30)]
        self.assertTrue(all(self.pacing.min_seconds <= value <= self.pacing.max_seconds
                            for value in short + medium + long))
        self.assertLess(max(short), min(medium))
        self.assertEqual(set(long), {self.pacing.max_seconds})
        self.assertEqual(min(short), self.pacing.min_seconds)

    def test_only_the_first_reply_message_adds_reading_time(self):
        rng = random.Random(1)
        delays = self.pacing.plan(["a" * 60, "b" * 60], incoming="c" * 180, rng=rng)
        self.assertGreater(delays[0], delays[1])
        self.assertLessEqual(delays[0], self.pacing.max_seconds + self.pacing.reading_max)

    def test_pause_between_chats_stays_inside_the_bounds(self):
        rng = random.Random(3)
        for _ in range(50):
            value = self.pacing.between_chats(rng)
            self.assertTrue(self.pacing.between_min <= value <= self.pacing.between_max)


if __name__ == "__main__":
    unittest.main()
