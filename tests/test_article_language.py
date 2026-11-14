"""The actual article request follows channel language, independent of operator UI."""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from tools.ytbot import channels, chat


class ArticleLanguageContract(TestCase):
    def tearDown(self):
        channels.apply('fallem-prince')

    def test_outgoing_narration_request_has_the_profile_language(self):
        for slug, language in [('fallem-prince', 'English'), ('whispers-from-heaven', 'English'), ('zaflas', 'Brazilian Portuguese')]:
            with self.subTest(channel=slug), tempfile.TemporaryDirectory() as folder:
                channels.apply(slug)
                with patch.object(chat, 'send_text') as send, patch.object(chat, 'dismiss_notice'), patch.object(chat, 'wait_for_assistant'), patch.object(chat, 'copy_last', return_value='Narration text. '*200):
                    chat.generate_article(Mock(), 'A requested theme', Path(folder))
                request = send.call_args.args[1]
                self.assertIn('MANDATORY NARRATION LANGUAGE: '+language+'.', request)
                self.assertIn('regardless of the operator', request)
                self.assertIn('A requested theme', request)
