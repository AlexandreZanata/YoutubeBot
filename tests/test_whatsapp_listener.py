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

    def test_parse_row_skips_the_avatar_initial(self):
        parsed = listener.parse_row("F\nFelipe\n3:15 PM\nquanto custa?")
        self.assertEqual(parsed, {"title": "Felipe", "preview": "quanto custa?",
                                  "stamp": "3:15 PM"})

    def test_unread_labels_are_not_times(self):
        self.assertFalse(listener.looks_like_time("2 unread messages"))
        self.assertTrue(listener.looks_like_time("3:15 PM"))
        self.assertTrue(listener.looks_like_time("Ontem"))

    def test_structured_row_marks_our_last_message(self):
        class Row:
            def __init__(self, data):
                self.data = data

            def evaluate(self, script):
                return self.data

            def inner_text(self):
                return ""
        mine = listener.read_row(Row({"title": "Felipe", "stamp": "3:14 PM",
                                      "preview": "https://abastevo.com.br", "outgoing": True}))
        theirs = listener.read_row(Row({"title": "Felipe", "stamp": "3:15 PM",
                                        "preview": "quanto custa?", "outgoing": False,
                                        "unread": True}))
        self.assertTrue(mine["outgoing"])
        self.assertEqual((theirs["title"], theirs["preview"], theirs["outgoing"]),
                         ("Felipe", "quanto custa?", False))

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

    def test_scan_once_reads_ready_chat_list_without_reloading(self):
        class FakeLocator:
            def __init__(self, present):
                self._present = present

            def count(self):
                return 1 if self._present else 0

        class ReadyPage:
            url = "https://web.whatsapp.com/send?phone=5566999999999"

            def __init__(self):
                self.visits = 0

            def goto(self, url, timeout=None):
                self.visits += 1

            def locator(self, selector):
                return FakeLocator(selector in (listener.CHAT_LIST, listener.ROW))

            def evaluate(self, script, arg):
                return [
                    {"title": "João Flávio", "stamp": "12:27 PM", "preview": "Issae chefia",
                     "outgoing": False, "unread": True, "fallbackText": ""},
                    {"title": "Felipe", "stamp": "12:20 PM", "preview": "Certo!",
                     "outgoing": True, "unread": False, "fallbackText": ""},
                ]

        page = ReadyPage()
        events = listener.scan_once(page, set(), {"mode": "allow", "contacts": ["João Flávio"]})
        self.assertEqual(page.visits, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["chat"], events[0]["text"], events[0]["allowed"]),
                         ("João Flávio", "Issae chefia", True))

    def test_scan_once_navigates_when_chat_list_is_not_mounted(self):
        class FakeLocator:
            def __init__(self, ready_ref):
                self.ready_ref = ready_ref

            def count(self):
                return 1 if self.ready_ref[0] else 0

        class ColdPage:
            url = "about:blank"

            def __init__(self):
                self.visits = 0
                self.mounted = [False]

            def goto(self, url, timeout=None):
                self.visits += 1
                self.url = url
                self.mounted[0] = True

            def wait_for_selector(self, selector, timeout=None):
                return None

            def wait_for_timeout(self, ms):
                pass

            def locator(self, selector):
                return FakeLocator(self.mounted)

            def evaluate(self, script, arg):
                return [{"title": "Ana", "stamp": "12:00 PM", "preview": "Oi",
                         "outgoing": False, "unread": True, "fallbackText": ""}]

        page = ColdPage()
        events = listener.scan_once(page, set(), {"mode": "allow", "contacts": ["Ana"]})
        self.assertEqual(page.visits, 1)
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
