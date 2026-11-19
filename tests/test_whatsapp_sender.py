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

    def test_confirmed_accepts_whatsapp_formatted_text(self):
        class BubblePage:
            def evaluate(self, script, limit):
                return [{"dir": "out", "text": "Negrito e mais texto", "id": "msg-2", "media": ""}]

        self.assertTrue(sender.confirmed(BubblePage(), "*Negrito* e mais texto", {"msg-1"}))

    def test_deliver_retypes_once_when_chat_hydration_clears_composer_before_send(self):
        now = [100.0]

        class HydrationPage:
            def __init__(self, wipe_twice=False):
                self.typed = ""
                self.bubbles = [{"dir": "out", "text": "anterior", "id": "old"}]
                self.sends = 0
                self.enters = 0
                self.wipe_next_sleep = True
                self.wipe_twice = wipe_twice
                page = self

                class Keyboard:
                    def insert_text(self, chunk):
                        page.typed += chunk

                    def press(self, key):
                        if key == "Delete":
                            page.typed = ""
                        elif key == "Enter":
                            page.enters += 1

                self.keyboard = Keyboard()

            def locator(self, selector):
                page = self

                class Node:
                    first = None

                    def click(self, timeout=None):
                        pass

                    def evaluate(self, script):
                        pass

                    def inner_text(self):
                        return page.typed

                    def count(self):
                        return 0 if selector == "#main" else 1

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
                        page.sends += 1
                        page.bubbles.append({"dir": "out", "text": page.typed, "id": "new"})

                button = Button()
                button.first = button
                return button

            def evaluate(self, script, limit):
                return list(self.bubbles)

            def wait_for_timeout(self, ms):
                now[0] += ms / 1000
                if self.wipe_twice and ms == 150 and self.sends == 0:
                    self.typed = ""

        page = HydrationPage()

        def fake_sleep(seconds):
            now[0] += seconds
            # Only wipe during the post-typing cooldown sleep, not inter-chunk keystroke pauses.
            if page.wipe_next_sleep and seconds >= 0.5:
                page.typed = ""
                page.wipe_next_sleep = False

        with patch.object(sender.time, "monotonic", lambda: now[0]), \
                patch.object(sender.time, "sleep", fake_sleep):
            state = sender.deliver(page, "Boa tarde", sender.Pacing(), delay=2.0)
        self.assertEqual(state, "sent")
        self.assertEqual(page.sends, 1)
        self.assertEqual(page.bubbles[-1]["text"], "Boa tarde")

    def test_deliver_raises_before_send_if_composer_loses_text_after_retype(self):
        now = [100.0]

        class BrokenComposerPage:
            def __init__(self):
                self.typed = ""
                self.bubbles = []
                self.sends = 0
                self.enters = 0
                self.sleep_wiped = False
                page = self

                class Keyboard:
                    def insert_text(self, chunk):
                        page.typed += chunk

                    def press(self, key):
                        if key == "Delete":
                            page.typed = ""
                        elif key == "Enter":
                            page.enters += 1

                self.keyboard = Keyboard()

            def locator(self, selector):
                page = self

                class Node:
                    first = None

                    def click(self, timeout=None):
                        pass

                    def evaluate(self, script):
                        pass

                    def inner_text(self):
                        return "" if page.sleep_wiped and selector != "never" and len(page.typed) else page.typed

                    def count(self):
                        return 0 if selector == "#main" else 1

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
                        page.sends += 1

                button = Button()
                button.first = button
                return button

            def evaluate(self, script, limit):
                return []

            def wait_for_timeout(self, ms):
                now[0] += ms / 1000

        # Use a page that wipes during sleep once, then simulates empty composer read on retype check
        class EmptyOnSecondCheckPage(BrokenComposerPage):
            def __init__(self):
                super().__init__()
                self.typing_phase = 0

            def locator(self, selector):
                page = self

                class Node:
                    first = None

                    def click(self, timeout=None):
                        pass

                    def evaluate(self, script):
                        pass

                    def inner_text(self):
                        # Return typed text on initial check, empty after sleep and on retype check
                        if page.typing_phase == 1:
                            return page.typed
                        return ""

                    def count(self):
                        return 0 if selector == "#main" else 1

                node = Node()
                node.first = node
                return node

        page = EmptyOnSecondCheckPage()
        orig_insert = page.keyboard.insert_text

        def tracked_insert(chunk):
            if page.typing_phase == 0:
                page.typing_phase = 1
            orig_insert(chunk)

        page.keyboard.insert_text = tracked_insert

        def fake_sleep(seconds):
            now[0] += seconds
            if seconds >= 0.5:
                page.typing_phase = 2
                page.typed = ""

        with patch.object(sender.time, "monotonic", lambda: now[0]), \
                patch.object(sender.time, "sleep", fake_sleep), \
                self.assertRaises(RuntimeError) as ctx:
            sender.deliver(page, "Boa tarde", sender.Pacing(), delay=2.0)
        self.assertIn("before send", str(ctx.exception))
        self.assertEqual((page.sends, page.enters, page.typed), (0, 0, ""))

    def test_send_sequence_captures_debug_screenshot_on_unconfirmed(self):
        class ShotPage:
            def screenshot(self, path):
                Path(path).write_bytes(b"png-bytes")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_path = root / "journal.jsonl"
            debug_dir = root / "debug"
            results = sender.send_sequence(
                ShotPage(), "Lead", [{"key": "k1", "text": "Boa tarde", "delay": 1.0}],
                sender.Pacing(), journal_path,
                deliver_fn=lambda *a, **k: "unconfirmed", debug_dir=debug_dir,
            )
            self.assertEqual(results, [{"key": "k1", "state": "unconfirmed"}])
            entries = sender.read_journal(journal_path)
            self.assertEqual(entries[-1]["state"], "unconfirmed")
            shot = Path(entries[-1]["screenshot"])
            self.assertTrue(shot.is_file())
            self.assertEqual(shot.parent, debug_dir)


if __name__ == "__main__":
    unittest.main()
