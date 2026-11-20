"""Unit tests for Mercado Livre affiliate product metadata helpers."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tools.ytbot.commercial.mercadolivre import products
from tools.ytbot.commercial.mercadolivre.products import (
    _extract_brand_name,
    _extract_seller_name,
    _select_product_ld,
)


class MercadoLivreProductHelpersTest(unittest.TestCase):
    def test_select_product_ld_accepts_list_and_single_product(self) -> None:
        scripts = [
            "not json",
            json.dumps({"@type": "BreadcrumbList"}),
            json.dumps([{"@type": "Organization"}, {"@type": "Product", "name": "Headset"}]),
        ]
        selected = _select_product_ld(scripts)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["name"], "Headset")

    def test_extract_brand_name_handles_string_dict_list_and_specs_fallback(self) -> None:
        self.assertEqual(_extract_brand_name({"brand": "Redragon"}), "Redragon")
        self.assertEqual(_extract_brand_name({"brand": {"name": "Kingston"}}), "Kingston")
        self.assertEqual(_extract_brand_name({"brand": [{"name": "LG"}]}), "LG")
        self.assertEqual(
            _extract_brand_name({}, [{"name": "Marca", "value": "Logitech"}]),
            "Logitech",
        )

    def test_extract_seller_name_handles_sold_by_and_official_store(self) -> None:
        self.assertEqual(
            _extract_seller_name(["Vendido por", "Loja Tech", "+5mil vendas"]),
            "Loja Tech",
        )
        self.assertEqual(
            _extract_seller_name(["Loja oficial", "Redragon", "", "+1 M vendas"]),
            "Loja oficial Redragon",
        )


class CapturedAtTest(unittest.TestCase):
    def test_save_writes_offset_aware_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "products.json"
            products.save(path, "ssd", [])
            captured_at = json.loads(path.read_text())["captured_at"]
        self.assertIsNotNone(datetime.fromisoformat(captured_at).utcoffset())


if __name__ == "__main__":
    unittest.main()
