import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sales_fixtures import Clock, FakeChannel, FakeModel
from tools.ytbot.commercial.whatsapp.lanchonete.agent import (LanchoneteAgent, clean_incoming,
                                                              is_ours, owner_resolve, text_plain)
from tools.ytbot.commercial.whatsapp.lanchonete.parser import parse
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

    def say(self, text, chat=None):
        self.count += 1
        self.clock.now += timedelta(minutes=1)
        self.agent.ingest([{"id": f"e{self.count}", "chat": chat or self.chat, "text": text}])
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

    def test_a_quoted_cart_is_not_read_as_a_second_order(self):
        cart = ("Seu pedido até agora:\n• 1x Calabresa Acebolada — R$ 24,00\n"
                "• 1x Milk-Shake 400 ml — R$ 14,00\n• 1x Açaí 500 ml — R$ 22,00\n"
                "Subtotal: R$ 60,00")
        quoted = cart.replace("• ", "") + "\nQuero a açaí mais barato"
        self.assertEqual(clean_incoming(quoted, [cart]), "Quero a açaí mais barato")
        self.assertEqual(clean_incoming("Quer mais alguma coisa ou posso fechar o pedido?\n"
                                        "Milk-shake",
                                        ["Quer mais alguma coisa ou posso fechar o pedido?"]),
                         "Milk-shake")
        parsed = parse(self.rules, "Quero a açaí mais barato")
        self.assertEqual([item.item_id for item in parsed.items], ["acai-300"])

    def test_everything_on_the_menu_goes_to_the_owner(self):
        self.say("oi")
        self.say("Coloca tudo do cardápio")
        self.assertEqual(self.customer()["state"], "needs-owner")
        self.assertEqual(self.customer()["cart"], [])
        self.assertIn("Pedido acima do limite", self.notes[0]["reason"])

    def test_two_customers_keep_separate_carts_and_states(self):
        self.say("oi")
        self.say("quero um x-tudo")
        other = "(65) 90000-0002"
        self.say("oi", chat=other)
        self.say("quero uma coca", chat=other)
        felipe = self.store.find_lead(self.chat)
        thainan = self.store.find_lead(other)
        self.assertEqual([line["item_id"] for line in felipe["cart"]], ["x-tudo"])
        self.assertEqual([line["item_id"] for line in thainan["cart"]], ["coca-lata"])
        self.assertEqual(felipe["state"], "ordering")
        self.assertEqual(thainan["state"], "ordering")
        self.assertNotEqual(felipe["id"], thainan["id"])

    def test_a_new_agent_restores_the_saved_cart_and_state(self):
        self.say("oi")
        self.say("quero um x-tudo")
        agent = LanchoneteAgent(self.rules, self.store, self.channel, None, live=True,
                                clock=self.clock, sleep=lambda seconds: None,
                                notify=self.notes.append, log=lambda message: None)
        self.agent = agent
        self.say("mais uma coca")
        cart = [line["item_id"] for line in self.customer()["cart"]]
        self.assertEqual(cart, ["x-tudo", "coca-lata"])

    def test_recover_clears_only_the_unconfirmed_state(self):
        self.say("oi")
        self.store.update_lead(self.customer()["id"], state="unconfirmed",
                               handoff_reason="send failed")
        recovered = self.store.recover_unconfirmed(self.clock.now)
        self.assertEqual(len(recovered), 1)
        customer = self.customer()
        self.assertEqual(customer["state"], "ordering")
        self.assertIsNone(customer["handoff_reason"])

    def test_opening_sends_the_menu_once_without_replaying_the_history(self):
        customer = self.store.ensure_customer(self.chat, self.clock.now)
        self.store.update_lead(customer["id"], phone="556696384527", chat=self.chat)
        result = self.agent.opening(customer)
        self.assertEqual(result["state"], "ordering")
        self.assertTrue(any("X-Bacon" in text for text in self.sent()))
        before = len(self.sent())
        self.agent.opening(customer)
        self.assertEqual(len(self.sent()), before)

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

    def test_formatted_menu_bubbles_are_recognized_as_the_bots_own(self):
        sent = [text_plain("*Hot dogs*\n• Hot Dog — R$ 12,00\n• Hot Dog Completo — R$ 16,00")]
        self.assertTrue(is_ours("Hot dogs\n\nHot Dog — R$ 12,00\nHot Dog Completo — R$ 16,00",
                                sent))
        self.assertFalse(is_ours("quero pedir a atendente", sent))

    def test_owner_typing_in_the_chat_pauses_the_automation(self):
        self.say("oi")
        self.channel.bubbles = [{"dir": "out", "text": "Já te respondo por aqui", "id": "o1"}]
        self.say("e aí?")
        self.assertEqual(self.customer()["state"], "human")
        self.assertEqual(len(self.sent()), 7)

    def test_cheaper_acai_proposes_a_swap_instead_of_adding(self):
        self.say("oi")
        self.say("Adicione calabresa bem grossa")
        self.say("Milk-shake")
        self.say("Açaí")
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"calabresa-acebolada": 1, "milk-shake": 1, "acai-500": 1})
        self.say("Quero a açaí mais barato")
        # Nothing was added: the bot asks before exchanging.
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"calabresa-acebolada": 1, "milk-shake": 1, "acai-500": 1})
        self.assertEqual(self.customer().get("pending_replace"),
                         {"from": "acai-500", "to": "acai-300", "qty": 1})
        self.assertIn("Troco Açaí 500 ml por Açaí 300 ml?", "\n".join(self.sent()))
        self.say("sim")
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"calabresa-acebolada": 1, "milk-shake": 1, "acai-300": 1})
        self.assertFalse(self.customer().get("pending_replace"))

    def test_no_measures_proposal_when_the_customer_refuses_it(self):
        self.say("oi")
        self.say("Açaí")
        self.say("Quero a açaí mais barato")
        self.assertTrue(self.customer().get("pending_replace"))
        self.say("não")
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"acai-500": 1})
        self.assertFalse(self.customer().get("pending_replace"))

    def test_bare_rejection_removes_the_named_cart_item(self):
        self.say("oi")
        self.say("Adicione calabresa bem grossa")
        self.say("Açaí")
        self.say("não o de 500")
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"calabresa-acebolada": 1})
        self.assertIn("Tirei Açaí 500 ml do pedido.", "\n".join(self.sent()))

    def test_replace_request_with_quote_never_duplicates_the_cart(self):
        self.say("oi")
        self.say("Adicione calabresa bem grossa")
        self.say("Milk-shake")
        self.say("Açaí")
        quoted = ("Seu pedido até agora:\n1x Calabresa Acebolada — R$ 24,00\n"
                  "1x Milk-Shake 400 ml — R$ 14,00\n1x Açaí 500 ml — R$ 22,00\n"
                  "Subtotal: R$ 60,00\nQuero a açaí mais barato")
        self.say(quoted)
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"calabresa-acebolada": 1, "milk-shake": 1, "acai-500": 1})
        self.assertTrue(self.customer().get("pending_replace"))

    def test_journal_keys_bind_cause_and_content(self):
        customer = {"id": "C1", "awaiting": "event-9"}
        first = self.agent._items(customer, "reply", ["Oi, tudo bem?"], "oi")
        same = self.agent._items(customer, "reply", ["Oi, tudo bem?"], "oi")
        other_text = self.agent._items(customer, "reply", ["Outra coisa"], "oi")
        other_cause = self.agent._items({"id": "C1", "awaiting": "event-10"}, "reply",
                                        ["Oi, tudo bem?"], "oi")
        self.assertEqual(first[0]["key"], same[0]["key"])
        self.assertNotEqual(first[0]["key"], other_text[0]["key"])
        self.assertNotEqual(first[0]["key"], other_cause[0]["key"])

    def test_one_failing_customer_does_not_block_the_other(self):
        class FlakyChannel(type(self.channel)):
            def send(self, lead, items, extra):
                if lead["id"] != self.fail_id:
                    return super().send(lead, items, extra)
                raise RuntimeError("browser hiccup")

        self.say("oi")
        first_id = self.customer()["id"]
        other_chat = "(65) 90000-0002"
        self.say("oi", chat=other_chat)
        self.channel.__class__ = FlakyChannel
        self.channel.fail_id = first_id
        self.count += 1
        self.clock.now += timedelta(minutes=1)
        self.agent.ingest([{"id": "eX", "chat": self.chat, "text": "quero uma coca"}])
        self.agent.ingest([{"id": "eY", "chat": other_chat, "text": "quero uma coca"}])
        results = self.agent.reply_pending()
        by_customer = {item["customer"]: item for item in results}
        self.assertEqual(by_customer[first_id]["state"], "error")
        second_id = self.store.find_lead(other_chat)["id"]
        self.assertEqual(by_customer[second_id]["state"], "ordering")
        cart = {line["item_id"]: line["qty"]
                for line in self.store.lead(second_id)["cart"]}
        self.assertEqual(cart, {"coca-lata": 1})

    def test_closed_hours_answer_with_the_closed_message(self):
        self.clock.now = self.clock.now.replace(hour=15, minute=0)
        self.say("oi")
        self.assertEqual(self.customer()["state"], "closed")
        self.assertIn("estamos fechados", "\n".join(self.sent()).casefold())

    def test_attendant_request_warns_and_hands_over_politely(self):
        self.say("quero pedir a atendente")
        texts = "\n".join(self.sent())
        self.assertIn("atendente humano", texts)
        self.assertEqual(self.customer()["state"], "needs-owner")

    def test_wanting_to_order_shows_the_menu(self):
        self.say("quero fazer um pedido")
        texts = "\n".join(self.sent())
        self.assertIn("cardápio", texts)
        self.assertIn("X-Bacon", texts)
        self.assertEqual(self.customer()["state"], "ordering")
        # ...while a real item in the same sentence still orders.
        self.say("quero pedir um x-bacon")
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"x-bacon": 1})

    def test_owner_paste_does_not_swallow_the_pending_question(self):
        self.say("oi")
        self.say("quero um x-bacon")
        # The owner pastes something unrelated in the chat: automation pauses...
        self.store.remember(self.customer()["id"], {
            "at": "2026-11-18T15:17:53-04:00", "dir": "out", "kind": "owner",
            "text": "olha esse link aqui", "state": "sent"})
        self.store.update_lead(self.customer()["id"], state="human", awaiting=None)
        self.say("quero uma coca")
        self.assertEqual(self.customer()["state"], "human")
        # ...but handing the chat back still owes an answer to the pending question.
        owner_resolve(self.store, self.customer()["id"], "ordering")
        results = self.agent.reply_pending()
        self.assertEqual(results[0]["state"], "ordering")
        cart = {line["item_id"]: line["qty"] for line in self.customer()["cart"]}
        self.assertEqual(cart, {"x-bacon": 1, "coca-lata": 1})


if __name__ == "__main__":
    unittest.main()
