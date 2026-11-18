import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sales_fixtures import Clock, FakeChannel, FakeModel
from tools.ytbot.commercial.whatsapp.lanchonete.agent import LanchoneteAgent, owner_resolve
from tools.ytbot.commercial.whatsapp.lanchonete.rules import load
from tools.ytbot.commercial.whatsapp.lanchonete.store import LanchoneteStore

OPEN = datetime(2026, 11, 16, 19, 0, tzinfo=None)


class LanchoneteAgentTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        from zoneinfo import ZoneInfo
        self.clock = Clock(OPEN.replace(tzinfo=ZoneInfo("America/Cuiaba")))
        self.directory = tempfile.TemporaryDirectory()
        self.store = LanchoneteStore(Path(self.directory.name) / "whatsapp")
        self.channel = FakeChannel(self.store.journal_path)
        self.notes = []
        self.agent = LanchoneteAgent(self.rules, self.store, self.channel, None, live=True,
                                     clock=self.clock, sleep=lambda seconds: None,
                                     notify=self.notes.append, log=lambda message: None)
        self.chat = "(65) 90000-0001"
        self.count = 0

    def tearDown(self):
        self.directory.cleanup()

    def say(self, text):
        self.count += 1
        self.clock.now += timedelta(minutes=1)
        self.agent.ingest([{"id": f"e{self.count}", "chat": self.chat, "text": text}])
        return self.agent.reply_pending()

    def customer(self):
        return self.store.find_lead(self.chat)

    def sent(self):
        return [item["text"] for item in self.channel.sent]

    def test_first_contact_sends_the_menu_without_an_order(self):
        self.say("oi")
        texts = self.sent()
        self.assertIn("Brasa", texts[0])
        self.assertTrue(any("X-Bacon" in text for text in texts))
        self.assertEqual(self.customer()["state"], "ordering")
        self.assertEqual(self.store.orders(), [])

    def test_full_delivery_order_with_extras_cash_and_change(self):
        self.say("oi")
        self.say("quero 2 x-bacon com bacon extra e uma coca")
        self.say("fechar")
        self.say("entrega")
        self.say("Rua das Flores 123, Centro")
        self.say("Maria")
        self.say("dinheiro")
        self.say("troco para 100")
        self.say("sim")
        customer = self.customer()
        self.assertEqual(customer["state"], "confirmed")
        orders = self.store.orders()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["total"], "R$ 62,00")
        self.assertEqual(orders[0]["kind"], "delivery")
        self.assertTrue(Path(orders[0]["ficha"]).is_file())
        ficha = Path(orders[0]["ficha"]).read_text(encoding="utf-8")
        self.assertIn("Bacon extra — R$ 4,00 por unidade", ficha)
        self.assertIn("Troco a devolver: R$ 38,00", ficha)
        self.assertIn("Pedido confirmado", "\n".join(self.sent()))
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(self.notes[0]["priority"], "hot")
        self.assertIn("Novo pedido", self.notes[0]["reason"])

    def test_pickup_order_does_not_ask_for_an_address(self):
        self.say("oi")
        self.say("quero 2 x-burger")
        self.say("fechar")
        self.say("retirada")
        self.say("João")
        self.say("cartão")
        self.say("sim")
        customer = self.customer()
        self.assertEqual(customer["state"], "confirmed")
        self.assertEqual(self.store.orders()[0]["kind"], "pickup")
        self.assertNotIn("Qual o endereço", "\n".join(self.sent()))

    def test_minimum_order_blocks_delivery_but_allows_pickup(self):
        self.say("oi")
        self.say("quero uma coca")
        self.say("fechar")
        self.say("entrega")
        self.say("Rua A 1, Centro")
        self.say("Ana")
        self.say("pix")
        self.assertIn("pedido mínimo para entrega", "\n".join(self.sent()))
        self.assertEqual(self.customer()["state"], "ordering")
        self.assertEqual(self.store.orders(), [])
        self.say("retirada")
        self.say("sim")
        self.assertEqual(self.store.orders()[0]["kind"], "pickup")
        self.assertEqual(self.store.orders()[0]["total"], "R$ 6,00")

    def test_correction_at_the_summary_updates_the_total(self):
        self.say("oi")
        self.say("quero um x-tudo e uma coca")
        self.say("fechar")
        self.say("retirada")
        self.say("João")
        self.say("pix")
        self.say("tira a coca")
        customer = self.customer()
        self.assertEqual(customer["state"], "confirming")
        self.assertEqual(customer["confirmations"], 1)
        self.assertIn("*Total:* R$ 30,00", self.sent()[-2])
        self.say("sim")
        self.assertEqual(self.store.orders()[0]["total"], "R$ 30,00")

    def test_opt_out_blocks_the_number_and_stops_replies(self):
        self.say("oi")
        self.say("para de mandar mensagem")
        customer = self.customer()
        self.assertEqual(customer["state"], "do-not-contact")
        self.assertTrue(self.store.is_blocked(customer))
        before = len(self.sent())
        self.say("quero um x-bacon")
        self.assertEqual(len(self.sent()), before)

    def test_outside_hours_sends_one_notice_per_window(self):
        self.clock.now = self.clock.now.replace(hour=15, minute=0)
        self.say("oi")
        self.assertIn("estamos fechados", "\n".join(self.sent()))
        self.assertEqual(self.customer()["state"], "closed")
        before = len(self.sent())
        self.say("quero um x-bacon")
        self.assertEqual(len(self.sent()), before)
        self.clock.now = self.clock.now.replace(day=17, hour=19, minute=0)
        self.say("oi")
        self.assertIn("Aqui é a Nina", "\n".join(self.sent()))

    def test_two_unknown_answers_hand_the_chat_to_the_owner(self):
        self.say("oi")
        self.say("asdf ghjk")
        self.assertEqual(self.customer()["state"], "ordering")
        self.say("qwerty zxcv")
        self.assertEqual(self.customer()["state"], "needs-owner")
        self.assertEqual(len(self.notes), 1)
        self.assertIn("não entendeu", self.notes[0]["reason"].lower())

    def test_status_of_a_confirmed_order_goes_to_the_owner_without_a_bot_reply(self):
        self.say("oi")
        self.say("quero um x-tudo")
        self.say("fechar")
        self.say("retirada")
        self.say("Carlos")
        self.say("pix")
        self.say("sim")
        before = len(self.sent())
        self.say("cadê meu pedido?")
        self.assertEqual(len(self.sent()), before)
        self.assertEqual(self.notes[-1]["priority"], "hot")
        self.assertIn("pedido confirmado", self.notes[-1]["reason"].lower())

    def test_model_reads_a_free_form_order_but_never_invents_an_item(self):
        answer = {"items": [{"id": "x-bacon", "qty": 2, "extras": ["bacon"], "note": ""}],
                  "remove": [], "set": {}, "done": False, "cancel": False, "uncertain": False}
        agent = LanchoneteAgent(self.rules, self.store, self.channel, FakeModel(answer),
                                live=True, clock=self.clock, sleep=lambda seconds: None,
                                notify=self.notes.append, log=lambda message: None)
        self.agent = agent
        self.say("me vê dois lanches com bacon")
        self.assertEqual(self.customer()["cart"][0]["item_id"], "x-bacon")
        self.assertEqual(self.customer()["cart"][0]["qty"], 2)

        bad = {"items": [{"id": "nao-existe", "qty": 2}], "remove": [], "set": {},
               "done": False, "cancel": False, "uncertain": False}
        other_dir = tempfile.TemporaryDirectory()
        self.addCleanup(other_dir.cleanup)
        store = LanchoneteStore(Path(other_dir.name) / "whatsapp")
        channel = FakeChannel(store.journal_path)
        agent = LanchoneteAgent(self.rules, store, channel, FakeModel(bad), live=True,
                                clock=self.clock, sleep=lambda seconds: None,
                                notify=lambda entry: None, log=lambda message: None)
        agent.ingest([{"id": "b1", "chat": "(65) 90000-0003",
                       "text": "me vê dois lanches"}])
        agent.reply_pending()
        self.assertEqual(store.find_lead("(65) 90000-0003")["cart"], [])

    def test_allowlist_answers_only_the_selected_numbers_or_titles(self):
        agent = LanchoneteAgent(self.rules, self.store, self.channel, None, live=True,
                                clock=self.clock, sleep=lambda seconds: None,
                                notify=self.notes.append, log=lambda message: None,
                                only=("556696384527", "556696623492"))
        felipe = self.store.ensure_customer("Felipe", self.clock.now)
        self.store.update_lead(felipe["id"], phone="556696384527", chat="Felipe")
        agent.ingest([{"id": "a1", "chat": "Felipe", "text": "oi"}])
        self.assertIsNotNone(self.store.find_lead("Felipe")["awaiting"])
        agent.ingest([{"id": "a2", "chat": "Outro contato", "text": "oi"}])
        self.assertIsNone(self.store.find_lead("Outro contato"))
        agent.ingest([{"id": "a3", "chat": "(66) 9662-3492", "text": "oi"}])
        self.assertIsNotNone(self.store.find_lead("(66) 9662-3492"))

    def test_group_like_chats_are_never_touched(self):
        self.agent.ingest([{"id": "g1", "chat": "Família ❤️", "text": "João: quero 2 x-bacon"}])
        self.assertEqual(self.agent.reply_pending(), [])
        self.assertEqual(self.store.leads(), {})

    def test_voice_message_is_transcribed_and_ordered(self):
        self.channel.bubbles = [{"dir": "in", "text": "", "id": "m1", "media": "audio"}]
        self.channel.media = {"m1": [(b"voice", ".ogg")]}
        self.agent.transcriber = lambda path: {"text": "quero um x-bacon",
                                              "uncertain": [], "engine": "test"}
        self.say("[áudio]")
        customer = self.customer()
        self.assertEqual(customer["cart"][0]["item_id"], "x-bacon")
        self.assertIn("Quer mais alguma coisa", "\n".join(self.sent()))

    def test_extra_can_be_added_and_removed_on_an_existing_line(self):
        self.say("oi")
        self.say("quero um x-bacon com bacon")
        self.say("coloca cheddar no x-bacon")
        self.assertEqual(self.customer()["cart"][0]["extras"], ["bacon", "cheddar"])
        self.say("tira o bacon do x-bacon")
        self.assertEqual(self.customer()["cart"][0]["extras"], ["cheddar"])
        self.assertEqual(len(self.customer()["cart"]), 1)

    def test_flavors_and_notes_reach_the_kitchen_ficha(self):
        self.say("oi")
        self.say("quero um milk-shake de chocolate e um x-tudo sem cebola")
        cart = {line["item_id"]: line for line in self.customer()["cart"]}
        self.assertEqual(cart["milk-shake"]["note"], "chocolate")
        self.assertEqual(cart["x-tudo"]["note"], "cebola")

    def test_large_order_goes_to_the_owner_without_confirming(self):
        self.say("oi")
        self.say("quero 10 podrao")
        self.say("fechar")
        self.assertEqual(self.customer()["state"], "needs-owner")
        self.assertEqual(self.store.orders(), [])
        self.assertIn("Pedido acima do limite", self.notes[0]["reason"])

    def test_a_new_order_after_the_owner_closed_an_order_starts_clean(self):
        self.say("oi")
        self.say("quero um x-tudo")
        self.say("fechar")
        self.say("retirada")
        self.say("Ana")
        self.say("pix")
        self.say("sim")
        owner_resolve(self.store, self.customer()["id"], "closed")
        self.say("quero uma coca")
        cart = self.customer()["cart"]
        self.assertEqual([line["item_id"] for line in cart], ["coca-lata"])

    def test_owner_typing_in_the_chat_pauses_the_automation(self):
        self.say("oi")
        self.channel.bubbles = [{"dir": "out", "text": "Já te respondo por aqui", "id": "o1"}]
        self.say("e aí?")
        self.assertEqual(self.customer()["state"], "human")
        self.assertEqual(len(self.sent()), 7)


if __name__ == "__main__":
    unittest.main()
