import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tools.ytbot.commercial.whatsapp.sales import llm
from tools.ytbot.commercial.whatsapp.sales.rules import load

KEY = "oc_sk_fixture_not_a_real_key"
ANSWER = {"model": "deepseek-v4.1-flash",
          "choices": [{"finish_reason": "stop", "message": {"content": "{\"pong\": true}"}}],
          "usage": {"prompt_tokens": 45, "completion_tokens": 31,
                    "opencode": {"allowance": 3.042e-05}}}


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class OpenCodeGoTests(unittest.TestCase):
    settings = load().llm

    def test_request_follows_the_opencode_go_contract(self):
        client = llm.OpenCodeGo(self.settings, KEY)
        request = client.build_request([{"role": "user", "content": "oi"}], "zaflas-sales-L1")
        self.assertEqual(request.full_url,
                         "https://opencode.ai/inference/go/openai/v1/chat/completions")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["authorization"], f"Bearer {KEY}")
        self.assertEqual(headers["x-opencode-session"], "zaflas-sales-L1")
        self.assertTrue(headers["user-agent"].startswith("YoutubeBot-Sales/"))
        body = json.loads(request.data)
        self.assertEqual(body["model"], "deepseek-v4.1-flash")
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_response_content_tokens_and_cost_are_read(self):
        opener = lambda request, timeout: Response(json.dumps(ANSWER).encode())
        reply = llm.OpenCodeGo(self.settings, KEY, opener).complete([], "s")
        self.assertEqual(reply.content, "{\"pong\": true}")
        self.assertEqual((reply.input_tokens, reply.output_tokens), (45, 31))
        self.assertEqual(reply.cost_usd, 3.042e-05)

    def test_errors_never_carry_the_key(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "no", {},
                                         io.BytesIO(KEY.encode()))
        client = llm.OpenCodeGo(self.settings, KEY, opener)
        with self.assertRaises(llm.LlmError) as caught:
            client.complete([], "s")
        self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn(KEY, repr(client))

    def test_other_models_and_missing_keys_are_refused(self):
        with self.assertRaises(llm.LlmError):
            llm.OpenCodeGo({**self.settings, "model": "glm-5.3"}, KEY)
        with self.assertRaises(llm.LlmUnavailable):
            llm.OpenCodeGo(self.settings, "")

    def test_key_comes_from_the_environment_or_the_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "llm.env"
            path.write_text("OPENCODE_GO_API_KEY=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(llm.load_api_key("OPENCODE_GO_API_KEY", path), "from-file")
            with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "from-env"}):
                self.assertEqual(llm.load_api_key("OPENCODE_GO_API_KEY", path), "from-env")


if __name__ == "__main__":
    unittest.main()
