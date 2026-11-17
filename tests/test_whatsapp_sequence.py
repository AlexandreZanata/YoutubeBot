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

        def deliver(page, text, pacing, delay=None, link_wait=0.0, **kwargs):
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
        def deliver(page, text, pacing, delay=None, link_wait=0.0, **kwargs):
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


class FakeClock:
    def __init__(self, now):
        self.now = now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)


class DeliverPage:
    """Composer, Send button and bubbles; clicking Send adds our bubble."""

    def __init__(self, clock):
        self.clock = clock
        self.typed = ""
        self.bubbles = [{"dir": "out", "text": "anterior", "id": "old"}]
        self.sent_at = None
        page = self

        class Keyboard:
            def insert_text(self, chunk):
                page.typed += chunk

            def press(self, key):
                raise AssertionError("the Send button exists")

        self.keyboard = Keyboard()

    def locator(self, selector):
        page = self

        class Node:
            first = None

            def click(self):
                pass

            def count(self):
                return 1
        node = Node()
        node.first = node
        return node

    def get_by_role(self, role, name):
        page = self

        class Button:
            first = None

            def count(self):
                return 1 if name == "Send" else 0

            def click(self):
                page.sent_at = page.clock.now
                page.bubbles.append({"dir": "out", "text": page.typed, "id": "new"})
        button = Button()
        button.first = button
        return button

    def evaluate(self, script, limit):
        return list(self.bubbles)

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000


class DeliverTimingTests(unittest.TestCase):
    def deliver(self, text, delay, last_send, start, link_wait=0.0):
        clock = FakeClock(start)
        page = DeliverPage(clock)
        timing = {"last_send": last_send}
        with patch.object(sender.time, "monotonic", clock.monotonic), \
                patch.object(sender.time, "sleep", clock.sleep):
            state = sender.deliver(page, text, sender.Pacing(), delay=delay,
                                   link_wait=link_wait, timing=timing)
        return state, page, timing

    def test_interval_counts_from_the_previous_send_and_includes_typing(self):
        state, page, timing = self.deliver("Tudo bem?", 2.0, last_send=100.0, start=100.6)
        self.assertEqual(state, "sent")
        self.assertAlmostEqual(page.sent_at, 102.0, delta=0.01)
        self.assertEqual(timing["last_send"], page.sent_at)

    def test_link_waits_for_the_preview_inside_the_interval(self):
        _, page, _ = self.deliver("https://zaflas.com.br", 4.0, last_send=50.0, start=50.4,
                                  link_wait=3.0)
        self.assertAlmostEqual(page.sent_at, 54.0, delta=0.01)
        _, page, _ = self.deliver("https://zaflas.com.br", 1.0, last_send=50.0, start=50.4,
                                  link_wait=3.0)
        self.assertGreaterEqual(page.sent_at, 53.4)

    def test_missing_bubble_is_unconfirmed_after_the_bounded_wait(self):
        clock = FakeClock(10.0)
        page = DeliverPage(clock)
        page.get_by_role = lambda role, name: type("B", (), {
            "count": lambda self: 1, "first": property(lambda self: self),
            "click": lambda self: None})()
        with patch.object(sender.time, "monotonic", clock.monotonic), \
                patch.object(sender.time, "sleep", clock.sleep):
            state = sender.deliver(page, "Bom dia", sender.Pacing(), delay=1.0)
        self.assertEqual(state, "unconfirmed")


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
