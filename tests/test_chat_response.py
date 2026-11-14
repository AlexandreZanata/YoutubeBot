"""Response identity and formatting without clipboard access or live accounts."""
from unittest import TestCase
from unittest.mock import Mock
from tools.ytbot import chat


class ChatResponseContracts(TestCase):
    def test_latest_response_preserves_metadata_and_does_not_read_clipboard(self):
        page = Mock()
        page.locator.return_value.inner_text.return_value = (
            "Sidebar\nYou said:\nOld request\nChatGPT said:\nOld response\n"
            "You said:\nMetadata request\nChatGPT said:\n"
            "TITLE OPTIONS:\n1. A Title\n\n#mind #identity\nTAGS: mind, identity\n"
            "ChatGPT can make mistakes. Check important info.\nLatest response"
        )
        self.assertEqual(chat.copy_last(page),
                         "TITLE OPTIONS:\n1. A Title\n\n#mind #identity\nTAGS: mind, identity")
        page.evaluate.assert_not_called()
        page.keyboard.assert_not_called()

    def test_article_cleaning_keeps_only_narration_from_the_latest_response(self):
        page = Mock()
        page.locator.return_value.inner_text.return_value = (
            "You said:\nTheme: A topic\nChatGPT said:\n"
            "**Imagine this** — a thought becomes your own.\n\nSecond paragraph.\n"
            "Simple Deep Dive is now a plugin\nUse plugin\nThinking effort\nMedium"
        )
        self.assertEqual(chat.extract_assistant_text(page),
                         "Imagine this , a thought becomes your own.\n\nSecond paragraph.")
