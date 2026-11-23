"""Evolution API transport: typed client and channel, no network in tests."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.ytbot.commercial.whatsapp import sender
from tools.ytbot.commercial.whatsapp.sales import evolution


class EvolutionClientTests(unittest.TestCase):
    def env(self, folder, key="chave-teste", port="8091"):
        path = Path(folder) / "evolution.env"
        path.write_text(f"AUTHENTICATION_API_KEY={key}\nEVOLUTION_PORT={port}\n"
                        "EVOLUTION_INSTANCE=zaflas\n", encoding="utf-8")
        return path

    def test_settings_read_the_private_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.env(folder)
            config = evolution.settings(path)
            self.assertEqual(config["key"], "chave-teste")
            self.assertEqual(config["base"], "http://127.0.0.1:8091")
            self.assertEqual(config["instance"], "zaflas")

    def test_missing_key_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.env(folder, key="")
            with self.assertRaises(evolution.EvolutionError):
                evolution.settings(path)

    def test_send_text_posts_the_number_and_text_with_the_apikey_header(self):
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"key": {"id": "abc"}}'

        def opener(request, timeout=None):
            calls.append(request)
            return Response()

        config = {"base": "http://127.0.0.1:8091", "key": "chave-teste",
                  "instance": "zaflas"}
        evolution.send_text("+55 (65) 99999-0001", "Bom dia", config, opener=opener)
        request = calls[0]
        self.assertTrue(request.full_url.endswith("/message/sendText/zaflas"))
        self.assertEqual(request.get_header("Apikey"), "chave-teste")
        body = request.data.decode()
        self.assertIn("5565999990001", body)
        self.assertIn("Bom dia", body)

    def test_http_error_becomes_a_typed_error(self):
        import urllib.error

        def opener(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        with self.assertRaises(evolution.EvolutionError):
            evolution.send_text("5565999990001", "Oi",
                                {"base": "http://x", "key": "k", "instance": "zaflas"},
                                opener=opener)


class EvolutionChannelTests(unittest.TestCase):
    def test_channel_sends_each_bubble_and_journals_them(self):
        sent = []

        def fake_send(phone, text, config, opener=None):
            sent.append((phone, text))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as folder:
            journal = Path(folder) / "journal.jsonl"
            channel = evolution.EvolutionChannel(
                {"base": "http://x", "key": "k", "instance": "zaflas"}, journal)
            items = [{"key": "k1", "text": "Bom dia", "delay": 1.0},
                     {"key": "k2", "text": "Tudo bem?", "delay": 1.0}]
            with mock.patch.object(evolution, "send_text", fake_send):
                results = channel.send({"phone": "+5565999990001", "name": "Loja"},
                                       items, {"kind": "sales-opening"})
            self.assertEqual([item["state"] for item in results], ["sent", "sent"])
            self.assertEqual([text for _, text in sent], ["Bom dia", "Tudo bem?"])
            states = [entry["state"] for entry in sender.read_journal(journal)]
            self.assertEqual(states, ["started", "sent", "started", "sent"])

    def test_channel_never_repeats_a_sent_key(self):
        calls = []

        def fake_send(phone, text, config, opener=None):
            calls.append(text)
            return {}

        with tempfile.TemporaryDirectory() as folder:
            journal = Path(folder) / "journal.jsonl"
            channel = evolution.EvolutionChannel(
                {"base": "http://x", "key": "k", "instance": "zaflas"}, journal)
            items = [{"key": "k1", "text": "Bom dia", "delay": 1.0}]
            with mock.patch.object(evolution, "send_text", fake_send):
                channel.send({"phone": "5565999990001", "name": "Loja"}, items, {})
                again = channel.send({"phone": "5565999990001", "name": "Loja"}, items, {})
            self.assertEqual(again[0]["state"], "duplicate")
            self.assertEqual(calls, ["Bom dia"])


if __name__ == "__main__":
    unittest.main()
