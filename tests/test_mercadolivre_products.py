"""Unit tests for Mercado Livre affiliate product metadata helpers."""

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
