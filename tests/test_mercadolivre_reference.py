import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.ytbot.commercial import commands, reference


SAMPLE_REFERENCE_PAYLOAD = {
    "generatedAt": "2026-11-16T16:40:00Z",
    "cacheGeneration": 4,
    "totalProducts": 2,
    "items": [
        {
            "productId": "MLB63816534",
            "slug": "delux-m900pro-mlb63816534",
            "title": "Delux M900pro Mouse Gamer Sem Fio 8000Hz Paw3395",
            "brand": "Delux",
            "model": "M900PRO",
            "exactVariant": "Preto · 8000Hz",
            "categorySlug": "hardware-e-perifericos",
            "subcategorySlug": "mouses-e-teclados",
            "sellerName": "Delux Official",
            "state": "approved",
            "currentPriceCents": 29986,
            "pixPriceCents": 29986,
            "referencePriceCents": 39990,
            "discountPct": 25,
            "lowestPrice30dCents": 27990,
            "averagePrice30dCents": 31000,
            "highestPrice30dCents": 34990,
            "previousPriceCents": 32990,
            "priceDeltaCents": -3004,
            "priceDeltaPct": -9,
            "observationCount": 3,
            "priceTrend": "down",
            "priceLevel": "good_price",
            "priceLevelLabel": "Bom preço",
            "observedAt": "2026-11-16T16:40:00Z",
            "observedAtMs": 1763311200000,
            "officialAffiliateUrl": "https://meli.la/31tuNW3",
            "shortSummary": "Queda para R$ 299,86 (-9% vs anterior R$ 329,90)",
            "telegramPublishedCount": 1,
            "telegramLastStatus": "published",
        },
        {
            "productId": "MLB72674962",
            "slug": "mouse-blackbom-mlb72674962",
            "title": "Mouse Recarregavel Bluetooth Wireless Ergonomico Blackbom",
            "brand": "Blackbom",
            "exactVariant": "Sem fio",
            "categorySlug": "hardware-e-perifericos",
            "subcategorySlug": "mouses-e-teclados",
            "sellerName": "Loja Blackbom",
            "state": "approved",
            "currentPriceCents": 2099,
            "pixPriceCents": 2099,
            "discountPct": 10,
            "lowestPrice30dCents": 2099,
            "averagePrice30dCents": 2099,
            "highestPrice30dCents": 2099,
            "priceDeltaCents": 0,
            "priceDeltaPct": 0,
            "observationCount": 1,
            "priceTrend": "new",
            "priceLevel": "lowest_price",
            "priceLevelLabel": "Menor preço (30d)",
            "observedAt": "2026-11-16T16:40:00Z",
            "observedAtMs": 1763311200000,
            "officialAffiliateUrl": "https://meli.la/2ZpQqwX",
            "shortSummary": "Primeira captura em R$ 20,99",
            "telegramPublishedCount": 0,
            "telegramLastStatus": "queued",
        },
    ],
}


class MercadoLivreReferenceTests(unittest.TestCase):
    def test_sqlite_index_rebuilds_only_on_change_and_queries_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "vps-reference.json"
            db_path = root / "vps-reference.sqlite3"
            json_path.write_text(json.dumps(SAMPLE_REFERENCE_PAYLOAD), encoding="utf-8")

            self.assertTrue(reference.ensure_local_reference_db(json_path, db_path))
            self.assertFalse(reference.ensure_local_reference_db(json_path, db_path))

            by_query = reference.query_reference_db(db_path, query="delux paw3395", limit=10)
            self.assertEqual(by_query["overview"]["total_products"], 2)
            self.assertEqual(by_query["overview"]["price_drop_count"], 1)
            self.assertEqual(by_query["total_matches"], 1)
            self.assertEqual(by_query["items"][0]["product_id"], "MLB63816534")
            self.assertLess(by_query["overview"]["query_ms"], 250.0)

            by_id = reference.query_reference_db(db_path, product_id="mlb72674962")
            self.assertEqual(by_id["total_matches"], 1)
            self.assertEqual(by_id["items"][0]["price_brl"], "R$ 20,99")

            by_trend = reference.query_reference_db(db_path, trend="down")
            self.assertEqual([item["product_id"] for item in by_trend["items"]], ["MLB63816534"])

    def test_compare_products_flags_new_drop_increase_and_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "vps-reference.json"
            db_path = root / "vps-reference.sqlite3"
            json_path.write_text(json.dumps(SAMPLE_REFERENCE_PAYLOAD), encoding="utf-8")
            reference.ensure_local_reference_db(json_path, db_path)
            ref_by_id = reference.load_reference_index_by_id(db_path)

            rows = [
                {"product_id": "MLB63816534", "title": "Delux M900pro", "price": 249.90},
                {"product_id": "MLB72674962", "title": "Blackbom", "price": 20.99},
                {"product_id": "MLB99999999", "title": "Teclado Novo", "price": "189,90"},
            ]
            comparisons = reference.compare_products_with_reference(rows, ref_by_id)
            by_pid = {c["product_id"]: c for c in comparisons}
            self.assertEqual(by_pid["MLB63816534"]["status"], "price_drop")
            self.assertLess(by_pid["MLB63816534"]["delta_cents"], 0)
            self.assertIn("BAIXOU", by_pid["MLB63816534"]["comparison_summary"])

            self.assertEqual(by_pid["MLB72674962"]["status"], "unchanged")
            self.assertEqual(by_pid["MLB99999999"]["status"], "new")

    def test_cli_reference_command_reads_local_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            net_dir = root / "mercadolivre"
            net_dir.mkdir(parents=True, exist_ok=True)
            json_path = net_dir / "vps-reference.json"
            json_path.write_text(json.dumps(SAMPLE_REFERENCE_PAYLOAD), encoding="utf-8")

            class _FakeStore:
                def network(self, name: str) -> Path:
                    self.last_name = name
                    return net_dir

            out = io.StringIO()
            args = argparse.Namespace(
                network="mercadolivre",
                refresh=False,
                query="blackbom",
                product_id="",
                category="",
                trend="",
                limit=5,
            )
            with patch.object(commands, "_store", return_value=_FakeStore()):
                with redirect_stdout(out):
                    commands.command_reference(args)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["total_matches"], 1)
            self.assertEqual(payload["items"][0]["product_id"], "MLB72674962")
