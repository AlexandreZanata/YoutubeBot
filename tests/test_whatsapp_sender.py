import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ytbot.commercial.whatsapp import sender


class WhatsAppSenderTests(unittest.TestCase):
    def test_pacing_stays_inside_the_configured_bounds(self):
        pacing = sender.Pacing(min_interval=3, max_interval=9)
        for _ in range(50):
            self.assertGreaterEqual(pacing.between_messages(), 3)
            self.assertLessEqual(pacing.between_messages(), 9)

    def test_whatsapp_bold_formatting_does_not_look_like_a_lost_text(self):
        self.assertEqual(sender.text_key("*Burgers artesanais*"), "Burgers artesanais")
        self.assertEqual(sender.text_key("  *X-Bacon*\n— R$ 24,00 "),
                         "X-Bacon — R$ 24,00")

    def test_message_key_is_stable_and_distinct(self):
        first = sender.message_key("Ana", "Oferta do dia", None)
        self.assertEqual(first, sender.message_key("Ana", "Oferta do dia", None))
        self.assertNotEqual(first, sender.message_key("Bia", "Oferta do dia", None))

    def test_journal_prevents_duplicate_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            key = sender.message_key("Ana", "Oi", None)
            self.assertFalse(sender.already_sent(path, key))
            sender.journal(path, {"key": key, "state": "sent"})
            self.assertTrue(sender.already_sent(path, key))
            entries = sender.read_journal(path)
            self.assertEqual(entries[0]["state"], "sent")

    def test_dry_run_never_marks_a_message_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            page = type("Page", (), {})()
            with patch.object(sender, "open_chat"):
                results = sender.send_batch(
                    page, [{"to": "Ana", "text": "Oi"}], sender.Pacing(1, 2), True, path)
            self.assertEqual(results[0]["state"], "dry-run")
            self.assertFalse(sender.already_sent(path, sender.message_key("Ana", "Oi", None)))

    def test_is_typing_detects_only_typing_header_status(self):
        class HeaderPage:
            def __init__(self, statuses):
                self.statuses = statuses

            def evaluate(self, script):
                return self.statuses

        for positive in (["digitando..."], ["Digitando…"], ["typing..."], ["typing"]):
            self.assertTrue(sender.is_typing(HeaderPage(positive)), positive)
        for negative in (["gravando áudio..."], ["recording audio..."], ["online"],
                         ["visto por último hoje às 08:20"], []):
            self.assertFalse(sender.is_typing(HeaderPage(negative)), negative)


    def test_ai_notice_modal_is_dismissed_on_chat_open(self):
        class Node:
            def __init__(self, page, selector):
                self.page = page
                self.selector = selector

            @property
            def first(self):
                return self

            def count(self):
                if self.selector == "#main":
                    return 1
                if self.selector == 'div[role="dialog"] button:has-text("OK")':
                    return 1 if self.page.modal and not self.page.dismissed else 0
                return 0

            def inner_text(self):
                if self.selector == "#main" and self.page.modal and not self.page.dismissed:
                    return ("Get quick help from business chats that use AI from Meta "
                            "OK")
                return "regular chat content"

            def click(self, timeout=None):
                self.page.dismissed = True

        class ModalPage:
            modal = True

            def __init__(self):
                self.dismissed = False
                self.waits = 0

            def locator(self, selector):
                return Node(self, selector)

            def wait_for_timeout(self, ms):
                self.waits += 1

        class PlainPage(ModalPage):
            modal = False

        page = ModalPage()
        self.assertTrue(sender.dismiss_ai_notice(page))
        self.assertTrue(page.dismissed)
        self.assertFalse(sender.dismiss_ai_notice(page),
                         "a dismissed modal is not clicked again")
        plain = PlainPage()
        self.assertFalse(sender.dismiss_ai_notice(plain))
        self.assertFalse(plain.dismissed)

if __name__ == "__main__":
    unittest.main()
