import unittest

from maps_support import listing
from tools.ytbot.commercial.maps import rules, score
from tools.ytbot.commercial.whatsapp.sales.store import dnc_hash, phone_key


class MapsScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules.load()

    def test_website_classes(self):
        self.assertEqual(score.website_class("", self.rules), "none")
        self.assertEqual(score.website_class("https://instagram.com/loja", self.rules),
                         "social-only")
        self.assertEqual(score.website_class("https://wa.me/5565900000001", self.rules),
                         "social-only")
        self.assertEqual(score.website_class("https://loja.business.site", self.rules),
                         "free-builder")
        self.assertEqual(score.website_class("https://www.ifood.com.br/loja", self.rules),
                         "marketplace")
        self.assertEqual(score.website_class("https://lojaexemplo.com.br", self.rules), "own")

    def test_phone_details_format_and_mobile_flag(self):
        mobile = score.phone_details("(65) 90000-0001")
        self.assertEqual((mobile["canonical"], mobile["mobile"], mobile["display"]),
                         ("5565900000001", True, "(65) 90000-0001"))
        landline = score.phone_details("+55 65 3333-0001")
        self.assertEqual((landline["canonical"], landline["mobile"], landline["display"]),
                         ("556533330001", False, "(65) 3333-0001"))
        self.assertIsNone(score.phone_details("1234"))
        self.assertIsNone(score.phone_details("(10) 90000-0001"))

    def test_tier_a_with_social_only_website(self):
        value = listing(website_field="https://instagram.com/clinicaexemplo")
        result = score.score_listing(value, self.rules)
        self.assertEqual(result["total"], 93)
        self.assertEqual(result["tier"], "A")
        self.assertEqual(result["class"], "social-only")
        self.assertEqual(score.note(value, result, self.rules),
                         "A 93 · social-only · 4.8 (134) · agendamento")

    def test_tier_b_and_tier_c(self):
        medium = listing(rating=4.2, reviews=40, last_review_days=100,
                         phone="(65) 3333-0001", unclaimed=False, photos=3,
                         photos_bucket="1-9", hours=False, website_field="")
        result = score.score_listing(medium, self.rules)
        self.assertEqual((result["total"], result["tier"]), (59, "B"))
        self.assertEqual(score.note(medium, result, self.rules),
                         "B 59 · none · 4.2 (40) · agendamento")

        weak = listing(rating=None, reviews=5, last_review_days=None, group="alimentacao",
                       phone="(65) 3333-0001", unclaimed=False, photos=0,
                       photos_bucket="0", hours=False, website_field="")
        result = score.score_listing(weak, self.rules)
        self.assertEqual((result["total"], result["tier"]), (25, "C"))

    def test_adjust_list_has_no_website_points_and_names_the_service(self):
        value = listing(outcome="site-not-on-maps", website_field="")
        result = score.score_listing(value, self.rules)
        self.assertEqual(result["points"]["website"], 0)
        self.assertEqual(result["class"], "site-not-on-maps")
        self.assertEqual(score.short_product(value, self.rules), "ajuste do Google Maps")
        self.assertEqual(score.suggested_product(value, self.rules), "Ajuste do Google Maps")

    def test_hard_exclusions_in_contract_order(self):
        closed = listing(status="Fechado permanentemente")
        self.assertEqual(score.exclusion_reason(closed, self.rules, set(), set()),
                         "fechado permanentemente")
        self.assertEqual(score.exclusion_reason(listing(phone=""), self.rules, set(), set()),
                         "sem telefone")
        self.assertEqual(score.exclusion_reason(listing(phone="1234"), self.rules, set(), set()),
                         "telefone inválido")
        self.assertEqual(score.exclusion_reason(listing(name="McDonald's"), self.rules, set(),
                                                set()), "rede ou franquia: mcdonald")
        self.assertEqual(score.exclusion_reason(listing(name="Prefeitura Municipal"),
                                                self.rules, set(), set()),
                         "categoria excluída: prefeitura")
        self.assertEqual(score.exclusion_reason(listing(outcome="has-site"), self.rules, set(),
                                                set()), "já tem site funcionando")

    def test_listing_from_another_city_is_excluded(self):
        value = listing(city="Sorriso", target_city="Sinop",
                        address="R. Central, 10 - Centro, Sorriso - MT")
        self.assertEqual(score.exclusion_reason(value, self.rules, set(), set()),
                         "fora da cidade: Sorriso")
        self.assertFalse(score.city_matches(value, "Sinop"))
        self.assertTrue(score.city_matches(value, "Sorriso"))
        stale = listing(city="Sinop", target_city="Sinop",
                        address="R. Central, 10 - Centro, Sorriso - MT")
        self.assertEqual(score.exclusion_reason(stale, self.rules, set(), set()),
                         "fora da cidade: Sorriso")

    def test_already_a_lead_and_do_not_contact(self):
        value = listing()
        key = phone_key(value["phone"])
        self.assertEqual(score.exclusion_reason(value, self.rules, {key}, set()),
                         "já é um lead")
        self.assertEqual(score.exclusion_reason(value, self.rules, set(),
                                                {dnc_hash(value["phone"])}),
                         "lista de não contatar")


if __name__ == "__main__":
    unittest.main()
