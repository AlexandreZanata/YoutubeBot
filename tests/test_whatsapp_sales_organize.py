import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sales_fixtures import MONDAY, PHONES, Clock, FakeChannel, write_csv
from tools.ytbot.commercial.whatsapp.sales import central, dossier
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore, category_slug


def rows(*categories):
    return [{"name": f"Empresa {index}", "phone": PHONES[index], "category": category,
             "city": "Cuiabá"} for index, category in enumerate(categories)]


class OrganizeTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = SalesStore(Path(self.directory.name) / "whatsapp")

    def tearDown(self):
        self.directory.cleanup()

    def test_leads_are_numbered_per_category_and_never_renumbered(self):
        report = self.store.import_rows(rows("Barbearia", "Barbearia", "Salão de Beleza"),
                                        MONDAY, "google-maps-manual")
        self.assertEqual(report["labels"], ["barbearia-1 Empresa 0", "barbearia-2 Empresa 1",
                                            "salao-de-beleza-1 Empresa 2"])
        more = [{"name": "Nova", "phone": PHONES[9], "category": "barbearia"}]
        self.assertEqual(self.store.import_rows(more, MONDAY, "receita-federal")["labels"],
                         ["barbearia-3 Nova"])
        self.assertEqual(category_slug(""), "lead")

    def test_each_batch_writes_a_vcard_for_the_phone(self):
        report = self.store.import_csv(write_csv(Path(self.directory.name) / "l.csv",
                                                 rows("Barbearia", "Barbearia")), MONDAY)
        batch = Path(report["contacts_file"]).read_text(encoding="utf-8")
        self.assertEqual(batch.count("BEGIN:VCARD"), 2)
        self.assertIn("FN:barbearia-1 Empresa 0", batch)
        self.assertIn("TEL;TYPE=CELL:+5565900000001", batch)
        everyone = (self.store.contacts_dir / "todos.vcf").read_text(encoding="utf-8")
        self.assertEqual(everyone.count("BEGIN:VCARD"), 2)
        self.assertEqual(oct(Path(report["contacts_file"]).stat().st_mode & 0o777), "0o600")

    def test_refused_numbers_leave_the_phone_list(self):
        self.store.import_rows(rows("Barbearia", "Barbearia"), MONDAY)
        self.store.add_dnc("5565900000001", "refusal", MONDAY)
        path = self.store.export_contacts(None, MONDAY, "todos")
        self.assertEqual(path.read_text(encoding="utf-8").count("BEGIN:VCARD"), 1)

    def test_chat_saved_with_the_label_still_finds_the_lead(self):
        self.store.import_rows(rows("Barbearia"), MONDAY)
        self.assertEqual(self.store.find_lead("barbearia-1 Empresa 0")["name"], "Empresa 0")
        self.assertEqual(self.store.find_lead("barbearia-1 Barbearia renomeada")["name"],
                         "Empresa 0")
        self.assertIsNone(self.store.find_lead("barbearia-10 Outra"))

    def test_unknown_source_is_refused(self):
        with self.assertRaises(ValueError):
            self.store.import_rows(rows("Barbearia"), MONDAY, "scraping")

    def test_impossible_time_is_approximated_and_the_original_noted(self):
        brief = dossier.approximate_brief({"contato_no_site": {
            "horario": "Segunda a sexta, das 9h53 até 9h74"}, "observacoes": []})
        self.assertEqual(brief["contato_no_site"]["horario"], "Segunda a sexta, das 9h53 até 10h14")
        self.assertIn("9h74", brief["observacoes"][0])
        self.assertEqual(dossier.approximate_times("das 8h30 às 18h")[1], [])

    def test_transcriber_confidence_is_kept_with_the_message(self):
        self.store.import_rows(rows("Barbearia"), MONDAY)
        channel = FakeChannel(self.store.journal_path, media={"m1": [(b"OggS", ".ogg")]},
                              bubbles=[{"dir": "in", "text": "", "id": "m1", "media": "audio"}])
        agent = SalesAgent(self.rules, self.store, channel, None, live=True, clock=Clock(),
                           sleep=lambda seconds: None, notify=lambda entry: None,
                           log=lambda message: None,
                           transcriber=lambda path: {"text": "Atendo das 9h às 18h",
                                                     "uncertain": ["18h"], "engine": "test"})
        agent.prospect()
        agent.ingest([{"id": "e1", "chat": "+55 65 90000-0001", "text": "0:05"}])
        agent.reply_pending()
        lead = next(iter(self.store.leads().values()))
        voice = next(entry for entry in self.store.history(lead["id"]) if entry.get("media"))
        self.assertEqual((voice["text"], voice["uncertain"]), ("Atendo das 9h às 18h", ["18h"]))

    def test_central_lists_interventions_first_with_the_contact(self):
        self.store.import_rows(rows("Barbearia", "Barbearia"), MONDAY)
        channel = FakeChannel(self.store.journal_path)
        clock = Clock()
        agent = SalesAgent(self.rules, self.store, channel, None, live=True, clock=clock,
                           sleep=lambda seconds: None, notify=lambda entry: None,
                           log=lambda message: None)
        summary = agent.cycle([], prospect=True)
        self.assertEqual(len(summary["openings"]), 2)
        clock.now = MONDAY + timedelta(minutes=5)
        agent.cycle([{"id": "e1", "chat": "+55 65 90000-0002", "text": "Quero fechar"}])
        data = json.loads(self.store.central_path.read_text(encoding="utf-8"))
        first = data["interventions"][0]
        self.assertEqual((first["label"], first["priority"]), ("barbearia-2", "hot"))
        self.assertEqual(first["wa_link"], "https://wa.me/5565900000002")
        counts = {item["state"]: item["count"] for item in data["states"]}
        self.assertEqual((counts["needs-owner"], counts["opened"]), (1, 1))
        self.assertEqual(data["messages"][0]["text"], "Que ótimo! Já te respondo pessoalmente "
                                                      "com os próximos passos.")
        self.assertEqual(len(central.STATES), 14)


if __name__ == "__main__":
    unittest.main()
