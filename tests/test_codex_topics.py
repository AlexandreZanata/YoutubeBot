"""Automatic topic suggestions keep ChatGPT limited to article and audio work."""
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from tools.ytbot import codex_media, config, topics


class CodexTopicContracts(TestCase):
    def test_topic_request_is_bounded_text_only_and_keeps_channel_rules(self):
        candidates = ["Why Do Forgotten Dreams Still Shape Our Decisions?", "Can Silence Change the Way We Remember?", "Why Does Time Feel Different When Alone?"]
        with patch.object(config, 'prompt', return_value='Channel rules with {titles}'), patch.object(codex_media, '_execute', return_value={'topics': candidates}) as execute:
            self.assertEqual(codex_media.generate_topics(3, ['Existing narrative']), candidates)
        self.assertFalse(execute.call_args.kwargs['images'])
        self.assertIn('Channel rules', execute.call_args.args[2])
        self.assertIn('Existing narrative', execute.call_args.args[2])
        self.assertIn('Use no tools', execute.call_args.args[2])
        with self.assertRaises(ValueError):
            codex_media.generate_topics(13, [])
        with patch.object(codex_media, '_execute', return_value={'topics': ['Repeated topic', 'repeated topic']}):
            with self.assertRaises(ValueError):
                codex_media.generate_topics(2, [])

    def test_owner_queue_precedes_any_model_suggestion(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = Path(folder)/'topics.txt'
            queue.write_text('Why Does Silence Make Our Memories Feel Louder?\n')
            with patch.object(config, 'TOPICS', queue), patch.object(topics.logic, 'load_catalog', return_value=[]), patch.object(codex_media, 'generate_topics') as codex, patch.object(topics.chat, 'generate_topics') as chat:
                result = topics.prepare_topics(Mock(), 1)
            self.assertEqual(len(result), 1)
            codex.assert_not_called()
            chat.assert_not_called()

    def test_codex_candidates_still_pass_existing_novelty_filter(self):
        old = 'Why Does Silence Make Our Memories Feel Louder?'
        new = 'Can Time Exist Without Anyone to Experience It?'
        context = Mock()
        with patch.object(topics, '_read_queued_topics', return_value=[]), patch.object(topics.logic, 'load_catalog', return_value=[{'title': old}]), patch.object(codex_media, 'available', return_value=True), patch.object(codex_media, 'generate_topics', return_value=[old, new, 'What Happens When a Dream Becomes a Memory?']), patch.object(topics.chat, 'generate_topics') as chat:
            self.assertEqual(topics.prepare_topics(context, 1), [new])
        chat.assert_not_called()
        context.new_page.assert_not_called()

    def test_installed_codex_failure_never_falls_back_to_chatgpt_topics(self):
        with patch.object(topics, '_read_queued_topics', return_value=[]), patch.object(topics.logic, 'load_catalog', return_value=[]), patch.object(codex_media, 'available', return_value=True), patch.object(codex_media, 'generate_topics', side_effect=RuntimeError('fenced')), patch.object(topics.chat, 'generate_topics') as chat:
            with self.assertRaisesRegex(RuntimeError, 'fenced'):
                topics.prepare_topics(Mock(), 1)
        chat.assert_not_called()
