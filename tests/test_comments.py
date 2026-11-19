import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.ytbot import comments, config


class CommentReplyTests(unittest.TestCase):
    def test_inbox_url_keeps_the_unanswered_filter(self):
        url = comments.inbox_url("UCx0AE-elCyDhfY0d1hQIwdw")
        self.assertTrue(url.startswith(
            "https://studio.youtube.com/channel/UCx0AE-elCyDhfY0d1hQIwdw/comments/inbox"))
        self.assertIn("COMMENT_CATEGORY_NOT_ENGAGED", url)
        self.assertIn("PARENT_ENTITY_CONTENT_TYPE_SHORT", url)

    def test_language_follows_the_comment_instead_of_the_channel(self):
        self.assertEqual(comments.detect_language("Muito bom, gostei demais do vídeo!"), "pt-BR")
        self.assertEqual(comments.detect_language("Great video, thanks for the work"), "en")
        self.assertEqual(comments.detect_language("Adorei a explicação, parabéns"), "pt-BR")
        self.assertEqual(comments.detect_language("Boa!", "pt-BR"), "pt-BR")
        self.assertEqual(comments.detect_language("Top!", "en"), "en")

    def test_english_comment_on_a_portuguese_channel_gets_an_english_reply(self):
        text = comments.reply_text("Great video, keep it up!", "@ana", "zaflas", "en", "pt-BR")
        self.assertIn("Thank you", text)
        self.assertIn("@ana", text)
        self.assertIn("🌱🚜", text)
        self.assertNotIn("Oi,", text)

    def test_portuguese_comment_gets_a_portuguese_reply_with_the_channel_voice(self):
        text = comments.reply_text("Muito bom, gostei do vídeo!", "@joao", "zanata", "pt-BR", "en")
        self.assertIn("Oi, @joao", text)
        self.assertIn("grandes livros", text)
        self.assertIn("😊", text)

    def test_criticism_is_answered_with_respect_and_no_attack(self):
        text = comments.reply_text("This video is boring and wrong", "@bob", "reflection", "en")
        self.assertIn("feedback seriously", text)
        self.assertIn("🙏", text)
        self.assertNotIn("boring", text.lower())

    def test_tone_does_not_fire_on_substrings_like_clients(self):
        self.assertEqual(comments.tone("We act differently with clients and friends"), "praise")
        self.assertEqual(comments.tone("Is that really true?"), "question")

    def test_journal_is_private_and_keyed_by_comment_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            channel = mock.Mock(slug="zanata")
            with mock.patch.object(config, "ROOT", root), mock.patch.object(config, "CHANNEL", channel):
                comments._record("abc123", {"state": "replied", "reply": "thanks"})
                self.assertEqual(comments._entry("abc123")["state"], "replied")
                path = comments._journal_path()
                self.assertEqual(path.parent.stat().st_mode & 0o077, 0)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["abc123"]["reply"], "thanks")


if __name__ == "__main__":
    unittest.main()
