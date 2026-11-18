"""The desktop manager's channel table must match the bot's channel profiles."""

import re
import unittest
from pathlib import Path

from tools.ytbot import channels

CATALOG = Path(__file__).resolve().parents[1] / "desktop/crates/reports/src/catalog.rs"
ENTRY = re.compile(
    r'slug: "(?P<slug>[^"]+)",\s*name: "(?P<name>[^"]+)",\s*handle: "(?P<handle>[^"]+)",'
    r'\s*channel_id: "(?P<channel_id>[^"]+)"')


class DesktopCatalogTests(unittest.TestCase):
    def test_rust_catalog_mirrors_every_channel_profile(self):
        entries = {match["slug"]: match.groupdict() for match in ENTRY.finditer(CATALOG.read_text())}
        self.assertEqual(set(entries), set(channels.CHANNELS))
        for slug, channel in channels.CHANNELS.items():
            entry = entries[slug]
            self.assertEqual(entry["name"], channel.name, slug)
            self.assertEqual(entry["handle"], channel.handle, slug)
            self.assertEqual(entry["channel_id"], channel.channel_id, slug)


if __name__ == "__main__":
    unittest.main()
