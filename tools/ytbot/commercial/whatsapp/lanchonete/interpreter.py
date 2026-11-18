"""Optional model reading for free-form orders ("me vê dois lanches e uma coca").

The model only picks catalog ids and field values. Anything outside the catalog, outside the
limits or with an invented price rejects the whole answer, and the deterministic parser or the
fixed question handles the turn. This keeps the kitchen safe from a hallucinated item.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .order import Order
from .parser import FORBIDDEN_NOTE, Parsed, ParsedItem, parse_change
from .rules import RestaurantRules, normalize

CONTEXT_PATH = Path(__file__).with_name("context.md")
SET_FIELDS = ("type", "name", "address", "payment", "change_for")
TYPE_VALUES = {"delivery": "delivery", "entrega": "delivery", "pickup": "pickup",
               "retirada": "pickup", "retirar": "pickup"}


def _menu(rules: RestaurantRules) -> str:
    return "\n".join(f"- {item.id} | {item.name} | {item.price} | {item.description}"
                     for item in rules.items)


def _extras(rules: RestaurantRules) -> str:
    return "\n".join(f"- {extra.id} | {extra.name} | {extra.price} | "
                     f"{', '.join(extra.categories)}" for extra in rules.extras)


def _payments(rules: RestaurantRules) -> str:
    return "\n".join(f"- {payment.id} | {payment.name}" for payment in rules.payments)


def _cart(rules: RestaurantRules, order: Order) -> str:
    if order.is_empty():
        return "(vazio)"
    lines = [order.cart_text(rules)]
    fields = []
    if order.kind:
        fields.append(f"tipo: {order.kind_label()}")
    if order.customer_name:
        fields.append(f"nome: {order.customer_name}")
    if order.address:
        fields.append(f"endereço: {order.address}")
    if order.payment:
        fields.append(f"pagamento: {order.payment_label(rules)}")
    if fields:
        lines.append("campos: " + "; ".join(fields))
    return "\n".join(lines)


def missing_fields(rules: RestaurantRules, order: Order) -> list[str]:
    missing = []
    if order.is_empty():
        missing.append("itens")
    if not order.kind:
        missing.append("entrega ou retirada")
    if order.kind == "delivery" and not order.address:
        missing.append("endereço")
    if not order.customer_name:
        missing.append("nome")
    if not order.payment:
        missing.append("pagamento")
    if order.payment == "cash" and order.change_for_cents is None and not order.change_exact:
        missing.append("troco")
    if order.kind == "delivery" and order.totals(rules).missing_min_cents:
        missing.append("mais itens para o pedido mínimo")
    return missing


def build_prompt(rules: RestaurantRules, order: Order, text: str) -> list[dict]:
    try:
        template = CONTEXT_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"cannot read {CONTEXT_PATH.name}: {error}") from error
    system = (template
              .replace("{company}", rules.company)
              .replace("{agent_name}", rules.agent_name)
              .replace("{menu}", _menu(rules))
              .replace("{extras}", _extras(rules))
              .replace("{payments}", _payments(rules))
              .replace("{facts}", rules.facts_text())
              .replace("{cart}", _cart(rules, order))
              .replace("{missing}", "\n".join(f"- {item}" for item in
                                              missing_fields(rules, order)) or "- nenhum"))
    return [{"role": "system", "content": system},
            {"role": "user", "content": text.strip()}]


def _json(content: str) -> dict:
    value = (content or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model output has no JSON object")
    data = json.loads(value[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not an object")
    return data


def _note(value) -> str:
    text = re.sub(r"\br\$?\s*\d+(?:[,.]\d+)?\b", "", str(value or "")).strip()[:60]
    return "" if FORBIDDEN_NOTE.search(text.casefold()) else text


def _validate(rules: RestaurantRules, data: dict) -> Parsed:
    if data.get("uncertain") is True:
        raise ValueError("model is uncertain")
    result = Parsed()
    items = data.get("items") or []
    removes = data.get("remove") or []
    if not isinstance(items, list) or not isinstance(removes, list):
        raise ValueError("items and remove must be lists")
    if len(items) + len(removes) > int(rules.limits["max_lines"]):
        raise ValueError("too many lines")
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("item is not an object")
        item = rules.item(str(raw.get("id") or ""))
        qty = raw.get("qty", 1)
        if isinstance(qty, str) and qty.strip().isdigit():
            qty = int(qty.strip())
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ValueError("bad quantity")
        if qty > int(rules.limits["max_qty_per_item"]):
            raise ValueError("quantity above the limit")
        extras = []
        for extra_id in raw.get("extras") or []:
            extra = rules.extra(str(extra_id))
            if not extra.applies_to(item.category):
                raise ValueError(f"extra {extra.id} does not apply to {item.id}")
            if extra.id not in extras:
                extras.append(extra.id)
        if len(extras) > int(rules.limits["max_extras_per_item"]):
            raise ValueError("too many extras")
        result.items.append(ParsedItem(item.id, qty, extras, _note(raw.get("note"))))
    for raw in removes:
        if not isinstance(raw, dict):
            raise ValueError("remove is not an object")
        item = rules.item(str(raw.get("id") or ""))
        qty = raw.get("qty", 1)
        if qty is not None and (not isinstance(qty, int) or isinstance(qty, bool) or qty < 1):
            raise ValueError("bad remove quantity")
        result.items.append(ParsedItem(item.id, qty or 1, remove=True))
    fields = data.get("set") or {}
    if not isinstance(fields, dict):
        raise ValueError("set is not an object")
    unknown = set(fields) - set(SET_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    kind = str(fields.get("type") or "").strip().casefold()
    if kind:
        if kind not in TYPE_VALUES:
            raise ValueError("bad order type")
        result.fields["kind"] = TYPE_VALUES[kind]
    name = str(fields.get("name") or "").strip()[:60]
    if name:
        result.fields["name"] = name
    address = str(fields.get("address") or "").strip()[:200]
    if address:
        result.fields["address"] = address
    payment = normalize(str(fields.get("payment") or "")).strip()
    if payment:
        found = next((method.id for method in rules.payments
                      if payment == method.id or payment == normalize(method.name)
                      or payment in [normalize(alias) for alias in method.aliases]), "")
        if not found:
            raise ValueError("bad payment")
        result.fields["payment"] = found
    change = str(fields.get("change_for") or "").strip()
    if change:
        cents, exact = parse_change(change)
        if exact:
            result.fields["change_exact"] = True
        elif cents is not None:
            result.fields["change_for_cents"] = cents
    if data.get("done") is True:
        result.done = True
    if data.get("cancel") is True:
        result.cancel = True
    return result


def interpret(rules: RestaurantRules, order: Order, text: str, llm, now: datetime,
              usage=None, session_id: str = "") -> tuple[Parsed | None, str]:
    """The parsed order from the model; (None, error) never raises for a model problem."""
    if llm is None:
        return None, "no model"
    try:
        reply = llm.complete(build_prompt(rules, order, text),
                             session_id=session_id or f"brasa-pao-{now.strftime('%Y%m%d')}",
                             quick=True)
    except Exception as error:  # the model must never stop the conversation
        return None, str(error)[:200]
    if usage is not None:
        usage({"at": now.isoformat(timespec="seconds"), "kind": "order",
               "model": reply.model, "input_tokens": reply.input_tokens,
               "output_tokens": reply.output_tokens, "cost_usd": reply.cost_usd,
               "duration_ms": reply.duration_ms})
    try:
        return _validate(rules, _json(reply.content)), ""
    except (ValueError, KeyError) as error:
        return None, f"invalid model order: {error}"


__all__ = ["build_prompt", "interpret", "missing_fields"]
