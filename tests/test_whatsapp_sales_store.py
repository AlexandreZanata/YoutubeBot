import tempfile
import unittest
from pathlib import Path

from sales_fixtures import MONDAY, PHONES, lead_rows, write_csv
from tools.ytbot.commercial.whatsapp.sales import store as sales_store


class SalesStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name) / "whatsapp"
        self.store = sales_store.SalesStore(self.base)

    def tearDown(self):
        self.directory.cleanup()

    def test_brazilian_numbers_are_canonical(self):
        self.assertEqual(sales_store.canonical_phone("(65) 90000-0001"), "5565900000001")
        self.assertEqual(sales_store.canonical_phone("+55 65 3000-0001"), "556530000001")
        self.assertIsNone(sales_store.canonical_phone("(10) 90000-0001"))
        self.assertIsNone(sales_store.canonical_phone("12345"))
        self.assertEqual(sales_store.phone_key("+55 65 9 0000-0001"),
                         sales_store.phone_key("+55 65 0000-0001"))

    def test_import_keeps_reviewed_rows_and_reports_the_rest(self):
        rows = lead_rows(2) + [
            {"name": "Com site", "phone": PHONES[5], "website": "https://exemplo.com.br"},
            {"name": "Sem número", "phone": "123"},
            {"name": "Link estranho", "phone": PHONES[6], "maps_url": "https://exemplo.com/x"},
            {"name": "Repetida", "phone": PHONES[0]},
        ]
        report = self.store.import_csv(write_csv(Path(self.directory.name) / "l.csv", rows),
                                       MONDAY)
        self.assertEqual(report["imported"], 2)
        self.assertEqual(report["duplicates"], 1)
        self.assertEqual([item["line"] for item in report["rejected"]], [4, 5, 6])
        lead = next(iter(self.store.leads().values()))
        self.assertEqual((lead["state"], lead["source"]), ("new", "google-maps-reviewed"))
        self.assertEqual(self.store.leads_path.stat().st_mode & 0o777, 0o600)

    def test_do_not_contact_survives_and_blocks_reimport(self):
        self.store.add_dnc("5565900000002", "refusal", MONDAY)
        report = self.store.import_csv(write_csv(Path(self.directory.name) / "l.csv",
                                                 lead_rows(2)), MONDAY)
        self.assertEqual((report["imported"], report["do_not_contact"]), (1, 1))
        stored = self.store.dnc_path.read_text(encoding="utf-8")
        self.assertNotIn("900000002", stored)

    def test_chat_titles_find_leads_by_number_or_name(self):
        self.store.import_csv(write_csv(Path(self.directory.name) / "l.csv", lead_rows(2)), MONDAY)
        self.assertEqual(self.store.find_lead("+55 65 90000-0001")["name"], "Empresa 0")
        self.assertEqual(self.store.find_lead("Empresa 1")["name"], "Empresa 1")
        self.assertIsNone(self.store.find_lead("Mãe"))

    def test_memory_appends_in_order(self):
        self.store.remember("L1", {"dir": "out", "text": "Bom dia"})
        self.store.remember("L1", {"dir": "in", "text": "Bom dia!"})
        self.assertEqual([entry["dir"] for entry in self.store.history("L1")], ["out", "in"])

    def test_only_one_run_holds_the_lock(self):
        self.assertTrue(self.store.acquire())
        self.store.lock_path.write_text("1", encoding="utf-8")  # pid 1 is always alive
        self.assertFalse(self.store.acquire())
        self.store.lock_path.unlink()
        self.assertTrue(self.store.acquire())
        self.store.release()
        self.assertFalse(self.store.lock_path.exists())


if __name__ == "__main__":
    unittest.main()
