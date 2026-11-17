import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ytbot.commercial.whatsapp import listener, sender

ITEMS = [{"key": f"k{index}", "text": f"mensagem {index}", "delay": 0} for index in range(3)]


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.journal = Path(self.directory.name) / "journal.jsonl"

    def tearDown(self):
        self.directory.cleanup()

    def send(self, states):
        sent = []

        def deliver(page, text, pacing, delay=None, link_wait=0.0):
            state = states.pop(0)
            if state == "sent":
                sent.append(text)
            return state
        results = sender.send_sequence(None, "Empresa", ITEMS, sender.Pacing(), self.journal,
                                       extra={"kind": "sales-opening"}, deliver_fn=deliver)
        return results, sent

    def test_sequence_stops_at_the_first_unconfirmed_message(self):
        results, sent = self.send(["sent", "unconfirmed", "sent"])
        self.assertEqual([item["state"] for item in results], ["sent", "unconfirmed"])
        self.assertEqual(sent, ["mensagem 0"])
        self.assertEqual(sender.journal_state(self.journal, "k1"), "uncertain")
        self.assertEqual(sender.read_journal(self.journal)[0]["kind"], "sales-opening")

    def test_uncertain_keys_are_never_retried_and_sent_keys_are_skipped(self):
        self.send(["sent", "unconfirmed"])
        results, sent = self.send(["sent", "sent", "sent"])
        self.assertEqual([item["state"] for item in results], ["duplicate", "fenced"])
        self.assertEqual(sent, [])

    def test_exception_is_journaled_as_error(self):
        def deliver(page, text, pacing, delay=None, link_wait=0.0):
            raise RuntimeError("composer missing")
        results = sender.send_sequence(None, "Empresa", ITEMS, sender.Pacing(), self.journal,
                                       deliver_fn=deliver)
        self.assertEqual(results[0]["state"], "error")
        self.assertEqual(len(results), 1)

    def test_open_chat_by_number_uses_the_click_to_chat_url(self):
        class Locator:
            def __init__(self, count, text=""):
                self._count, self._text = count, text

            def count(self):
                return self._count

            def inner_text(self):
                return self._text

        class Page:
            url = None

            def goto(self, url, timeout):
                self.url = url

            def locator(self, selector):
                return Locator(1) if selector == sender.COMPOSER else Locator(0)

            def wait_for_timeout(self, ms):
                pass

        page = Page()
        with patch.object(sender.time, "sleep"):
            sender.open_chat(page, "Empresa", sender.Pacing(), phone="+55 65 90000-0001")
        self.assertEqual(page.url, "https://web.whatsapp.com/send?phone=5565900000001")

    def test_number_without_whatsapp_is_reported(self):
        class Locator:
            def __init__(self, count, text=""):
                self._count, self._text = count, text

            def count(self):
                return self._count

            def inner_text(self):
                return self._text

        class Page:
            def goto(self, url, timeout):
                pass

            def locator(self, selector):
                if selector == "body":
                    return Locator(1, "Phone number shared via url is invalid.")
                return Locator(0)

            def wait_for_timeout(self, ms):
                pass

        with self.assertRaises(sender.InvalidNumber):
            sender.open_chat(Page(), "Empresa", sender.Pacing(), phone="5565900000001")


class ContactRuleTests(unittest.TestCase):
    def test_phone_entries_match_formatted_chat_titles(self):
        rules = {"mode": "allow", "contacts": ["+5565900000001"]}
        self.assertTrue(listener.contact_allowed("+55 65 90000-0001", rules))
        self.assertFalse(listener.contact_allowed("+55 65 90000-0002", rules))

    def test_allow_and_revoke_keep_the_rules_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            listener.save_rules(path, "allow", ["Renê"])
            listener.allow_contact(path, "+5565900000001")
            self.assertEqual(listener.load_rules(path)["contacts"], ["Renê", "+5565900000001"])
            listener.revoke_contact(path, "+5565900000001")
            self.assertEqual(listener.load_rules(path), {"mode": "allow", "contacts": ["Renê"]})
            listener.save_rules(path, "block", [])
            listener.revoke_contact(path, "+5565900000001")
            self.assertEqual(listener.load_rules(path)["contacts"], ["+5565900000001"])


if __name__ == "__main__":
    unittest.main()
