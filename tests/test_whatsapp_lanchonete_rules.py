import copy
import tomllib
import unittest
from datetime import datetime

from sales_fixtures import MONDAY, ZONE
from tools.ytbot.commercial.whatsapp.lanchonete import rules as lanchonete_rules


class LanchoneteRulesTests(unittest.TestCase):
    def setUp(self):
        self.rules = lanchonete_rules.load()
        self.raw = tomllib.loads(
            lanchonete_rules.RULES_PATH.read_text(encoding="utf-8"))

    def test_identity_menu_extras_and_payments_are_complete(self):
        self.assertEqual(self.rules.company, "Brasa & Pão")
        self.assertEqual(len(self.rules.items), 32)
        self.assertEqual(len(self.rules.extras), 16)
        self.assertEqual([payment.id for payment in self.rules.payments],
                         ["pix", "cash", "card"])
        self.assertIn("bacon", [extra.id for extra in self.rules.extras])
        self.assertEqual(self.rules.extra("bacon").price_cents, 400)
        self.assertEqual(self.rules.extra("cheddar").price_cents, 350)
        self.assertEqual(self.rules.extra("maionese").price_cents, 200)
        self.assertEqual(self.rules.item("x-bacon").price_cents, 2400)

    def test_menu_messages_fit_the_reply_limits_and_show_every_item(self):
        messages = self.rules.menu_messages()
        self.assertLessEqual(len(messages), self.rules.limits["max_messages_per_reply"])
        self.assertTrue(all(len(message) <= self.rules.limits["max_message_chars"]
                            for message in messages))
        text = "\n".join(messages)
        for item in self.rules.items:
            self.assertIn(item.name, text)
            self.assertIn(item.price, text)

    def test_delivery_values_are_the_only_fees(self):
        self.assertEqual(self.rules.delivery["fee_cents"], 500)
        self.assertEqual(self.rules.delivery["free_above_cents"], 6000)
        self.assertEqual(self.rules.delivery["min_order_cents"], 1500)
        self.assertTrue({"5.00", "60.00", "15.00"} <= self.rules.allowed_money)

    def test_ordering_window_is_1800_to_2300_every_day(self):
        self.assertTrue(self.rules.in_window(MONDAY.replace(hour=18, minute=0)))
        self.assertTrue(self.rules.in_window(MONDAY.replace(hour=22, minute=59)))
        self.assertFalse(self.rules.in_window(MONDAY.replace(hour=17, minute=59)))
        self.assertFalse(self.rules.in_window(MONDAY.replace(hour=23, minute=0)))
        self.assertTrue(self.rules.in_window(
            datetime(2026, 11, 22, 20, 0, tzinfo=ZONE)))

    def test_safety_intents_are_present_and_opt_out_blocks(self):
        for intent_id in ("opt_out", "bot_question", "human_request", "complaint", "status",
                          "cancel", "menu", "price", "hours", "address", "delivery",
                          "payment", "unknown"):
            self.assertTrue(self.rules.has_intent(intent_id), intent_id)
        self.assertEqual(self.rules.intent("opt_out").action, "block")
        self.assertEqual(self.rules.intent("human_request").action, "handoff")
        self.assertTrue(self.rules.intent("human_request").reason)

    def test_a_price_outside_the_menu_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["texts"]["confirmed_total"] = "Total: R$ 99,00 — pagamento: {payment}."
        with self.assertRaises(lanchonete_rules.RulesError):
            lanchonete_rules.build(raw)

    def test_duplicate_alias_or_bad_fallback_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["menu"]["items"][1]["aliases"].append(raw["menu"]["items"][0]["aliases"][0])
        with self.assertRaises(lanchonete_rules.RulesError):
            lanchonete_rules.build(raw)
        raw = copy.deepcopy(self.raw)
        raw["llm"]["fallback"] = ["gpt-expensive"]
        with self.assertRaises(lanchonete_rules.RulesError):
            lanchonete_rules.build(raw)

    def test_facts_have_no_links_and_render_company_and_address(self):
        facts = self.rules.facts_text()
        self.assertNotIn("http", facts)
        self.assertIn("Brasa & Pão", facts)
        self.assertIn(self.rules.address, facts)

    def test_payment_text_mentions_pix_cash_and_card(self):
        text = self.rules.payment_text().casefold()
        self.assertIn("pix", text)
        self.assertIn("dinheiro", text)
        self.assertIn("cartão", text)
        self.assertIn("troco", text)


if __name__ == "__main__":
    unittest.main()
