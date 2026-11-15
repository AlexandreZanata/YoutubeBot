import json
import tempfile
import unittest
from pathlib import Path

from tools.ytbot import cleanup


class CleanupTests(unittest.TestCase):
    def test_scheduled_run_keeps_records_and_loses_the_video(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            for name in ("video.mp4", "narration.wav", "narration.aac", "metadata.json",
                         "thumbnail.png", "upload-run.mp4"):
                (run / name).write_bytes(b"x" * 10)
            (run / "upload.json").write_text(
                json.dumps({"scheduled": True, "videoId": "abc12345678"}), encoding="utf-8")
            self.assertTrue(cleanup.scheduled_upload(run))
            files, freed = cleanup.prune_run(run)
            self.assertEqual(files, 3)
            self.assertEqual(freed, 30)
            self.assertFalse((run / "video.mp4").exists())
            self.assertFalse((run / "narration.wav").exists())
            self.assertTrue((run / "narration.aac").exists())
            self.assertTrue((run / "metadata.json").exists())
            self.assertTrue((run / "upload.json").exists())

    def test_dry_run_reports_without_deleting(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "video.mp4").write_bytes(b"x" * 10)
            files, freed = cleanup.prune_run(run, dry_run=True)
            self.assertEqual((files, freed), (1, 10))
            self.assertTrue((run / "video.mp4").exists())

    def test_unscheduled_run_is_not_touched(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "upload.json").write_text(json.dumps({"videoId": ""}), encoding="utf-8")
            self.assertFalse(cleanup.scheduled_upload(run))


if __name__ == "__main__":
    unittest.main()
