import unittest

from sales_fixtures import MONDAY

from tools.ytbot.commercial.whatsapp.lanchonete import guard
from tools.ytbot.commercial.whatsapp.lanchonete.order import Order, OrderError
from tools.ytbot.commercial.whatsapp.lanchonete.rules import brl, load


class LanchoneteOrderTests(unittest.TestCase):
    def setUp(self):
        self.rules = load()

    def order(self):
        order = Order(kind="delivery", customer_name="Maria", address="Rua A, 10 — Centro",
                      payment="cash", change_for_cents=10000)
        order.add(self.rules, "x-bacon", 2, ["bacon"])
        order.add(self.rules, "coca-lata")
        return order

    def test_extra_is_charged_per_unit_and_identical_lines_merge(self):
        order = self.order()
        self.assertEqual(len(order.lines), 2)
        line = order.lines[0]
        self.assertEqual(line.unit_cents(self.rules), 2800)
        self.assertEqual(line.total_cents(self.rules), 5600)
        order.add(self.rules, "x-bacon", 1, ["bacon"])
        self.assertEqual(order.lines[0].qty, 3)
        self.assertEqual(order.lines[0].total_cents(self.rules), 8400)

    def test_delivery_free_above_sixty_and_change(self):
        totals = self.order().totals(self.rules)
        self.assertEqual(totals.subtotal_cents, 6200)
        self.assertEqual(totals.delivery_fee_cents, 0)
        self.assertEqual(totals.total_cents, 6200)
        self.assertEqual(totals.change_due_cents, 3800)
        self.assertFalse(totals.change_too_low)

    def test_fee_below_the_free_threshold(self):
        order = Order(kind="delivery")
        order.add(self.rules, "x-tudo")
        totals = order.totals(self.rules)
        self.assertEqual(totals.delivery_fee_cents, 500)
        self.assertEqual(totals.total_cents, 3500)

    def test_pickup_has_no_fee(self):
        order = Order(kind="pickup")
        order.add(self.rules, "coca-lata")
        totals = order.totals(self.rules)
        self.assertEqual(totals.delivery_fee_cents, 0)
        self.assertEqual(totals.total_cents, 600)

    def test_minimum_order_is_flagged_not_silently_filled(self):
        order = Order(kind="delivery")
        order.add(self.rules, "coca-lata")
        totals = order.totals(self.rules)
        self.assertEqual(totals.missing_min_cents, 900)
        order.kind = "pickup"
        self.assertEqual(order.totals(self.rules).missing_min_cents, 0)

    def test_change_low_and_exact(self):
        order = Order(kind="delivery", payment="cash", change_for_cents=2000)
        order.add(self.rules, "x-tudo")
        totals = order.totals(self.rules)
        self.assertTrue(totals.change_too_low)
        order.change_for_cents = None
        order.change_exact = True
        totals = order.totals(self.rules)
        self.assertFalse(totals.change_too_low)
        self.assertEqual(totals.change_due_cents, 0)

    def test_remove_whole_line_and_partial_quantity(self):
        order = self.order()
        self.assertEqual(order.remove(self.rules, "x-bacon", 1), 1)
        self.assertEqual(order.lines[0].qty, 1)
        self.assertEqual(order.remove(self.rules, "x-bacon"), 1)
        self.assertEqual(len(order.lines), 1)
        self.assertEqual(order.remove(self.rules, "coca-lata"), 1)
        self.assertTrue(order.is_empty())

    def test_add_extra_to_an_existing_line_and_reject_unknown(self):
        order = self.order()
        order.add_extra(self.rules, "x-bacon", "cheddar")
        self.assertIn("cheddar", order.lines[0].extras)
        with self.assertRaises(OrderError):
            order.add_extra(self.rules, "x-bacon", "nao-existe")

    def test_summary_and_ficha_show_everything_the_customer_confirms(self):
        order = self.order()
        order.number = "BP-20261116-001"
        order.status = "confirmed"
        summary = order.summary_text(self.rules)
        for text in ("entrega", "Maria", "Rua A, 10", "2x X-Bacon", "Bacon extra",
                     "1x Coca-Cola", "Subtotal", "Total", "Dinheiro", "troco para R$ 100,00",
                     "troco de R$ 38,00"):
            self.assertIn(text, summary)
        ficha = order.ficha_markdown(self.rules, {"name": "Maria", "phone": "5565900000001"},
                                     MONDAY, "Nina")
        for text in ("# Pedido BP-20261116-001", "Maria", "Rua A, 10", "2x X-Bacon",
                     "Bacon extra — R$ 4,00 por unidade", "Total do item: R$ 56,00",
                     "**Total: R$ 62,00**", "Dinheiro", "Troco a devolver: R$ 38,00"):
            self.assertIn(text, ficha)

    def test_guard_accepts_the_order_and_rejects_an_invented_price(self):
        order = self.order()
        messages = [order.cart_text(self.rules), order.summary_text(self.rules)]
        self.assertEqual(guard.violations(self.rules, messages, order), [])
        self.assertIn("money value not in the menu or order: 99.00",
                      " ".join(guard.violations(self.rules, ["Total: R$ 99,00"], order)))
        self.assertTrue(guard.violations(self.rules, ["Temos desconto hoje"], order))

    def test_round_trip_keeps_lines_and_fields(self):
        order = self.order()
        restored = Order.from_lead(self.rules, order.to_lead_fields())
        self.assertEqual(restored.lines[0].item_id, "x-bacon")
        self.assertEqual(restored.lines[0].qty, 2)
        self.assertEqual(restored.lines[0].extras, ["bacon"])
        self.assertEqual(restored.address, order.address)
        self.assertEqual(restored.change_for_cents, 10000)

    def test_large_order_above_the_limit(self):
        order = Order(kind="delivery")
        order.add(self.rules, "podrao", 11)
        self.assertTrue(order.over_limit(self.rules))
        self.assertEqual(brl(6200), "R$ 62,00")


if __name__ == "__main__":
    unittest.main()
