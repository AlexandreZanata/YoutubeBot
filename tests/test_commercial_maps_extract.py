import unittest

from maps_support import fixture
from tools.ytbot.commercial.maps import extract, html, rules


class MapsHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules.load()

    def test_every_configured_selector_is_supported(self):
        for name, selectors in self.rules.selectors.items():
            for selector in selectors:
                with self.subTest(name=name, selector=selector):
                    self.assertTrue(html.compile_selector(selector))

    def test_listing_without_site_reads_every_public_field(self):
        value = extract.parse_listing(fixture("listing_sem_site.html"),
                                      "https://www.google.com/maps/place/Clinica+Exemplo",
                                      self.rules)
        self.assertEqual(value["name"], "Clínica Exemplo")
        self.assertEqual(value["category"], "Clínica odontológica")
        self.assertEqual(value["address"],
                         "Av. Brasil, 123 - Centro, Lucas do Rio Verde - MT, 78455-000")
        self.assertEqual(value["city"], "Lucas do Rio Verde")
        self.assertEqual(value["phone"], "(65) 90000-0001")
        self.assertEqual(value["website_field"], "")
        self.assertEqual(value["rating"], 4.8)
        self.assertEqual(value["reviews"], 134)
        self.assertTrue(value["hours"])
        self.assertEqual((value["photos"], value["photos_bucket"]), (24, "10+"))
        self.assertTrue(value["unclaimed"])
        self.assertEqual(value["status"], "")
        self.assertIn("https://instagram.com/clinicaexemplo", value["social"])
        self.assertIn("https://www.facebook.com/clinicaexemplo", value["social"])

    def test_listing_with_site_and_no_hours(self):
        value = extract.parse_listing(fixture("listing_com_site.html"),
                                      "https://www.google.com/maps/place/Marmoraria",
                                      self.rules)
        self.assertEqual(value["website_field"], "https://marmorariasilva.com.br")
        self.assertEqual(value["rating"], 4.6)
        self.assertEqual(value["reviews"], 41)
        self.assertFalse(value["hours"])
        self.assertEqual(value["photos_bucket"], "1-9")
        self.assertFalse(value["unclaimed"])

    def test_closed_listing_is_recorded(self):
        value = extract.parse_listing(fixture("listing_fechado.html"),
                                      "https://www.google.com/maps/place/Loja",
                                      self.rules)
        self.assertEqual(value["status"], "Fechado permanentemente")

    def test_feed_links_are_absolute_and_deduplicated(self):
        links = extract.parse_place_links(fixture("feed.html"), self.rules)
        self.assertEqual(len(links), 3)
        self.assertTrue(all(link.startswith("https://") for link in links))
        self.assertEqual(links[0],
                         "https://www.google.com/maps/place/"
                         "Cl%C3%ADnica+Exemplo/data=!4m2!3m1!1s0x0:0x1?entry=ttu")
        self.assertTrue(links[-1].endswith("/maps/place/Barbearia+Teste"))

    def test_search_results_unwrap_google_redirects(self):
        results = extract.parse_search_results(fixture("search_results.html"), self.rules)
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["url"], "https://clinicaexemplo.com.br/")
        self.assertEqual(results[1]["url"],
                         "https://www.guiamais.com.br/lucas-do-rio-verde-mt/clinica-exemplo")

    def test_challenge_wins_over_every_other_state(self):
        page = fixture("challenge.html")
        self.assertTrue(extract.detect_challenge(page, "https://www.google.com/maps", self.rules))
        self.assertEqual(extract.layout(page, self.rules), "unknown")

    def test_search_states(self):
        page = fixture("search_results.html")
        self.assertEqual(extract.layout(page, self.rules), "google-search")
        self.assertFalse(extract.detect_challenge(page, "https://www.google.com/search?q=x",
                                                  self.rules))
        self.assertTrue(extract.no_search_results(fixture("search_no_results.html"), self.rules))
        google = '<h1>Um painel de conhecimento</h1>'
        self.assertEqual(extract.layout(google, self.rules,
                                        "https://www.google.com/search?q=x"), "unknown")
        self.assertEqual(extract.layout(google, self.rules,
                                        "https://www.google.com/maps/place/X"), "maps")

    def test_login_state_uses_the_visible_account_or_login_marker(self):
        logged_in = '<div role="main"><button aria-label="Conta do Google: Ana">A</button></div>'
        logged_out = '<a href="https://accounts.google.com/ServiceLogin">Fazer login</a>'
        self.assertEqual(extract.login_state(logged_in, self.rules), "logged-in")
        self.assertEqual(extract.login_state(logged_out, self.rules), "login-required")
        self.assertEqual(extract.login_state("<p>nada</p>", self.rules), "unknown")

    def test_google_results_shell_without_links_is_recognized(self):
        page = '<html><body>Resultados da pesquisa <h1>Visão geral</h1></body></html>'
        self.assertTrue(extract.search_page(page, self.rules))
        self.assertEqual(extract.parse_search_results(page, self.rules), [])

    def test_review_age_reads_the_freshest_relative_date(self):
        self.assertEqual(extract.review_age_days("há 2 semanas"), 14)
        self.assertEqual(extract.review_age_days("há um mês"), 30)
        self.assertEqual(extract.review_age_days("há 1 ano"), 365)
        self.assertEqual(extract.review_age_days("um mês atrás"), 30)
        self.assertEqual(extract.review_age_days("2 meses atrás"), 60)
        self.assertEqual(extract.review_age_days("5 meses atrás"), 150)
        self.assertEqual(extract.review_age_days("hoje"), 0)
        self.assertEqual(extract.review_age_days("ontem"), 1)
        self.assertIsNone(extract.review_age_days("sem data"))
        text = "há 3 meses · há 2 dias · há um ano"
        self.assertEqual(extract.newest_review_age(text), 2)
        self.assertEqual(extract.newest_review_age("um mês atrás · 2 meses atrás · 3 dias atrás"), 3)

    def test_photos_presence_is_a_conservative_bucket(self):
        page = ('<div role="main"><h1>Clínica Teste</h1><div>Ver fotos</div></div>')
        value = extract.parse_listing(page, "https://www.google.com/maps/place/X",
                                      self.rules)
        self.assertEqual((value["photos"], value["photos_bucket"]), (1, "1-9"))


if __name__ == "__main__":
    unittest.main()
