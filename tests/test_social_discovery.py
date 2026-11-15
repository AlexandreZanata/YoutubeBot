import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tools.ytbot.social import discovery
from tools.ytbot.social.x import publish


def row(**overrides):
    value = {
        "text": "A gasolina subiu e não sei se compensa etanol. Como vocês calculam o custo por km?",
        "published_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "href": "/motorista/status/123456789",
        "author_text": "Motorista\n@motorista",
        "like_label": "12 curtidas",
        "body": "Motorista @motorista",
    }
    value.update(overrides)
    return value


class DiscoveryTests(unittest.TestCase):
    def test_parse_extracts_status_author_and_metrics(self):
        item = discovery._parse(row())
        self.assertEqual(item["status_id"], "123456789")
        self.assertEqual(item["author"], "motorista")
        self.assertEqual(item["url"], "https://x.com/motorista/status/123456789")
        self.assertEqual(item["likes"], 12)

    def test_parse_skips_posts_without_text(self):
        self.assertIsNone(discovery._parse(row(text="")))

    def test_score_requires_product_terms(self):
        spec = discovery.PRODUCTS["abastevo"]
        unrelated = discovery._parse(row(text="Como vocês fazem essa conta no dia a dia?"))
        unrelated["published_at"] = datetime.now(timezone.utc).isoformat()
        self.assertIsNone(discovery.score(unrelated, spec))
        item = discovery._parse(row(text="Gasolina ou etanol? Como vocês calculam o custo por km?"))
        item["published_at"] = datetime.now(timezone.utc).isoformat()
        self.assertGreater(discovery.score(item, spec), 0)

    def test_political_post_is_excluded(self):
        spec = discovery.PRODUCTS["abastevo"]
        item = discovery._parse(row(text="O governo e a gasolina: mais um imposto. O que acham do preço?"))
        item["published_at"] = datetime.now(timezone.utc).isoformat()
        self.assertIsNone(discovery.score(item, spec))

    def test_curate_deduplicates_and_sorts(self):
        item = discovery._parse(row())
        item["published_at"] = datetime.now(timezone.utc).isoformat()
        with patch.object(discovery, "search", return_value=[item]):
            rows = discovery.curate(None, "abastevo", days=7, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status_id"], "123456789")

    def test_project_link_guard_accepts_only_owner_domains(self):
        self.assertTrue(publish._has_project_link(
            "Veja o guia: https://abastevo.com.br/guias/como-e-formado-o-preco-da-gasolina/"))
        self.assertTrue(publish._has_project_link(
            "Veja o repositório: https://github.com/open-data-brazil/br-validators"))
        self.assertFalse(publish._has_project_link("Veja: https://example.com/qualquer-coisa"))

    def test_every_product_has_queries_terms_and_a_link(self):
        for name, spec in discovery.PRODUCTS.items():
            self.assertTrue(spec["queries"], name)
            self.assertTrue(spec["terms"], name)
            self.assertTrue(spec["link"].startswith("https://"), name)
            self.assertTrue(spec["campaign"], name)


if __name__ == "__main__":
    unittest.main()
