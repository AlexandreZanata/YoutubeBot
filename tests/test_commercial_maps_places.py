import base64
import dataclasses
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.ytbot.commercial.maps import places, rules, websearch


def place(**overrides):
    value = {
        "id": "abc123",
        "displayName": {"text": "Agro Exemplo"},
        "primaryTypeDisplayName": {"text": "Loja de insumos agrícolas"},
        "formattedAddress": "Av. Exemplo, 100, Lucas do Rio Verde - MT, 78455-000",
        "nationalPhoneNumber": "(65) 99224-9976",
        "websiteUri": "",
        "rating": 4.7,
        "userRatingCount": 42,
        "regularOpeningHours": {"periods": []},
        "photos": [],
        "businessStatus": "OPERATIONAL",
        "googleMapsUri": "https://maps.google.com/?cid=1",
    }
    value.update(overrides)
    return value


class MapsPlacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules.load()
        cls.now = datetime(2026, 11, 19, 9, 0, tzinfo=ZoneInfo("America/Cuiaba"))

    def test_listing_maps_the_api_fields_to_the_read_schema(self):
        value = places.listing(place(), "Lucas do Rio Verde", "MT", "agro",
                               "revenda em Lucas do Rio Verde - MT", self.rules, self.now)
        self.assertEqual(value["name"], "Agro Exemplo")
        self.assertEqual(value["category"], "Loja de insumos agrícolas")
        self.assertEqual(value["phone"], "(65) 99224-9976")
        self.assertEqual(value["rating"], 4.7)
        self.assertEqual(value["reviews"], 42)
        self.assertTrue(value["hours"])
        self.assertEqual(value["status"], "")
        self.assertEqual(value["photos_bucket"], "0")
        self.assertEqual(value["source"], "places")
        self.assertEqual(value["place_id"], "abc123")
        self.assertIsNone(value["last_review_days"])

    def test_social_website_becomes_social_only_input(self):
        value = places.listing(place(websiteUri="https://instagram.com/agroexemplo"),
                               "Lucas do Rio Verde", "MT", "agro", "q", self.rules, self.now)
        self.assertEqual(value["social"], ["https://instagram.com/agroexemplo"])

    def test_ten_photos_and_closed_status(self):
        photos = [{"name": f"places/abc/photos/{index}"} for index in range(10)]
        value = places.listing(place(photos=photos, businessStatus="CLOSED_PERMANENTLY"),
                               "Lucas do Rio Verde", "MT", "agro", "q", self.rules, self.now)
        self.assertEqual(value["photos"], 10)
        self.assertEqual(value["photos_bucket"], "10+")
        self.assertEqual(value["status"], "Fechado permanentemente")

    def test_search_places_follows_the_page_token(self):
        calls = []

        def poster(body, key, current_rules):
            calls.append(body)
            if len(calls) == 1:
                return {"places": [place(id="1")], "nextPageToken": "token-2"}
            return {"places": [place(id="2")]}

        found = places.search_places("termo", self.rules, key="k", poster=poster)
        self.assertEqual([item["id"] for item in found], ["1", "2"])
        self.assertEqual(calls[1]["pageToken"], "token-2")
        self.assertEqual(calls[0]["textQuery"], "termo")

    def test_missing_key_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = dict(self.rules.places)
            settings.update({"key_file": str(Path(folder) / "absent.key"), "key_env": ""})
            with self.assertRaises(places.PlacesError):
                places.api_key(dataclasses.replace(self.rules, places=settings))

    def test_ddg_redirect_links_are_decoded(self):
        html = ('<a rel="nofollow" href="//duckduckgo.com/l/?uddg='
                'https%3A%2F%2Fexemplo.com.br%2Fcontato&amp;rut=x" class="result-link">x</a>')
        self.assertEqual([item["url"] for item in websearch._ddg_results(html)],
                         ["https://exemplo.com.br/contato"])

    def test_bing_redirect_links_are_decoded(self):
        target = "https://exemplo.com.br"
        payload = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        html = f'<h2><a href="https://www.bing.com/ck/a?x=1&amp;u=a1{payload}">x</a></h2>'
        self.assertEqual([item["url"] for item in websearch._bing_results(html)], [target])

    def test_search_keeps_only_external_links(self):
        html = ('<a rel="nofollow" href="//duckduckgo.com/l/?uddg='
                'https%3A%2F%2Floja.com.br%2F" class="result-link">x</a>'
                '<a href="https://www.bing.com/ck/a?u=a1zz">b</a>')
        results = websearch._clean(websearch._ddg_results(html))
        self.assertEqual([item["url"] for item in results], ["https://loja.com.br/"])


if __name__ == "__main__":
    unittest.main()
