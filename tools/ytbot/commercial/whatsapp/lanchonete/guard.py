"""Checks every outgoing message against the menu, fees, limits and forbidden claims.

The bot writes the texts; this guard is the last line between a bug (or a future model-written
sentence) and the customer. A money value that is not in the catalog, in the delivery fees or
in the order being shown blocks the message batch.
"""

from __future__ import annotations

import re

from ..sales.rules import links_in, money_values, normalize
from .order import Order
from .rules import RestaurantRules

EMAIL = re.compile(r"@")
PERCENT = re.compile(r"%")


def _term(term: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])")


def order_values(order: Order, rules: RestaurantRules) -> set[str]:
    """Every amount the summary legitimately shows, as "62.00" strings."""
    totals = order.totals(rules)
    cents = {totals.subtotal_cents, totals.delivery_fee_cents, totals.total_cents,
             int(rules.delivery["fee_cents"]), int(rules.delivery["free_above_cents"]),
             int(rules.delivery["min_order_cents"]), totals.missing_min_cents}
    if order.change_for_cents is not None:
        cents.add(order.change_for_cents)
    if totals.change_due_cents is not None:
        cents.add(totals.change_due_cents)
    for line in order.lines:
        cents.add(line.unit_cents(rules))
        cents.add(line.total_cents(rules))
        for extra in line.extra_objects(rules):
            cents.add(extra.price_cents)
    return {f"{value // 100}.{value % 100:02d}" for value in cents if value > 0}


def violations(rules: RestaurantRules, messages: list[str],
               order: Order | None = None) -> list[str]:
    """Every reason the batch may not be sent; empty means safe."""
    problems: list[str] = []
    limits = rules.limits
    if not messages:
        problems.append("no messages")
    if len(messages) > int(limits["max_messages_per_reply"]):
        problems.append(f"more than {limits['max_messages_per_reply']} messages")
    allowed_money = set(rules.allowed_money)
    if order is not None:
        allowed_money |= order_values(order, rules)
    forbidden = [(term, _term(term)) for term in rules.raw["guard"]["forbidden"]]
    claims = [re.compile(pattern) for pattern in rules.raw["guard"]["human_claims"]]
    for message in messages:
        plain = normalize(message)
        if not plain:
            problems.append("empty message")
            continue
        if len(message) > int(limits["max_message_chars"]):
            problems.append(f"message longer than {limits['max_message_chars']} characters")
        if links_in(message):
            problems.append("links are not part of the restaurant rules")
        if EMAIL.search(message):
            problems.append("e-mail or handle")
        if PERCENT.search(message):
            problems.append("percentage")
        without_links = re.sub(r"https?://\S+", " ", plain)
        for value in money_values(without_links):
            if value not in allowed_money:
                problems.append(f"money value not in the menu or order: {value}")
        for term, pattern in forbidden:
            if pattern.search(plain):
                problems.append(f"forbidden term: {term}")
        for pattern in claims:
            if pattern.search(plain):
                problems.append("claims to be human")
    return sorted(set(problems))


__all__ = ["order_values", "violations"]
