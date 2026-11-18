import argparse
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from maps_support import listing
from tools.ytbot.commercial.maps import commands as maps_commands
from tools.ytbot.commercial.maps import record, render, rules
from tools.ytbot.commercial.whatsapp.sales import commands as sales_commands
from tools.ytbot.commercial.whatsapp.sales.store import CSV_FIELDS, SalesStore
from tools.ytbot.social.store import SocialStore

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=ZoneInfo("America/Cuiaba"))


class MapsRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "maps"
        self.store = record.RunStore(self.root)
        self.rules = rules.load()
        self.run = self.store.create("Lucas do Rio Verde", "MT", NOW)

    def tearDown(self):
        self.directory.cleanup()

    def test_run_directory_and_resume_identities(self):
        self.assertEqual(self.run.id, "lucas-do-rio-verde/2026-11-18")
        opening = {"state": "opening", "maps_url":
                   "https://www.google.com/maps/place/X/data=!4m2?entry=ttu"}
        self.run.append_listing(opening)
        value = listing()
        self.run.append_listing({**value, "state": "read"})
        self.assertIn(record.url_key(opening["maps_url"]), self.run.attempted())
        self.assertIn(record.identity(value), self.run.attempted())
        self.assertEqual(len(self.run.read_listings()), 1)
        self.assertEqual(self.store.daily_businesses(self.run.day), 1)
        self.assertEqual(self.store.resolve("lucas-do-rio-verde").id, self.run.id)
        with self.assertRaises(ValueError):
            self.store.resolve("../fora")

    def test_attention_marker_round_trip(self):
        entry = self.store.record_attention(self.run, "challenge", "desafio do Google",
                                           {"url": "https://www.google.com/maps"}, NOW)
        self.assertEqual(self.store.attention()["stage"], "challenge")
        self.assertEqual(entry["run"], self.run.id)
        self.store.clear_attention()
        self.assertIsNone(self.store.attention())

    def test_export_splits_candidates_adjustments_and_exclusions(self):
        candidate = listing()
        adjustment = listing(name="Marmoraria Silva", phone="(65) 3333-0001", group="casa",
                             category="Marmoraria", rating=4.8, reviews=134,
                             last_review_days=20, hours=False, photos=3, photos_bucket="1-9",
                             unclaimed=True, website_field="https://instagram.com/x",
                             outcome="site-not-on-maps")
        excluded = listing(name="Loja Com Site", phone="(65) 90000-0002", outcome="has-site")
        for value, outcome in ((candidate, "no-site"), (adjustment, "site-not-on-maps"),
                               (excluded, "has-site")):
            self.run.append_listing({**value, "state": "read"})
            self.run.append_check({"identity": record.identity(value), "outcome": outcome,
                                   "own_url": "https://marmorariasilva.com.br" if value is
                                   adjustment else ""})

        report = render.export_run(self.run, self.rules, NOW, set(), set())
        self.assertEqual((report["read"], report["candidates"], report["adjustments"],
                          report["excluded"]), (3, 1, 1, 1))
        with (self.run.path / "candidatos.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0]), list(CSV_FIELDS))
        self.assertEqual(rows[0]["name"], "Clínica Exemplo")
        self.assertEqual(rows[0]["phone"], "(65) 90000-0001")
        self.assertEqual(rows[0]["city"], "Lucas do Rio Verde")
        self.assertEqual(rows[0]["website"], "")
        self.assertTrue(rows[0]["note"].startswith("A 88 · none · 4.8 (134) · agendamento"))

        with (self.run.path / "ajuste-maps.csv").open(encoding="utf-8") as handle:
            adjust = list(csv.DictReader(handle))
        self.assertEqual(adjust[0]["name"], "Marmoraria Silva")
        self.assertEqual(adjust[0]["website"], "https://marmorariasilva.com.br")
        self.assertIn("ajuste do Google Maps", adjust[0]["note"])

        text = (self.run.path / "report.md").read_text(encoding="utf-8")
        self.assertIn("Empresas lidas | 3", text)
        self.assertIn("Loja Com Site", text)
        self.assertIn("já tem site funcionando", text)
        self.assertEqual((self.run.path / "report.md").stat().st_mode & 0o777, 0o600)

    def test_other_city_is_excluded_before_confirmation(self):
        self.run.append_listing({**listing(name="Odonto Sorriso", phone="(66) 90000-0002",
                                           city="Sorriso",
                                           address="R. Central, 10 - Centro, Sorriso - MT"),
                                 "state": "read"})
        report = render.export_run(self.run, self.rules, NOW, set(), set())
        self.assertEqual((report["excluded"], report["pending"]), (1, 0))
        text = (self.run.path / "report.md").read_text(encoding="utf-8")
        self.assertIn("fora da cidade: Sorriso", text)

    def test_pending_confirmation_is_not_exported(self):
        self.run.append_listing({**listing(), "state": "read"})
        report = render.export_run(self.run, self.rules, NOW, set(), set())
        self.assertEqual((report["pending"], report["candidates"]), (1, 0))

    def test_export_command_uses_the_private_maps_run(self):
        self.run.append_listing({**listing(), "state": "read"})
        self.run.append_check({"identity": record.identity(listing()), "outcome": "no-site"})
        store = SocialStore(self.root.parent)
        output = io.StringIO()
        with redirect_stdout(output):
            maps_commands.command_export(SimpleNamespace(run=self.run.id), lambda: store)
        result = json.loads(output.getvalue())
        self.assertEqual((result["run"], result["candidates"]), (self.run.id, 1))
        self.assertTrue(Path(result["candidatos_csv"]).is_file())


class MapsSalesImportTests(unittest.TestCase):
    def test_import_accepts_the_manual_maps_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "whatsapp"
            path = Path(directory) / "candidatos.csv"
            path.write_text(
                "name,phone,city,category,maps_url,website,note\n"
                "Clínica Exemplo,(65) 90000-0001,Lucas do Rio Verde,Clínica odontológica,"
                "https://maps.app.goo.gl/x,,A 88 · none\n",
                encoding="utf-8")
            store = SalesStore(base)
            report = store.import_csv(path, NOW, source="google-maps-manual")
            self.assertEqual(report["imported"], 1)
            lead = next(iter(store.leads().values()))
            self.assertEqual(lead["source"], "google-maps-manual")

    def test_cli_has_the_source_option(self):
        parser = argparse.ArgumentParser()
        actions = parser.add_subparsers(dest="action", required=True)
        sales_commands.add_parser(actions, lambda: None, lambda: None)
        args = parser.parse_args(["sales", "import", "--network", "whatsapp", "--csv", "x.csv",
                                  "--source", "google-maps-manual"])
        self.assertEqual(args.source, "google-maps-manual")
        default = parser.parse_args(["sales", "import", "--network", "whatsapp",
                                     "--csv", "x.csv"])
        self.assertEqual(default.source, "google-maps-reviewed")


if __name__ == "__main__":
    unittest.main()
