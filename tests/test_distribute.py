import unittest

from tools.ytbot import distribute


class AllocationTests(unittest.TestCase):
    def test_next_video_goes_to_the_channel_with_fewer_scheduled(self):
        plan = distribute.allocate(3, {"a": 0, "b": 1})
        self.assertEqual(plan, {"a": 2, "b": 1})

    def test_plan_levels_the_channels_before_adding_extras(self):
        plan = distribute.allocate(8, {"a": 6, "b": 0})
        self.assertEqual(plan, {"a": 1, "b": 7})

    def test_zero_videos_keeps_every_channel_untouched(self):
        plan = distribute.allocate(0, {"a": 3, "b": 8})
        self.assertEqual(plan, {"a": 0, "b": 0})

    def test_every_upload_channel_has_its_bound_account(self):
        self.assertEqual(distribute.UPLOAD_ACCOUNTS["midnight-tales"], "midnight")
        self.assertEqual(distribute.UPLOAD_ACCOUNTS["zanata"], "zanata")
        self.assertEqual(distribute.UPLOAD_ACCOUNTS["reflection"], "reflection")

    def test_negative_count_is_rejected(self):
        with self.assertRaises(ValueError):
            distribute.allocate(-1, {"a": 0})


if __name__ == "__main__":
    unittest.main()
