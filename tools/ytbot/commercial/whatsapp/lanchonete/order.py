"""The order being assembled: lines, extras, fees, payment, change and the order ficha.

Every amount is calculated here from the catalog in `lanchonete_rules.toml`; a model never
supplies a price. The same object renders the WhatsApp summary the customer confirms and the
`pedido.md` the kitchen receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .rules import Item, RestaurantRules, brl


class OrderError(ValueError):
    """The requested change cannot be applied to this order."""


def _line_extras(rules: RestaurantRules, item: Item, extra_ids) -> list[str]:
    allowed = {extra.id: extra for extra in rules.extras_for(item.category)}
    result = []
    for extra_id in extra_ids:
        if extra_id in allowed and extra_id not in result:
            result.append(extra_id)
    return result


@dataclass
class Line:
    item_id: str
    qty: int = 1
    extras: list[str] = field(default_factory=list)
    note: str = ""

    def item(self, rules: RestaurantRules) -> Item:
        return rules.item(self.item_id)

    def extra_objects(self, rules: RestaurantRules) -> list:
        return [rules.extra(extra_id) for extra_id in self.extras]

    def unit_cents(self, rules: RestaurantRules) -> int:
        return self.item(rules).price_cents + sum(
            extra.price_cents for extra in self.extra_objects(rules))

    def total_cents(self, rules: RestaurantRules) -> int:
        return self.unit_cents(rules) * self.qty

    def same_as(self, other: "Line") -> bool:
        return (self.item_id == other.item_id and sorted(self.extras) == sorted(other.extras)
                and self.note.strip().casefold() == other.note.strip().casefold())

    def label(self, rules: RestaurantRules) -> str:
        text = self.item(rules).name
        extras = self.extra_objects(rules)
        if extras:
            text += " (" + ", ".join(extra.name for extra in extras) + ")"
        return text

    def to_dict(self) -> dict:
        return {"item_id": self.item_id, "qty": self.qty, "extras": list(self.extras),
                "note": self.note}


@dataclass(frozen=True)
class Totals:
    subtotal_cents: int
    delivery_fee_cents: int
    total_cents: int
    missing_min_cents: int = 0
    change_due_cents: int | None = None
    change_too_low: bool = False


@dataclass
class Order:
    lines: list[Line] = field(default_factory=list)
    kind: str = ""                     # delivery | pickup
    customer_name: str = ""
    address: str = ""
    payment: str = ""                  # pix | cash | card
    change_for_cents: int | None = None
    change_exact: bool = False
    note: str = ""
    number: str = ""
    status: str = "draft"              # draft | confirmed | cancelled | closed
    created_at: str = ""
    confirmed_at: str = ""

    # Lines -------------------------------------------------------------------------
    def add(self, rules: RestaurantRules, item_id: str, qty: int = 1,
            extras: list[str] | tuple[str, ...] = (), note: str = "") -> Line:
        item = rules.item(item_id)
        qty = int(qty)
        if qty < 1:
            raise OrderError("quantity must be at least 1")
        extras = _line_extras(rules, item, extras)
        if len(extras) > int(rules.limits["max_extras_per_item"]):
            raise OrderError("too many extras")
        note = (note or "").strip()[:60]
        new = Line(item_id, qty, extras, note)
        for line in self.lines:
            if line.same_as(new):
                line.qty += qty
                return line
        self.lines.append(new)
        return new

    def remove(self, rules: RestaurantRules, item_id: str, qty: int | None = None) -> int:
        rules.item(item_id)
        removed = 0
        kept = []
        for line in self.lines:
            if line.item_id != item_id:
                kept.append(line)
                continue
            if qty is None:
                removed += line.qty
                continue
            take = min(line.qty, qty - removed)
            removed += take
            if take < line.qty:
                line.qty -= take
                kept.append(line)
        self.lines = kept
        return removed

    def add_extra(self, rules: RestaurantRules, item_id: str, extra_id: str) -> None:
        """Add an extra to every line of an item already in the cart."""
        target = [line for line in self.lines if line.item_id == item_id]
        if not target:
            raise OrderError("item not in the cart")
        try:
            rules.extra(extra_id)
        except KeyError as error:
            raise OrderError(f"unknown extra {extra_id}") from error
        for line in target:
            if extra_id not in line.extras:
                line.extras.append(extra_id)

    def is_empty(self) -> bool:
        return not self.lines

    def line_count(self) -> int:
        return len(self.lines)

    # Totals ------------------------------------------------------------------------
    def totals(self, rules: RestaurantRules) -> Totals:
        subtotal = sum(line.total_cents(rules) for line in self.lines)
        fee = 0
        missing = 0
        if self.kind == "delivery" and self.lines:
            if subtotal >= int(rules.delivery["free_above_cents"]):
                fee = 0
            else:
                fee = int(rules.delivery["fee_cents"])
            minimum = int(rules.delivery["min_order_cents"])
            if subtotal < minimum:
                missing = minimum - subtotal
        total = subtotal + fee
        change_due = None
        too_low = False
        if self.payment == "cash" and self.change_for_cents is not None:
            change_due = self.change_for_cents - total
            too_low = change_due < 0
        if self.payment == "cash" and self.change_exact:
            change_due = 0
        return Totals(subtotal, fee, total, missing, change_due, too_low)

    def total_cents(self, rules: RestaurantRules) -> int:
        return self.totals(rules).total_cents

    def over_limit(self, rules: RestaurantRules) -> bool:
        totals = self.totals(rules)
        return (self.line_count() > int(rules.limits["max_lines"])
                or totals.total_cents > int(rules.limits["max_order_cents"]))

    # Rendering ---------------------------------------------------------------------
    def kind_label(self) -> str:
        return {"delivery": "entrega", "pickup": "retirada"}.get(self.kind, "")

    def payment_label(self, rules: RestaurantRules) -> str:
        return rules.payment(self.payment).name if self.payment else ""

    def items_text(self, rules: RestaurantRules) -> str:
        return "\n".join(f"• {line.qty}x {line.label(rules)} — {brl(line.total_cents(rules))}"
                         + (f"\n  Obs: {line.note}" if line.note else "")
                         for line in self.lines)

    def cart_text(self, rules: RestaurantRules) -> str:
        totals = self.totals(rules)
        parts = [rules.fill(rules.texts["cart_header"]), self.items_text(rules),
                 rules.fill(rules.texts["cart_subtotal"], subtotal=brl(totals.subtotal_cents))]
        return "\n".join(part for part in parts if part)

    def summary_text(self, rules: RestaurantRules) -> str:
        """The complete order the customer confirms before it reaches the kitchen."""
        totals = self.totals(rules)
        parts = [rules.fill(rules.texts["summary_intro"]), ""]
        if self.kind:
            parts.append(f"*Pedido:* {self.kind_label()}")
        if self.customer_name:
            parts.append(f"*Nome:* {self.customer_name}")
        if self.kind == "delivery" and self.address:
            parts.append(f"*Endereço:* {self.address}")
        parts += ["*Itens:*", self.items_text(rules),
                  f"*Subtotal:* {brl(totals.subtotal_cents)}"]
        if self.kind == "delivery":
            fee = ("sem taxa" if totals.delivery_fee_cents == 0
                   else brl(totals.delivery_fee_cents))
            parts.append(f"*Entrega:* {fee}")
        parts.append(f"*Total:* {brl(totals.total_cents)}")
        if self.payment:
            payment = f"*Pagamento:* {self.payment_label(rules)}"
            if self.payment == "cash" and self.change_exact:
                payment += " — sem troco"
            elif self.payment == "cash" and self.change_for_cents is not None:
                payment += f" — troco para {brl(self.change_for_cents)}"
                if totals.change_due_cents is not None and totals.change_due_cents > 0:
                    payment += f" (troco de {brl(totals.change_due_cents)})"
                elif totals.change_due_cents == 0:
                    payment += " (sem troco)"
            parts.append(payment)
        return "\n".join(parts)

    def ficha_markdown(self, rules: RestaurantRules, customer: dict, now: datetime,
                       agent_name: str) -> str:
        totals = self.totals(rules)
        lines = [f"# Pedido {self.number} — {rules.company}", "",
                 f"- Status: {self.status}",
                 f"- Confirmado em: {self.confirmed_at or now.isoformat(timespec='seconds')}",
                 f"- Cliente: {self.customer_name or customer.get('name', '')}",
                 f"- WhatsApp: {customer.get('phone') or customer.get('chat', '')}",
                 f"- Tipo: {self.kind_label() or 'não informado'}"]
        if self.address:
            lines.append(f"- Endereço: {self.address}")
        if self.payment:
            lines.append(f"- Pagamento: {self.payment_label(rules)}")
        if self.payment == "cash" and self.change_exact:
            lines.append("- Troco: sem troco (valor exato)")
        elif self.payment == "cash" and self.change_for_cents is not None:
            lines.append(f"- Troco para: {brl(self.change_for_cents)}")
            if totals.change_due_cents is not None and totals.change_due_cents >= 0:
                lines.append(f"- Troco a devolver: {brl(totals.change_due_cents)}")
        lines += ["", "## Itens", ""]
        for line in self.lines:
            item = line.item(rules)
            lines.append(f"- {line.qty}x {item.name} — unitário {brl(item.price_cents)}")
            for extra in line.extra_objects(rules):
                lines.append(f"  - {extra.name} — {brl(extra.price_cents)} por unidade")
            if line.note:
                lines.append(f"  - Observação: {line.note}")
            lines.append(f"  - Total do item: {brl(line.total_cents(rules))}")
        fee = ("sem taxa" if not totals.delivery_fee_cents
               else brl(totals.delivery_fee_cents))
        lines += ["", "## Totais", "",
                  f"- Subtotal: {brl(totals.subtotal_cents)}",
                  f"- Taxa de entrega: {fee}",
                  f"- **Total: {brl(totals.total_cents)}**"]
        if totals.missing_min_cents:
            lines.append(f"- Abaixo do pedido mínimo de entrega em {brl(totals.missing_min_cents)}")
        if self.note:
            lines += ["", "## Observações", "", self.note]
        lines += ["", "## Conversa", "", f"Atendimento por {agent_name}."]
        return "\n".join(lines) + "\n"

    # Persistence -------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"number": self.number, "status": self.status, "kind": self.kind,
                "customer_name": self.customer_name, "address": self.address,
                "payment": self.payment, "change_for_cents": self.change_for_cents,
                "change_exact": self.change_exact, "note": self.note,
                "created_at": self.created_at, "confirmed_at": self.confirmed_at,
                "lines": [line.to_dict() for line in self.lines]}

    def with_totals(self, rules: RestaurantRules) -> dict:
        totals = self.totals(rules)
        data = self.to_dict()
        data["totals"] = {"subtotal_cents": totals.subtotal_cents,
                          "delivery_fee_cents": totals.delivery_fee_cents,
                          "total_cents": totals.total_cents,
                          "missing_min_cents": totals.missing_min_cents,
                          "change_due_cents": totals.change_due_cents}
        return data

    @classmethod
    def from_lead(cls, rules: RestaurantRules, lead: dict) -> "Order":
        return cls.from_dict(rules, {
            "lines": lead.get("cart") or [], "kind": lead.get("order_kind") or "",
            "customer_name": lead.get("order_name") or "",
            "address": lead.get("order_address") or "",
            "payment": lead.get("order_payment") or "",
            "change_for_cents": lead.get("order_change_for_cents"),
            "change_exact": bool(lead.get("order_change_exact")),
            "note": lead.get("order_note") or "",
            "number": lead.get("order_number") or "",
        })

    @classmethod
    def from_dict(cls, rules: RestaurantRules, data: dict | None) -> "Order":
        data = data or {}
        order = cls(kind=str(data.get("kind") or ""),
                    customer_name=str(data.get("customer_name") or ""),
                    address=str(data.get("address") or ""),
                    payment=str(data.get("payment") or ""),
                    change_for_cents=data.get("change_for_cents"),
                    change_exact=bool(data.get("change_exact")),
                    note=str(data.get("note") or ""),
                    number=str(data.get("number") or ""),
                    status=str(data.get("status") or "draft"),
                    created_at=str(data.get("created_at") or ""),
                    confirmed_at=str(data.get("confirmed_at") or ""))
        for raw in data.get("lines", []):
            try:
                item = rules.item(str(raw.get("item_id") or ""))
            except KeyError:
                continue
            qty = max(1, min(int(raw.get("qty") or 1), int(rules.limits["max_qty_per_item"])))
            extras = _line_extras(rules, item, raw.get("extras") or [])
            order.lines.append(Line(item.id, qty, extras,
                                    str(raw.get("note") or "")[:60]))
        return order

    def to_lead_fields(self) -> dict:
        return {"cart": [line.to_dict() for line in self.lines], "order_kind": self.kind,
                "order_name": self.customer_name, "order_address": self.address,
                "order_payment": self.payment,
                "order_change_for_cents": self.change_for_cents,
                "order_change_exact": self.change_exact, "order_note": self.note}


def order_number(prefix: str, now: datetime, sequence: int) -> str:
    return f"{prefix}-{now.strftime('%Y%m%d')}-{sequence:03d}"


__all__ = ["Line", "Order", "OrderError", "Totals", "order_number"]
