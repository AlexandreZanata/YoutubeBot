import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sales_fixtures import MONDAY, PHONES, Clock, FakeChannel
from tools.ytbot.commercial.whatsapp.sales import referral
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore


class SalesFlowTests(unittest.TestCase):
    """Staff answering, referral to the decision maker, closing and end classifications."""

    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = SalesStore(Path(self.directory.name) / "whatsapp")
        self.store.import_rows([{"name": "Barbearia Navalha", "phone": PHONES[0],
                                 "category": "Barbearia", "city": "Cuiabá"}], MONDAY)
        self.lead = next(iter(self.store.leads().values()))
        self.clock = Clock()
        self.notes = []
        self.channel = FakeChannel(self.store.journal_path)
        self.agent = SalesAgent(self.rules, self.store, self.channel, None, live=True,
                                clock=self.clock, sleep=lambda seconds: None,
                                notify=self.notes.append, log=lambda message: None)
        self.agent.prospect()
        self.count = 0

    def tearDown(self):
        self.directory.cleanup()

    def say(self, text, chat="+55 65 90000-0001"):
        self.count += 1
        self.clock.now = self.clock.now + timedelta(minutes=1)
        self.agent.ingest([{"id": f"e{self.count}", "chat": chat, "text": text}])
        return self.agent.reply_pending()

    def state(self, lead_id=None):
        return self.store.lead(lead_id or self.lead["id"])["state"]

    def sent(self):
        return [item["text"] for item in self.channel.sent]

    def test_staff_is_asked_for_the_decision_maker_and_the_referral_is_opened(self):
        self.say("Sou funcionária, o dono não está")
        self.assertEqual(self.state(), "gatekeeper")
        self.assertEqual(self.sent()[-1], self.rules.raw["referral"]["ask_name"])
        self.say("Aqui é a Paula")
        self.assertEqual(self.store.lead(self.lead["id"])["staff_name"], "Paula")
        self.assertIn("Prazer, Paula!", self.sent()[-1])
        self.say("O número do Carlos é (65) 90000-0009")
        lead = self.store.lead(self.lead["id"])
        self.assertEqual(lead["state"], "referred")
        new = self.store.lead(lead["referred_to"])
        self.assertEqual((new["label"], new["name"]), ("barbearia-2", "Carlos · Barbearia Navalha"))
        self.assertEqual(new["referral"]["staff"], "Paula")
        self.assertIn("Muito obrigado, Paula! Vou falar com Carlos agora.", self.sent())
        self.assertIn("Paula, da empresa Barbearia Navalha, me passou o seu contato. Sou o "
                      "Alexandre, da Zaflas Inova Simples: criamos sistemas, sites e aplicativos. "
                      "Vi que no Google Maps a empresa Barbearia Navalha ainda não tem site.",
                      self.sent())
        self.assertEqual(new["state"], "opened")
        batch = sorted(self.store.contacts_dir.glob("novos-*.vcf"))[-1].read_text("utf-8")
        self.assertIn("FN:barbearia-2 Carlos · Barbearia Navalha", batch)

    def test_referral_to_a_number_already_in_the_contacts_still_gets_the_opening(self):
        # Owner, 2026-11-18: a referred contact is always messaged, even one already known.
        self.store.import_rows([{"name": "Carlos", "phone": PHONES[8], "category": "Barbearia"}],
                               MONDAY)
        known = self.store.find_lead(PHONES[8])
        self.store.update_lead(known["id"], state="needs-owner", opened_at="2026-11-15T09:00:00",
                               last_in_at="2026-11-15T09:05:00", cycle=1)
        before = set(self.store.leads())
        self.say("Sou funcionária, o dono não está")
        self.say("O número do Carlos é (65) 90000-0009")
        self.assertEqual(set(self.store.leads()), before)
        self.assertEqual(self.store.lead(self.lead["id"])["referred_to"], known["id"])
        lead = self.store.lead(known["id"])
        self.assertEqual((lead["state"], lead["cycle"]), ("opened", 2))
        self.assertEqual(lead["referral"]["from"], self.lead["id"])
        self.assertIn("A equipe da empresa Barbearia Navalha me passou o seu contato. Sou o "
                      "Alexandre, da Zaflas Inova Simples: criamos sistemas, sites e aplicativos. "
                      "Vi que no Google Maps a empresa Barbearia Navalha ainda não tem site.",
                      self.sent())

    def test_referral_to_a_contact_the_owner_is_closing_goes_to_the_owner(self):
        self.store.import_rows([{"name": "Carlos", "phone": PHONES[8], "category": "Barbearia"}],
                               MONDAY)
        known = self.store.find_lead(PHONES[8])
        self.store.update_lead(known["id"], state="won")
        sent = len(self.sent())
        self.say("Sou funcionária, o dono não está")
        self.say("O número do Carlos é (65) 90000-0009")
        self.assertEqual(self.store.lead(known["id"])["state"], "won")
        self.assertEqual(self.state(), "needs-owner")
        self.assertIn("já está nos contatos (barbearia-2, estado won)", self.notes[-1]["reason"])
        self.assertFalse([text for text in self.sent()[sent:] if "me passou o seu contato" in text])

    def test_staff_who_will_not_pass_the_contact_gets_a_kind_close(self):
        self.say("Sou funcionária, o dono não está")
        self.say("Vou passar pro dono, ele te chama")
        self.assertEqual(self.sent()[-1], self.rules.raw["referral"]["gave_up"])
        self.assertEqual(self.state(), "closed")

    def test_referral_opens_even_after_the_cold_limit(self):
        self.store.update_lead(self.lead["id"], interest="")
        for index in range(10):
            self.store.import_rows([{"name": f"Outra {index}", "phone": PHONES[10 + index]}], MONDAY)
        self.agent.prospect()
        self.assertEqual(self.agent.openings_today("cold"), 10)
        self.say("Fala com o dono no 65 90000-0009")
        self.assertEqual(self.agent.openings_today("referral"), 1)

    def test_closing_the_simple_site_sends_the_pix_keys_and_waits_for_the_owner(self):
        self.say("Quanto fica um site simples pra barbearia?")
        self.say("Quero fechar, como faço pra pagar a entrada?")
        self.assertEqual(self.state(), "won")
        self.assertIn("financeiro@zaflas.com.br", self.sent())
        self.assertIn("8e725568-04bd-47e9-9615-cf090a1929a7", self.sent())
        self.assertEqual(self.notes[-1]["priority"], "hot")
        sent = len(self.sent())
        self.say("Paguei, segue o comprovante")
        self.assertEqual(len(self.sent()), sent)
        self.assertEqual(self.notes[-1]["reason"], self.rules.intent("payment_sent").reason)

    def test_closing_a_system_goes_to_the_owner_without_keys(self):
        self.say("Vocês fazem aplicativo de agendamento?")
        self.say("Quero fechar")
        self.assertEqual(self.state(), "buying")
        self.assertNotIn("financeiro@zaflas.com.br", self.sent())
        self.assertEqual(self.notes[-1]["reason"], self.rules.intent("ready_to_buy").reason)

    def test_giving_up_after_interest_is_lost_not_blocked(self):
        self.say("Vocês fazem aplicativo de agendamento?")
        self.say("Não tenho interesse")
        self.assertEqual(self.state(), "lost")
        self.assertFalse(self.store.is_dnc(self.lead["phone"]))
        self.assertIn("você decide", self.notes[-1]["reason"])

    def test_cold_refusal_still_blocks(self):
        self.say("Não tenho interesse")
        self.assertEqual(self.state(), "do-not-contact")
        self.assertTrue(self.store.is_dnc(self.lead["phone"]))

    def test_central_shows_the_new_states(self):
        self.say("Vocês fazem aplicativo de agendamento?")
        self.say("Quero fechar")
        self.agent.cycle([])
        data = json.loads(self.store.central_path.read_text(encoding="utf-8"))
        counts = {item["state"]: (item["count"], item["group"]) for item in data["states"]}
        self.assertEqual(counts["buying"], (1, "Com você"))
        self.assertIn("gatekeeper", counts)
        self.assertIn("referred", counts)


class ReferralParsingTests(unittest.TestCase):
    def test_numbers_and_names_come_from_the_message(self):
        text = "Aqui é a Paula. O número do Carlos é (65) 90000-0009, ou 65 900000001"
        self.assertEqual(referral.phones(text, own="5565900000001"), ["5565900000009"])
        self.assertEqual(referral.names(text), {"staff": "Paula", "decider": "Carlos"})
        self.assertEqual(referral.names("o whats do dono é esse"), {"staff": "", "decider": ""})


if __name__ == "__main__":
    unittest.main()
