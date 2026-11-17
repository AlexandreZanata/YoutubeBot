import tempfile
import unittest
from pathlib import Path

from tools.ytbot.commercial.whatsapp import listener


class WhatsAppListenerTests(unittest.TestCase):
    def test_parse_row_reads_title_time_and_incoming_preview(self):
        parsed = listener.parse_row("Renê\n12:32 PM\nJá mudei")
        self.assertEqual(parsed, {"title": "Renê", "preview": "Já mudei", "stamp": "12:32 PM"})

    def test_parse_row_rebuilds_outgoing_preview(self):
        parsed = listener.parse_row("Devs\n12:20 PM\nYou\n:\xa0\nSim")
        self.assertEqual(parsed["preview"], "You: Sim")

    def test_shortcut_rows_are_ignored(self):
        self.assertEqual(listener.parse_row("Locked chats"), {})

    def test_allowlist_only_permits_listed_contacts(self):
        rules = {"mode": "allow", "contacts": ["Renê"]}
        self.assertTrue(listener.contact_allowed("Renê", rules))
        self.assertFalse(listener.contact_allowed("Frotas do L", rules))

    def test_blocklist_only_blocks_listed_contacts(self):
        rules = {"mode": "block", "contacts": ["Frotas do L"]}
        self.assertTrue(listener.contact_allowed("Renê", rules))
        self.assertFalse(listener.contact_allowed("Frotas do L", rules))

    def test_rules_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            listener.save_rules(path, "allow", ["Renê", "Frotas do L"])
            self.assertEqual(listener.load_rules(path),
                             {"mode": "allow", "contacts": ["Renê", "Frotas do L"]})

    def test_event_id_is_stable(self):
        first = listener.event_id("Renê", "Já mudei", "12:32 PM")
        self.assertEqual(first, listener.event_id("Renê", "Já mudei", "12:32 PM"))
        self.assertNotEqual(first, listener.event_id("Renê", "Já mudei", "12:33 PM"))


if __name__ == "__main__":
    unittest.main()
