import unittest

from tools.ytbot.commercial.maps import rules, verify

NAME = "Clínica Exemplo"
CITY = "Lucas do Rio Verde"
PHONE = "(65) 90000-0001"


def fetched(url, status=200, title="", text="", error="", https=True, parking=False):
    return verify.Fetched(url, url, status, title, text, error, https, parking)


def fetcher(mapping):
    def run(url, _rules):
        return mapping.get(url, fetched(url, status=0, error="não resolveu",
                                        https=url.startswith("https://")))
    return run


class MapsVerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules.load()

    def test_own_site_found_in_search_but_missing_on_maps(self):
        results = [{"title": "Clínica Exemplo", "url": "https://clinicaexemplo.com.br/"},
                   {"title": "GuiaMais", "url": "https://www.guiamais.com.br/clinica"}]
        mapping = {
            "https://clinicaexemplo.com.br/": fetched(
                "https://clinicaexemplo.com.br/", title="Clínica Exemplo",
                text="Odontologia em Lucas do Rio Verde. (65) 90000-0001"),
        }
        result = verify.evaluate(NAME, CITY, PHONE, "https://instagram.com/clinicaexemplo",
                                 results, self.rules, fetcher(mapping))
        self.assertEqual(result["outcome"], "site-not-on-maps")
        self.assertEqual(result["maps_class"], "social-only")
        self.assertEqual(result["own_url"], "https://clinicaexemplo.com.br/")
        self.assertTrue(any(item["url"] == "https://clinicaexemplo.com.br/"
                            for item in result["evidence"]))

    def test_no_site_at_all(self):
        result = verify.evaluate(NAME, CITY, PHONE, "", [], self.rules, fetcher({}))
        self.assertEqual(result["outcome"], "no-site")
        self.assertEqual(len(result["evidence"]), 2)  # the two obvious domains

    def test_maps_site_working_is_has_site(self):
        website = "https://clinicaexemplo.com.br"
        mapping = {website: fetched(website, title="Clínica Exemplo",
                                    text="Lucas do Rio Verde")}
        result = verify.evaluate(NAME, CITY, PHONE, website, [], self.rules, fetcher(mapping))
        self.assertEqual(result["maps_class"], "own")
        self.assertEqual(result["outcome"], "has-site")

    def test_maps_site_down_is_weak(self):
        website = "https://clinicaexemplo.com.br"
        result = verify.evaluate(NAME, CITY, PHONE, website, [], self.rules, fetcher({}))
        self.assertEqual(result["outcome"], "weak-site")

    def test_http_only_site_is_weak(self):
        http = "http://marmorariasilva.com.br/"
        mapping = {http: fetched(http, title="Marmoraria Silva",
                                 text="Marmoraria em Lucas do Rio Verde", https=False)}
        result = verify.evaluate("Marmoraria Silva", CITY, "(65) 3333-0001", "",
                                 [{"title": "Marmoraria Silva", "url": http}],
                                 self.rules, fetcher(mapping))
        self.assertEqual(result["outcome"], "weak-site")

    def test_parking_page_is_weak(self):
        domain = "https://clinica-exemplo.com.br"
        mapping = {domain: fetched(domain, title="Clínica Exemplo",
                                   text="Domínio à venda", parking=True)}
        result = verify.evaluate(NAME, CITY, PHONE, "", [], self.rules, fetcher(mapping))
        self.assertEqual(result["outcome"], "weak-site")

    def test_directories_are_ignored(self):
        results = [{"title": "Clínica Exemplo", "url": "https://www.guiamais.com.br/x"},
                   {"title": "Clínica Exemplo", "url": "https://cadeodentista.com.br/x"},
                   {"title": "Clínica Exemplo", "url": "https://magicpin.com/brazil/x"}]
        result = verify.evaluate(NAME, CITY, PHONE, "", results, self.rules, fetcher({}))
        self.assertEqual(result["outcome"], "no-site")
        self.assertFalse(any(item["source"] == "search" for item in result["evidence"]))

    def test_domain_probe_falls_back_to_http(self):
        https = "https://clinica-exemplo.com.br"
        http = "http://clinica-exemplo.com.br"
        mapping = {http: fetched(http, title="Clínica Exemplo", https=False)}
        result = verify.probe_domain(https, self.rules, fetcher(mapping))
        self.assertEqual((result.status, result.https), (200, False))


if __name__ == "__main__":
    unittest.main()
