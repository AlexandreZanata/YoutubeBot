import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sales_fixtures import Clock, FakeChannel, FakeModel
from tools.ytbot.commercial.whatsapp.lanchonete.agent import (
    LanchoneteAgent, awaiting_reply, clean_incoming, is_ours, owner_resolve, text_plain,
)
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

    def test_first_contact_greets_without_dumping_the_menu_until_asked(self):
        self.say("oi")
        texts = self.sent()
        self.assertIn("Brasa", texts[0])
        self.assertIn("Nina", texts[0])
        self.assertFalse(any("X-Bacon" in text for text in texts))
        self.assertEqual(self.customer()["state"], "ordering")
        self.assertEqual(self.store.orders(), [])
        self.say("me manda o cardápio")
        self.assertTrue(any("X-Bacon" in text for text in self.sent()))

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
        before = len(self.sent())
        self.channel.bubbles = [{"dir": "out", "text": "Já te respondo por aqui", "id": "o1"}]
        self.say("e aí?")
        self.assertEqual(self.customer()["state"], "human")
        self.assertEqual(len(self.sent()), before)

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

    def test_replaced_preview_plus_chat_bubble_never_doubles_item(self):
        # Thainan regression: preview "Mais 10 açaí" replaced by chat bubble must stay 10, not 20.
        self.say("oi")
        self.agent.ingest([{"id": "p1", "chat": self.chat, "text": "Mais 10 açaí"}])
        customer = self.customer()
        self.agent.store.remember(customer["id"], {
            "at": self.clock.now.isoformat(timespec="seconds"), "dir": "in",
            "kind": "incoming", "source": "chat", "message_id": "m10",
            "replaces": ["p1"], "text": "Mais 10 açaí",
        })
        unanswered = awaiting_reply(self.agent.store.history(customer["id"]))
        self.assertEqual([entry["text"] for entry in unanswered], ["Mais 10 açaí"])
        self.agent.reply_pending()
        cart = self.customer()["cart"]
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]["item_id"], "acai-500")
        self.assertEqual(cart[0]["qty"], 10)

    def test_repeated_message_within_five_minutes_counts_once(self):
        self.say("oi")
        self.clock.now += timedelta(seconds=30)
        self.agent.ingest([{"id": "dup1", "chat": self.chat, "text": "Mais 10 açaí"}])
        self.clock.now += timedelta(minutes=2)
        self.agent.ingest([{"id": "dup2", "chat": self.chat, "text": "Mais 10 açaí"}])
        unanswered = awaiting_reply(self.agent.store.history(self.customer()["id"]))
        self.assertEqual(len(unanswered), 1)
        self.agent.reply_pending()
        self.assertEqual(self.customer()["cart"][0]["qty"], 10)

        # Separated by more than 5 minutes still counts separately.
        t0 = self.clock.now
        t1 = t0 + timedelta(minutes=6)
        hist = [
            {"dir": "out", "text": "ok"},
            {"dir": "in", "text": "quero uma coca", "at": t0.isoformat(timespec="seconds")},
            {"dir": "in", "text": "quero uma coca", "at": t1.isoformat(timespec="seconds")},
        ]
        self.assertEqual(len(awaiting_reply(hist)), 2)

    def test_partial_order_keeps_valid_item_and_asks_only_about_missing_part(self):
        # Felipe regression: 1x Coca added cleanly with NO leaked note, asked only about sauce.
        self.say("quero fazer um pedido")
        self.agent.ingest([{"id": "fp1", "chat": self.chat,
                            "text": "uma coca e um molhinho de pimenta safada"}])
        customer = self.customer()
        self.agent.store.remember(customer["id"], {
            "at": self.clock.now.isoformat(timespec="seconds"), "dir": "in",
            "kind": "incoming", "source": "chat", "message_id": "fm1",
            "replaces": ["fp1"], "text": "uma coca e um molhinho de pimenta safada",
        })
        self.agent.reply_pending()
        customer = self.customer()
        self.assertEqual(len(customer["cart"]), 1)
        self.assertEqual(customer["cart"][0]["item_id"], "coca-lata")
        self.assertEqual(customer["cart"][0]["qty"], 1)
        self.assertEqual(customer["cart"][0]["note"], "")
        reply_text = "\n".join(self.sent()[-3:]).casefold()
        self.assertIn("vamos manter o foco", reply_text)
        self.assertIn("coca-cola", reply_text)
        self.assertIn("molhinho de pimenta", reply_text)
        self.assertIn("adicionais", reply_text)
        self.assertNotIn("safada", reply_text)
        # Answering "sim" to "quer ver os adicionais?" lists catalog extras.
        self.say("sim")
        self.assertIn("Bacon extra — R$ 4,00", "\n".join(self.sent()[-2:]))

    def test_harassment_two_level_policy_deflects_first_then_escalates_hot(self):
        self.say("quero fazer um pedido")
        # Level 1 with valid order: Hot Dog Completo added cleanly, note clean, deflected neutrally.
        self.say("quero um hot doc completo com a maior salsicha possivel... se é que me entende....")
        customer = self.customer()
        self.assertEqual(customer["state"], "ordering")
        self.assertEqual(customer["cart"][0]["item_id"], "hot-dog-completo")
        self.assertEqual(customer["cart"][0]["qty"], 1)
        self.assertEqual(customer["cart"][0]["note"], "")
        self.assertIn("Vamos manter o foco no seu pedido", "\n".join(self.sent()))

        # Level 2 on repeat: hands over to owner with priority="hot", keeping existing cart.
        self.say("você é safada? Namora?")
        customer = self.customer()
        self.assertEqual(customer["state"], "needs-owner")
        self.assertEqual(customer["cart"][0]["item_id"], "hot-dog-completo")
        self.assertEqual(self.notes[-1]["priority"], "hot")
        self.assertIn("insinuação", self.notes[-1]["reason"].lower())

        # Standalone Level 1 flirt on fresh customer stays in ordering (no unknown strike wasted).
        other = "(65) 90000-0099"
        self.say("você é safada? Namora?", chat=other)
        other_cust = self.store.find_lead(other)
        self.assertEqual(other_cust["state"], "ordering")
        self.assertIn("Vamos manter o foco", "\n".join(self.sent()[-3:]))

    def test_destructive_keep_only_and_clear_cart_require_confirmation(self):
        self.say("oi")
        self.say("Mais 10 açaí")
        self.say("Deixa só um")
        # Must NOT reduce silently before confirmation.
        self.assertEqual(self.customer()["cart"][0]["qty"], 10)
        self.assertIn("Quer deixar o pedido só com 1x Açaí 500 ml?", "\n".join(self.sent()))
        self.say("SIM")
        self.assertEqual(self.customer()["cart"][0]["qty"], 1)

        # Multi-item ambiguous "só esse" / "Deixa só um" asks which item without guessing.
        self.say("quero uma coca")
        self.say("só esse")
        self.assertEqual(len(self.customer()["cart"]), 2)
        self.assertIn("Qual item você quer manter", "\n".join(self.sent()))

        # "tira tudo" asks confirmation before emptying cart.
        self.say("tira tudo")
        self.assertEqual(len(self.customer()["cart"]), 2)
        self.assertIn("Quer tirar todos os itens", "\n".join(self.sent()))
        self.say("SIM")
        self.assertEqual(self.customer()["cart"], [])

    def test_thainan_sequence_and_waiting_ping_never_go_silent(self):
        self.say("oi")
        self.say("Mais 10 açaí")
        self.assertEqual(self.customer()["cart"][0]["qty"], 10)
        self.say("Deixa só um")
        self.say("sim")
        self.assertEqual(self.customer()["cart"][0]["qty"], 1)
        # Semantic superlatives: never fall into opaque unknown -> needs-owner.
        before = len(self.sent())
        self.say("Quero o maior lanche")
        self.assertGreater(len(self.sent()), before)
        self.assertEqual(self.customer()["state"], "ordering")
        self.assertIn("Podrão da Casa", "\n".join(self.sent()[before:]))
        before = len(self.sent())
        self.say("Um lanche do maior que tem")
        self.assertGreater(len(self.sent()), before)
        self.assertEqual(self.customer()["state"], "ordering")
        before = len(self.sent())
        self.say("Cadê o atendimento?")
        self.assertGreater(len(self.sent()), before)
        self.assertIn("Nina, atendente virtual", "\n".join(self.sent()[before:]))

        # Even if already in needs-owner inside owner_reminder_minutes, "Cadê o atendimento?" alerts hot + responds once.
        self.store.update_lead(self.customer()["id"], state="needs-owner", awaiting=None,
                               handoff_reason="manual")
        self.agent._handoff(self.customer(), "anterior", "needed", "manual", "anterior")
        notes_before = len(self.notes)
        sent_before = len(self.sent())
        self.say("Cadê o atendimento?")
        self.assertEqual(len(self.notes), notes_before + 1)
        self.assertEqual(self.notes[-1]["priority"], "hot")
        self.assertEqual(len(self.sent()), sent_before + 1)
        # Subsequent repeated pings stay guarded against loops.
        sent_after = len(self.sent())
        self.say("Cadê o atendimento?")
        self.assertEqual(len(self.sent()), sent_after)

    def test_value_jump_requires_confirmation_and_cumulative_max_qty(self):
        self.say("oi")
        self.say("Açaí")
        # 1 -> 10 (+9 = 10 total, >3x jump vs 1x) must ask confirmation before adding.
        self.say("mais 9 açaí")
        self.assertEqual(self.customer()["cart"][0]["qty"], 1)
        self.assertIn("salto grande no pedido", "\n".join(self.sent()))
        self.say("não")
        self.assertEqual(self.customer()["cart"][0]["qty"], 1)

        # Cumulative > max_qty_per_item (10 + 10 = 20) must be rejected cleanly.
        self.say("mais 9 açaí")
        self.say("sim")
        self.assertEqual(self.customer()["cart"][0]["qty"], 10)
        self.say("Mais 10 açaí")
        self.assertEqual(self.customer()["cart"][0]["qty"], 10)
        self.assertIn("até 10 unidades", "\n".join(self.sent()))

        # Normal cross-item lunch add (1x Coca R$ 6 + 1x X-Tudo R$ 30) never false-positives.
        other = "(65) 90000-0088"
        self.say("oi", chat=other)
        self.say("uma coca", chat=other)
        self.say("um x-tudo", chat=other)
        other_cart = {line["item_id"]: line["qty"]
                      for line in self.store.find_lead(other)["cart"]}
        self.assertEqual(other_cart, {"coca-lata": 1, "x-tudo": 1})

    def test_contextual_pode_closes_cart_and_clarify_choice_resolves_option(self):
        # Felipe regression: answering "pode" to "Quer mais alguma coisa ou posso fechar o pedido?"
        self.say("oi")
        self.say("uma coca")
        self.assertIn("posso fechar o pedido?", self.sent()[-1])
        self.say("pode")
        self.assertEqual(self.customer()["awaiting_field"], "type")
        self.assertIn("entrega ou retirada", "\n".join(self.sent()[-2:]))

        # Memory resolves "o primeiro" after semantic superlative menu clarification.
        other = "(65) 90000-0077"
        self.say("Quero o maior lanche", chat=other)
        self.say("o primeiro", chat=other)
        cart = self.store.find_lead(other)["cart"]
        self.assertEqual([line["item_id"] for line in cart], ["podrao"])

    def test_identity_consistency_never_claims_human_except_handoff(self):
        self.say("oi")
        self.say("você é robô?")
        bot_reply = "\n".join(self.sent()[-2:]).casefold()
        self.assertIn("assistente virtual", bot_reply)
        self.assertNotIn("sou humano", bot_reply)
        self.say("Cadê o atendimento?")
        self.assertIn("Nina, atendente virtual", "\n".join(self.sent()[-2:]))
        self.say("quero falar com um atendente humano")
        self.assertEqual(self.customer()["state"], "needs-owner")
        self.assertIn("atendente humano", "\n".join(self.sent()[-1:]))

    def test_audio_uncertain_number_and_failed_transcription_handling(self):
        # Preview "0:12" replaced by audio transcript with uncertain digit "5" must confirm first.
        self.channel.bubbles = [{"dir": "in", "text": "", "id": "aud1", "media": "audio"}]
        self.channel.media = {"aud1": [(b"voice", ".ogg")]}
        self.agent.transcriber = lambda path: {
            "text": "quero 5 x-bacon", "uncertain": ["5"], "engine": "test",
        }
        self.say("0:12")
        self.assertEqual(self.customer()["cart"], [])
        self.assertIn("No seu áudio entendi 5x X-Bacon", "\n".join(self.sent()))
        self.channel.bubbles = []
        self.say("sim")
        self.assertEqual(self.customer()["cart"][0]["item_id"], "x-bacon")
        self.assertEqual(self.customer()["cart"][0]["qty"], 5)

        # Transcription failure falls back cleanly to owner media handoff.
        other = "(65) 90000-0066"
        self.channel.bubbles = [{"dir": "in", "text": "", "id": "aud2", "media": "audio"}]
        self.channel.media = {"aud2": [(b"broken", ".ogg")]}

        def fail_transcriber(_path):
            raise RuntimeError("whisper failed")

        self.agent.transcriber = fail_transcriber
        self.say("0:09", chat=other)
        self.assertEqual(self.store.find_lead(other)["state"], "needs-owner")

    def test_menu_url_sends_configured_link_only_when_requested(self):
        import copy
        import tomllib
        from tools.ytbot.commercial.whatsapp.lanchonete import rules as lanchonete_rules

        raw = tomllib.loads(lanchonete_rules.RULES_PATH.read_text(encoding="utf-8"))
        linked_raw = copy.deepcopy(raw)
        linked_raw["menu"]["url"] = "https://cardapio.brasaepao.com.br"
        linked_rules = lanchonete_rules.build(linked_raw)
        self.agent.use_rules(linked_rules)

        self.say("oi")
        self.assertFalse(any("https://" in text or "X-Bacon" in text for text in self.sent()))
        self.say("me manda o cardápio")
        self.assertTrue(any("https://cardapio.brasaepao.com.br" in text for text in self.sent()))
        self.assertFalse(any("X-Bacon" in text for text in self.sent()))

    def test_scoped_category_menus_send_only_requested_category(self):
        self.say("oi")
        before = len(self.sent())
        self.say("quero um lanche")
        burger_reply = "\n".join(self.sent()[before:])
        self.assertIn("X-Bacon", burger_reply)
        self.assertNotIn("Coca-Cola", burger_reply)
        self.assertNotIn("Açaí", burger_reply)

        before = len(self.sent())
        self.say("bebidas")
        drinks_reply = "\n".join(self.sent()[before:])
        self.assertIn("Coca-Cola", drinks_reply)
        self.assertNotIn("X-Bacon", drinks_reply)

        before = len(self.sent())
        self.say("quero uma porção")
        portions_reply = "\n".join(self.sent()[before:])
        self.assertIn("Batata Frita", portions_reply)
        self.assertNotIn("Coca-Cola", portions_reply)

    def test_delivery_asks_address_and_payment_together_across_reply_cases(self):
        # Case A: address + payment together in one message -> asks only missing name.
        self.say("quero um x-tudo")
        self.say("fechar")
        self.say("entrega")
        prompt = self.sent()[-1].casefold()
        self.assertIn("endereço", prompt)
        self.assertIn("como prefere pagar", prompt)
        self.say("Rua Florença, 922, pix")
        c = self.customer()
        self.assertEqual(c["order_address"], "Rua Florença, 922")
        self.assertEqual(c["order_payment"], "pix")
        self.assertEqual(c["awaiting_field"], "name")

        # Case B: only payment provided first -> asks ONLY address next (not payment again).
        other = "(65) 90000-0055"
        self.say("quero um x-tudo", chat=other)
        self.say("fechar", chat=other)
        self.say("entrega", chat=other)
        self.say("cartão", chat=other)
        c2 = self.store.find_lead(other)
        self.assertEqual(c2["order_payment"], "card")
        self.assertEqual(c2["awaiting_field"], "address")
        addr_only_prompt = self.sent()[-1].casefold()
        self.assertIn("qual o endereço", addr_only_prompt)
        self.assertNotIn("como prefere pagar", addr_only_prompt)
        self.assertNotIn("pix", addr_only_prompt)

        # Case C: name + address + payment + cash change all at once -> straight to summary!
        third = "(65) 90000-0044"
        self.say("quero um x-tudo", chat=third)
        self.say("fechar", chat=third)
        self.say("entrega", chat=third)
        self.say("Meu nome é Lucas, Rua das Flores 123, dinheiro troco pra 50", chat=third)
        c3 = self.store.find_lead(third)
        self.assertEqual(c3["state"], "confirming")
        self.assertEqual(c3["order_name"], "Lucas")
        self.assertEqual(c3["order_address"], "Rua das Flores 123")
        self.assertEqual(c3["order_payment"], "cash")
        self.assertEqual(c3["order_change_for_cents"], 5000)

    def test_felipe_live_checkout_failure_cases_are_all_fixed(self):
        self.say("quero fazer um pedido")
        self.say("1 hot doc completo e 1 coca")
        # 1) Profanity / clause closing still hits done cleanly.
        self.say("cu de amolar ferro, eu disse que pode fechar o pedido")
        self.assertEqual(self.customer()["awaiting_field"], "type")

        # 2) Replying "sim" to delivery/pickup prompt clarifies delivery vs pickup (no "qual item").
        before = len(self.sent())
        self.say("sim")
        reply = "\n".join(self.sent()[before:]).casefold()
        self.assertNotIn("qual item do cardápio", reply)
        self.assertIn("entrega ou retirada", reply)

        self.say("entrega")
        # 3) Preview + bubble address never duplicates into "rua florença, 922 rua florença, 922".
        self.agent.ingest([{"id": "addr1", "chat": self.chat, "text": "rua florença, 922"}])
        self.agent.store.remember(self.customer()["id"], {
            "at": self.clock.now.isoformat(timespec="seconds"), "dir": "in",
            "kind": "incoming", "source": "chat", "message_id": "addrm1",
            "replaces": ["addr1"], "text": "rua florença, 922",
        })
        self.agent.reply_pending()
        self.assertEqual(self.customer()["order_address"], "rua florença, 922")

        # 4) Invalid name fallback never says "qual item do cardápio"; clarifies name cleanly.
        before = len(self.sent())
        self.say("???")
        name_clarify = "\n".join(self.sent()[before:]).casefold()
        self.assertNotIn("qual item do cardápio", name_clarify)
        self.assertIn("nome", name_clarify)

        # 5) 60-char full name and prefixed "* " name both work natively without failing.
        self.say("pdiddy tinau epstein flavio zanata henrique garcia das neves")
        self.assertEqual(self.customer()["order_name"],
                         "pdiddy tinau epstein flavio zanata henrique garcia das neves")
        # Prefix + trailing asterisk also parses directly cleanly.
        self.say("cartão")
        self.assertEqual(self.customer()["state"], "confirming")

        # 6) High historical bot_replies never aborts final "sim" on confirming summary!
        self.store.update_lead(self.customer()["id"], bot_replies=20)
        self.say("sim")
        self.assertEqual(self.customer()["state"], "confirmed")
        self.assertEqual(len(self.store.orders()), 1)

        # Standalone prefixed + asterisk 61-char name check.
        from tools.ytbot.commercial.whatsapp.lanchonete.parser import parse_name
        self.assertEqual(
            parse_name("o meu nome é pdiddy tinau epstein flavio zanata henrique garcia das neves*"),
            "pdiddy tinau epstein flavio zanata henrique garcia das neves",
        )


if __name__ == "__main__":
    unittest.main()
