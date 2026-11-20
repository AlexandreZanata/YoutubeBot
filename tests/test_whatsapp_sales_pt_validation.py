"""End-to-end validation of the sales agent's Portuguese behaviors (owner review, 2026-11-20).

Synthetic conversations through the real classifier, rules and agent with a fake channel:
nothing here touches the real WhatsApp account. Each case states what a person said, what the
bot answered and which state the conversation must be in.
"""

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sales_fixtures import MONDAY, PHONES, Clock, FakeChannel
from tools.ytbot.commercial.whatsapp.sales import classifier
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore

OFFER = [{"dir": "out", "text": "Você gostaria que eu fizesse um orçamento?", "state": "sent"}]


class PortugueseSalesValidationTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SalesStore(root / "whatsapp")
        self.store.import_rows([{"name": "Academia Exemplo", "phone": PHONES[0],
                                 "category": "Academia", "city": "Cuiabá"}], MONDAY)
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

    def say(self, text):
        self.count += 1
        self.clock.now = self.clock.now + timedelta(seconds=35)  # past the debounce
        self.agent.ingest([{"id": f"e{self.count}", "chat": "+55 65 90000-0001", "text": text}])
        return self.agent.reply_pending()

    def sent_texts(self):
        return [item["text"] for item in self.channel.sent]

    def state(self):
        return self.store.lead(self.lead["id"])["state"]

    def ask_bubbles(self):
        return list(self.rules.raw["referral_ask"]["messages"])

    # 1. A real refusal asks for an indication and hands the chat to the owner ------------
    def test_every_portuguese_refusal_wording_triggers_the_indication_ask(self):
        phrasings = [
            "Não, obrigado",
            "NÃO, OBRIGADO!",                      # caps
            "agora não",
            "Agora não, valeu",
            "Nesse momento não estou precisando",
            "não precisamos disso não, obrigado",
            "Não tenho interesse",
            "Não temos interesse, obrigado",
            "não me interessa",
            "Dispenço, valeu!",                    # accented, colloquial
            "obrigado, mas não",
            "não, valeu",
            "não é do nosso interesse",
            "sem interesse",
        ]
        for text in phrasings:
            with self.subTest(refusal=text):
                fresh = PortugueseSalesValidationTests()
                fresh.setUp()
                try:
                    fresh.say(text)
                    self.assertEqual(fresh.state(), "needs-owner", text)
                    self.assertEqual(fresh.sent_texts()[-len(fresh.ask_bubbles()):],
                                     fresh.ask_bubbles(), text)
                    self.assertFalse(fresh.store.is_dnc(fresh.lead["phone"]), text)
                finally:
                    fresh.tearDown()

    # 2. A redirect or a postponement is never a refusal --------------------------------
    def test_busy_postponing_or_redirecting_wordings_never_ask_for_an_indication(self):
        not_a_refusal = [
            ("Agora não posso, me chama amanhã", "callback_later"),
            ("Não me chama agora, me chama amanhã", "callback_later"),
            ("Não quero site, quero um aplicativo", "system_request"),
            ("vou pensar", "later"),
            ("Não tenho dinheiro agora, ta muito caro", "negotiation"),
            ("Não sei, o que vocês fazem mesmo?", "who_are_you"),  # the bot introduces itself
            # Staff wording: the bot keeps the chat and asks for the decider's contact
            # (a referral opportunity), which is the intended design.
            ("vou passar pro dono", "gatekeeper"),
        ]
        for text, expected in not_a_refusal:
            with self.subTest(text=text):
                intent = classifier.classify(self.rules, text, None, "engaged")
                self.assertNotEqual(intent, "refusal", text)
                self.assertNotEqual(intent, "opt_out", text)
                self.assertEqual(intent, expected, text)

    # 3. A true opt-out still blocks forever --------------------------------------------
    def test_explicit_opt_out_wordings_still_block_forever(self):
        wordings = [
            "Para de me mandar mensagem",
            "para de me enviar",
            "Pare de",
            "não me mande mais",
            "meu número, me remove",
            "remova o meu contato",
            "isso é spam",
            "vou denunciar",
            "vou bloquear",
            "não me chame mais",
            "não me procure mais",
            "sai fora",
            "meu número, me remove",
            "me remove da lista por favor",
            "tira meu numero dai",
            "pode tirar meu contato da lista",
            "apaga meu contato",
            "exclui o meu numero",
        ]
        for text in wordings:
            with self.subTest(opt_out=text):
                fresh = PortugueseSalesValidationTests()
                fresh.setUp()
                try:
                    fresh.say(text)
                    self.assertEqual(fresh.state(), "do-not-contact", text)
                    self.assertTrue(fresh.store.is_dnc(fresh.lead["phone"]), text)
                    self.assertNotIn(text, [t for t in fresh.sent_texts()])
                finally:
                    fresh.tearDown()

    # 4. After the ask the bot goes silent; the owner takes over ------------------------
    def test_after_the_ask_the_bot_never_replies_or_follows_up_again(self):
        self.say("Não tenho interesse")
        self.assertEqual(self.state(), "needs-owner")
        sent = len(self.channel.sent)
        self.say("Oi de novo")
        self.assertEqual(len(self.channel.sent), sent, "no bot reply after the ask")
        self.clock.now = MONDAY + timedelta(days=10)
        self.agent.followups()
        self.assertEqual(len(self.channel.sent), sent, "no follow-up after the ask")

    # 5. The debounce waits for a second bubble -----------------------------------------
    def test_two_bubbles_five_seconds_apart_are_answered_once_as_one_turn(self):
        self.agent.reply_debounce = 30.0
        self.agent.ingest([{"id": "b1", "chat": "+55 65 90000-0001", "text": "Boa tarde"}])
        self.assertEqual(self.agent.reply_pending(), [], "first bubble is not answered")
        self.clock.now += timedelta(seconds=5)
        self.agent.ingest([{"id": "b2", "chat": "+55 65 90000-0001", "text": "quanto custa um site?"}])
        self.assertEqual(self.agent.reply_pending(), [], "second bubble still inside the window")
        self.clock.now += timedelta(seconds=31)
        replies = self.agent.reply_pending()
        self.assertEqual([item["state"] for item in replies], ["engaged"], "one single turn")
        inbound = [entry for entry in self.store.history(self.lead["id"]) if entry["dir"] == "in"]
        self.assertEqual(len(inbound), 2, "both bubbles are in memory")

    # 6. Forwarding to the decision maker closes politely without the ask ----------------
    def test_forwarding_to_the_decider_closes_without_the_indication_ask(self):
        for text in ("Irei encaminhar para o responsável!!",
                     "vou encaminhar para o marketing",
                     "vou encaminhar para o responsável",
                     "já encaminhei pro comercial"):
            with self.subTest(forward=text):
                fresh = PortugueseSalesValidationTests()
                fresh.setUp()
                try:
                    fresh.say(text)
                    self.assertEqual(fresh.state(), "closed", text)
                    self.assertFalse(fresh.store.is_dnc(fresh.lead["phone"]), text)
                    self.assertNotEqual(fresh.sent_texts()[-len(fresh.ask_bubbles()):],
                                        fresh.ask_bubbles(), text)
                finally:
                    fresh.tearDown()

    # 7. A staff member stays a gatekeeper and is asked for the decision maker -----------
    def test_staff_wordings_keep_the_gatekeeper_flow(self):
        for text in ("Sou funcionária, o dono não está",
                     "aqui é a recepção",
                     "vou falar com o gerente"):
            with self.subTest(staff=text):
                fresh = PortugueseSalesValidationTests()
                fresh.setUp()
                try:
                    fresh.say(text)
                    self.assertIn(fresh.state(), ("gatekeeper", "referred", "needs-owner"), text)
                    self.assertFalse(fresh.store.is_dnc(fresh.lead["phone"]), text)
                finally:
                    fresh.tearDown()

    # 8. A refusal after real interest still asks for the indication --------------------
    def test_refusal_after_interest_also_asks_and_hands_to_the_owner(self):
        self.say("Vocês fazem aplicativo de agendamento?")
        self.say("Quero fechar")
        self.say("Academia Exemplo, agendamento pelo celular")
        self.say("Não tenho interesse")
        self.assertEqual(self.state(), "needs-owner")
        self.assertEqual(self.sent_texts()[-len(self.ask_bubbles()):], self.ask_bubbles())
        self.assertFalse(self.store.is_dnc(self.lead["phone"]))

    # 9. The ask is sent exactly once, never twice --------------------------------------
    def test_the_ask_is_never_repeated(self):
        self.say("Não, obrigado")
        ask = self.ask_bubbles()
        occurrences = sum(1 for i in range(len(self.sent_texts()) - len(ask) + 1)
                          if self.sent_texts()[i:i + len(ask)] == ask)
        self.assertEqual(occurrences, 1)

    # 10. The refusal wording still matches with accents, case and politeness -----------
    def test_classification_is_accent_and_case_insensitive(self):
        for text in ("NAO, OBRIGADO", "não obrigado", "Nao preciso não, valeu!"):
            self.assertIn(classifier.classify(self.rules, text, None, "engaged"),
                          ("refusal",), text)
        for text in ("vou encaminhar pro responsavel", "IREI ENCAMINHAR PARA O RESPONSÁVEL"):
            self.assertEqual(classifier.classify(self.rules, text, None, "engaged"),
                             "forwarded_to_decider", text)


if __name__ == "__main__":
    unittest.main()
