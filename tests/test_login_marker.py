import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ytbot import config, runtime


class LoginMarkerTests(unittest.TestCase):
    def test_pending_login_is_recorded_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(config, "DATA", Path(directory)):
                entry = runtime.record_login_request(
                    "https://studio.youtube.com/", "expired", Path("/home/user/profile"))
            marker = Path(directory) / "needs-login.json"
            self.assertTrue(marker.is_file())
            data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(data["url"], "https://studio.youtube.com/")
            self.assertEqual(data["reason"], "expired")
            self.assertEqual(data["name"], "profile")
            self.assertNotIn("cookie", json.dumps(data).lower())
            self.assertEqual(entry, data)


if __name__ == "__main__":
    unittest.main()
