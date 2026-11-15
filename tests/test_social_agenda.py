import json
import tempfile
import unittest
from pathlib import Path

from tools.ytbot.social import agenda
from tools.ytbot.social.store import SocialStore
from tools.ytbot.social.x import publish


def item(**overrides):
    value = {
        "id": "P01",
        "date": "2026-11-16",
        "product": "Abastevo",
        "format": "text",
        "text": "Compare com a mesma unidade. Veja a calculadora: {url}",
        "destination": "https://abastevo.com.br/ferramentas/etanol-ou-gasolina/",
        "campaign": "abastevo_utilidade_202611",
        "content": "p01_text",
        "audience": "Motorista",
        "objective": "Entender custo",
        "cta": "Veja a calculadora",
        "metric": "Calculo concluido",
        "conversation": "Ler uma duvida",
        "image": None,
        "alt_text": "",
        "status": "approved",
    }
    value.update(overrides)
    return value


class AgendaTests(unittest.TestCase):
    def load(self, items):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "agenda.json"
        path.write_text(json.dumps({"schema": 1, "items": items}), encoding="utf-8")
        return agenda.load_agenda(path)

    def test_tracked_url_keeps_language_and_adds_utm(self):
        value = agenda.tracked_url(item(destination="https://sorrifit.com/?idioma=pt",
                                        campaign="sorrifit_registro_202611"))
        self.assertIn("idioma=pt", value)
        self.assertIn("utm_source=x", value)
        self.assertIn("utm_campaign=sorrifit_registro_202611", value)
        self.assertIn("utm_content=p01_text", value)

    def test_text_is_rendered_and_weighted_for_x(self):
        value = item()
        text = agenda.render_text(value)
        self.assertIn("utm_source=x", text)
        self.assertNotIn("{url}", text)
        self.assertEqual(agenda.x_length("a" * 100 + " https://example.com/"), 124)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(agenda.AgendaError):
            self.load([item(), item()])

    def test_text_requires_the_url_placeholder(self):
        with self.assertRaises(agenda.AgendaError):
            self.load([item(text="Sem link")])

    def test_only_known_formats_and_statuses_are_accepted(self):
        with self.assertRaises(agenda.AgendaError):
            self.load([item(format="audio")])
        with self.assertRaises(agenda.AgendaError):
            self.load([item(status="published")])

    def test_journal_blocks_a_started_or_posted_item(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SocialStore(Path(directory) / "social")
            digest = agenda.text_hash(agenda.render_text(item()))
            self.assertIsNone(agenda.already_posted(store, "x", "P01", digest))
            agenda.save_post(store, "x", "P01", {"state": "started", "text_sha256": digest})
            found = agenda.already_posted(store, "x", "P01", digest)
            self.assertEqual(found["state"], "started")

    def test_reply_quota_counts_only_posted_replies_for_the_owner_post(self):
        self.assertEqual(publish.REPLIES_PER_POST, 5)
        with tempfile.TemporaryDirectory() as directory:
            store = SocialStore(Path(directory) / "social")
            agenda.save_post(store, "x", "P01", {"state": "posted", "text_sha256": "a"})
            publish._save_reply(store, "x", "111", {"state": "posted", "for_post": "P01"})
            publish._save_reply(store, "x", "222", {"state": "started", "for_post": "P01"})
            publish._save_reply(store, "x", "333", {"state": "posted", "for_post": ""})
            self.assertEqual(publish.reply_counts(store, "x"), {"P01": 1})

    def test_same_text_under_another_id_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SocialStore(Path(directory) / "social")
            digest = agenda.text_hash(agenda.render_text(item()))
            agenda.save_post(store, "x", "P01", {"state": "posted", "text_sha256": digest})
            found = agenda.already_posted(store, "x", "P99", digest)
            self.assertEqual(found["id"], "P01")


if __name__ == "__main__":
    unittest.main()
