"""Consistency suite for the Brasa & Pão agent: logical and semantic gaps found by replaying
adversarial customer conversations (plural/quantity wording, questions read as orders, checkout
fields given out of order, confirmation hijacking, money/change loops, silent turns)."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sales_fixtures import Clock, FakeChannel
from tools.ytbot.commercial.whatsapp.lanchonete import parser, semantics
from tools.ytbot.commercial.whatsapp.lanchonete.agent import LanchoneteAgent, owner_resolve
from tools.ytbot.commercial.whatsapp.lanchonete.rules import load
from tools.ytbot.commercial.whatsapp.lanchonete.store import LanchoneteStore

OPEN = datetime(2026, 11, 16, 19, 0)


class Base(unittest.TestCase):
    rules = load()

    def setUp(self):
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

    def say(self, *texts, chat=None):
        """Every text arrives before the bot answers (one reply cycle)."""
        for text in texts:
            self.count += 1
            self.clock.now += timedelta(seconds=30)
            self.agent.ingest([{"id": f"e{self.count}", "chat": chat or self.chat, "text": text}])
        return self.agent.reply_pending()

    def customer(self, chat=None):
        return self.store.find_lead(chat or self.chat)

    def cart(self):
        return {line["item_id"]: line["qty"] for line in self.customer()["cart"]}

    def last(self, count=1):
        return "\n".join(item["text"] for item in self.channel.sent[-count:])

    def checkout_to_summary(self, item="um x-tudo", kind="retirada", pay="pix"):
        self.say("oi")
        self.say(item)
        self.say("fechar")
        self.say(kind)
        if kind == "entrega":
            self.say("rua das flores 10 centro")
        self.say("Ana")
        self.say(pay)


class ParsingTests(Base):
    def test_plural_item_names_are_understood(self):
        for text, expected in (("quero duas cocas", {"coca-lata": 2}),
                               ("dois hot dogs completos", {"hot-dog-completo": 2}),
                               ("3 batatas fritas", {"batata-frita": 3})):
            parsed = parser.parse(self.rules, text)
            self.assertEqual({item.item_id: item.qty for item in parsed.items}, expected, text)

    def test_quantity_written_after_the_item(self):
        self.say("oi")
        self.say("x-tudo 2x")
        self.say("x-bacon x2")
        self.assertEqual(self.cart(), {"x-tudo": 2, "x-bacon": 2})

    def test_a_quantity_before_the_next_item_is_not_stolen_by_the_previous_one(self):
        parsed = parser.parse(self.rules, "um x-tudo 2 x-bacon")
        self.assertEqual({item.item_id: item.qty for item in parsed.items},
                         {"x-tudo": 1, "x-bacon": 2})

    def test_sem_notes_keep_their_meaning_for_the_kitchen(self):
        self.say("oi")
        self.say("um x-tudo sem cebola e sem tomate")
        self.assertEqual(self.customer()["cart"][0]["note"], "sem cebola; sem tomate")

    def test_pay_on_delivery_does_not_turn_a_pickup_into_a_delivery(self):
        self.assertEqual(parser.parse_kind("vou pagar na entrega no débito"), "")
        self.assertEqual(parser.parse_kind("quero entrega, pago na entrega no pix"), "delivery")
        self.assertEqual(parser.parse_kind("vou retirar no balcão"), "pickup")

    def test_address_is_cut_out_of_a_full_order_message(self):
        self.assertEqual(
            parser.parse_address("quero 2 x-bacon, entrega, rua das flores 10, centro, pix"),
            "rua das flores 10, centro")
        self.assertEqual(
            parser.parse_address("quero:\n2 x-bacon\n1 coca\nentrega\nrua das flores 10 centro\npix"),
            "rua das flores 10 centro")

    def test_variant_not_sold_is_not_silently_replaced(self):
        self.say("oi")
        self.say("quero uma coca zero")
        self.assertEqual(self.cart(), {})
        self.assertIn("coca zero", self.last())
        self.say("sim")
        text = self.last(2)
        self.assertIn("Coca-Cola lata 350 ml", text)
        self.assertNotIn("X-Bacon", text)  # only the drinks, not the whole menu


class QuestionsAreNotOrders(Base):
    def test_availability_and_ingredient_questions_do_not_add_items(self):
        self.say("oi")
        for question in ("tem x-tudo?", "o x-tudo tem ovo?", "vocês tem vegetariano?"):
            self.say(question)
            self.assertEqual(self.cart(), {}, question)
        self.assertIn("Veggie Burger", self.last(2))

    def test_quero_esse_after_a_price_answer_adds_that_item(self):
        self.say("oi")
        self.say("quanto custa o x-bacon")
        self.assertIn("Quer que eu anote", self.last())
        self.say("quero esse")
        self.assertEqual(self.cart(), {"x-bacon": 1})

    def test_total_and_cart_questions_show_the_cart(self):
        self.say("oi")
        self.say("o que eu pedi?")
        self.assertIn("vazio", self.last(2))
        self.say("um x-bacon")
        for text in ("qual o total?", "meu pedido", "quanto fica tudo?"):
            self.say(text)
            self.assertIn("Subtotal: R$ 24,00", self.last(2), text)
        self.assertEqual(self.cart(), {"x-bacon": 1})

    def test_generic_category_noun_lists_the_options_and_keeps_them_for_the_answer(self):
        self.say("oi")
        self.say("quero um hamburger")
        self.assertIn("X-Bacon", self.last())
        self.say("o quinto")
        self.assertEqual(self.cart(), {"cheddar-bacon": 1})

    def test_lanche_and_coca_in_one_message_adds_the_coca_and_asks_about_the_lanche(self):
        self.say("oi")
        self.say("eu queria um lanche e uma coca")
        self.assertEqual(self.cart(), {"coca-lata": 1})
        self.assertIn("X-Burger", self.last())
        self.say("o primeiro")
        self.assertEqual(self.cart(), {"coca-lata": 1, "x-burger": 1})

    def test_removing_something_not_in_the_cart_says_so(self):
        self.say("oi")
        self.say("um x-bacon")
        self.say("tira uma coca")
        self.assertIn("não está no seu pedido", self.last(2))
        self.assertEqual(self.cart(), {"x-bacon": 1})


class ConversationFlowTests(Base):
    def test_emoji_thumbs_up_answers_yes(self):
        self.say("oi")
        self.say("um x-tudo")
        self.say("👍")
        self.assertEqual(self.customer()["awaiting_field"], "type")
        self.say("retirada")
        self.say("Ana")
        self.say("pix")
        self.say("👍")
        self.assertEqual(self.customer()["state"], "confirmed")

    def test_no_thanks_closes_the_cart_instead_of_being_ignored(self):
        self.say("oi")
        self.say("um x-tudo")
        self.say("não, obrigado")
        self.assertEqual(self.customer()["awaiting_field"], "type")
        self.assertIn("entrega ou retirada", self.last())

    def test_a_misread_does_not_make_the_next_sim_fail(self):
        self.say("oi")
        self.say("um x-tudo")
        self.say("kkkkk")
        self.say("sim")
        self.assertEqual(self.customer()["awaiting_field"], "type")
        self.assertNotEqual(self.customer()["state"], "needs-owner")

    def test_punctuation_or_emoji_noise_is_not_a_strike_against_the_customer(self):
        self.say("oi")
        for noise in ("???", "...", "👀", "!!!"):
            self.say(noise)
        self.assertEqual(self.customer()["state"], "ordering")
        self.say("um x-bacon")
        self.assertEqual(self.cart(), {"x-bacon": 1})

    def test_greetings_in_the_middle_get_a_greeting_not_a_handoff(self):
        self.say("oi")
        self.say("um x-tudo")
        for text in ("oie tudo bem?", "e ai", "bom dia"):
            self.say(text)
            self.assertEqual(self.customer()["state"], "ordering", text)
            self.assertIn("Quer mais alguma coisa", self.last(), text)

    def test_cancel_word_at_the_summary_cancels(self):
        self.checkout_to_summary()
        self.say("cancela")
        self.assertEqual(self.customer()["state"], "cancelled")
        self.assertEqual(self.cart(), {})

    def test_closed_message_is_not_replayed_when_the_shop_opens(self):
        self.clock.now = self.clock.now.replace(hour=17, minute=0)
        self.say("oi")
        self.say("quero um x-bacon")
        self.clock.now = self.clock.now.replace(hour=18, minute=30)
        self.say("oi")
        self.assertEqual(self.cart(), {})

    def test_composite_message_fills_kind_and_payment(self):
        self.say("oi")
        self.say("um x-tudo, retirada, pix")
        customer = self.customer()
        self.assertEqual((customer["order_kind"], customer["order_payment"]), ("pickup", "pix"))

    def test_name_before_the_address_is_kept(self):
        self.say("oi")
        self.say("um x-tudo")
        self.say("fechar")
        self.say("entrega")
        self.say("Carla, rua x 10 centro, pix")
        customer = self.customer()
        self.assertEqual((customer["order_name"], customer["order_address"],
                          customer["order_payment"]), ("Carla", "rua x 10 centro", "pix"))
        self.assertEqual(customer["state"], "confirming")

    def test_too_many_extras_keep_the_item_and_say_so(self):
        self.say("oi")
        self.say("um x-tudo com bacon, cheddar, queijo, ovo, maionese, presunto, catupiry")
        self.assertEqual(self.cart(), {"x-tudo": 1})
        self.assertEqual(len(self.customer()["cart"][0]["extras"]),
                         int(self.rules.limits["max_extras_per_item"]))
        self.assertIn("até 6 adicionais", self.last(3))

    def test_a_cart_over_the_automatic_limit_goes_to_the_owner_immediately(self):
        self.say("oi")
        self.say("10 podrao")
        self.assertEqual(self.customer()["state"], "needs-owner")
        self.assertIn("Pedido acima do limite", self.notes[-1]["reason"])
        self.assertEqual(self.store.orders(), [])

    def test_long_orders_are_not_cut_by_the_reply_counters(self):
        self.say("oi")
        for index in range(12):
            self.say("uma coca" if index % 2 else "um guaraná")
        self.assertEqual(self.customer()["state"], "ordering")


class MoneyAndCheckoutTests(Base):
    def test_change_too_low_then_a_valid_value_is_accepted(self):
        self.checkout_to_summary(pay="dinheiro")
        # (checkout_to_summary stops asking for the change value)
        self.assertEqual(self.customer()["awaiting_field"], "change")
        self.say("10")
        self.assertIn("valor maior", self.last(2))
        self.say("50")
        customer = self.customer()
        self.assertEqual(customer["state"], "confirming")
        self.assertEqual(customer["order_change_for_cents"], 5000)

    def test_payment_can_be_changed_at_the_summary(self):
        self.checkout_to_summary()
        self.say("muda para cartão")
        self.assertEqual(self.customer()["order_payment"], "card")
        self.assertIn("Cartão", self.last(2))
        self.say("sim")
        self.assertEqual(self.store.orders()[0]["payment"], "card")

    def test_sim_with_a_different_payment_re_shows_the_summary_instead_of_confirming(self):
        self.checkout_to_summary()
        self.say("sim, no cartão")
        self.assertEqual(self.customer()["state"], "confirming")
        self.assertEqual(self.store.orders(), [])
        self.assertEqual(self.customer()["order_payment"], "card")

    def test_other_phrases_never_confirm_the_summary(self):
        self.checkout_to_summary(item="um x-tudo e uma coca")
        self.say("quero fazer um pedido")
        self.assertEqual(self.store.orders(), [])
        self.assertEqual(self.customer()["state"], "confirming")
        self.assertIn("Está tudo certo?", self.last())
        self.say("sim, mas tira a coca")
        self.assertEqual(self.store.orders(), [])
        self.assertEqual(self.cart(), {"x-tudo": 1})
        self.say("sim")
        self.assertEqual(len(self.store.orders()), 1)

    def test_paying_on_delivery_keeps_the_pickup_and_records_the_card(self):
        self.say("oi")
        self.say("um x-tudo")
        self.say("fechar")
        self.say("retirada")
        self.say("Ana")
        self.say("vou pagar na entrega no débito")
        customer = self.customer()
        self.assertEqual((customer["order_kind"], customer["order_payment"]), ("pickup", "card"))


class AfterTheOrderTests(Base):
    def test_a_confirmed_order_gets_one_holding_reply_for_changes_and_none_for_thanks(self):
        self.checkout_to_summary()
        self.say("sim")
        before = len(self.channel.sent)
        self.say("obrigado")
        self.assertEqual(len(self.channel.sent), before)
        self.say("quero mais uma coca")
        self.assertEqual(len(self.channel.sent), before + 1)
        self.assertIn("Avisei o atendente", self.last())
        self.say("e aí")
        self.assertEqual(len(self.channel.sent), before + 1)

    def test_after_the_owner_closes_a_new_order_starts_clean_and_can_be_followed_up_again(self):
        self.checkout_to_summary()
        self.say("sim")
        owner_resolve(self.store, self.customer()["id"], "closed")
        self.say("oi, quero uma coca")
        self.assertEqual(self.cart(), {"coca-lata": 1})
        self.assertLessEqual(self.customer()["bot_replies"], 1)


class SemanticsUnitTests(unittest.TestCase):
    rules = load()

    def test_emoji_answers(self):
        self.assertEqual(semantics.emoji_answer("👍"), "yes")
        self.assertEqual(semantics.emoji_answer("✅ 👍🏽"), "yes")
        self.assertEqual(semantics.emoji_answer("👎"), "no")
        self.assertEqual(semantics.emoji_answer("👍 ok"), "")
        self.assertEqual(semantics.emoji_answer(""), "")

    def test_show_cart_ignores_status_questions(self):
        self.assertTrue(semantics.is_show_cart("qual o total?"))
        self.assertFalse(semantics.is_show_cart("cadê meu pedido?"))

    def test_ordinals_resolve_against_the_listed_options(self):
        ids = [item.id for item in self.rules.items if item.category == "burgers"]
        self.assertEqual(semantics.resolve_clarify_choice(self.rules, ids, "o terceiro"), ids[2])
        self.assertEqual(semantics.resolve_clarify_choice(self.rules, ids, "o quinto"), ids[4])
        self.assertEqual(semantics.resolve_clarify_choice(self.rules, ids, "2"), ids[1])
        self.assertIsNone(semantics.resolve_clarify_choice(self.rules, ids, "o décimo"))


if __name__ == "__main__":
    unittest.main()
