"""Private lanchonete state: customers, conversations and confirmed order fichas.

It reuses `SalesStore`'s locking, phone validation, do-not-contact hashes, journal and contact
rules, with its own root (`.local/commercial/whatsapp/lanchonete/`). The sales funnel is never
touched.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from ..sales import dossier
from ..sales.store import SalesStore, _private_dir, _read_json, _write_json, canonical_phone, \
    phone_key, stamp
from .order import Order, order_number
from .rules import RestaurantRules


class LanchoneteStore(SalesStore):
    """One WhatsApp account, restaurant state; private files under 0700/0600."""

    def __init__(self, base: Path):
        super().__init__(base, root_name="lanchonete")
        self.orders_path = self.root / "pedidos.json"
        self.orders_dir = self.root / "pedidos"
        self.customers_dir = self.root / "clientes"

    # Customers -----------------------------------------------------------------------
    def ensure_customer(self, chat: str, now: datetime) -> dict:
        """The inbound chat's customer; any chat with a phone is accepted, names are allowed."""
        known = self.find_lead(chat)
        if known is not None:
            return known
        phone = canonical_phone(chat) or ""
        key = phone_key(phone) if phone else normalize(chat)
        identifier = "C" + hashlib.sha256(f"customer:{key}".encode()).hexdigest()[:10]
        leads = self.ensure_labels(self.leads())
        if identifier in leads:
            return leads[identifier]
        label = self._next_label(leads)
        leads[identifier] = {
            "id": identifier, "name": chat.strip(), "phone": phone, "chat": chat.strip(),
            "label": label, "category": "lanchonete", "city": "", "maps_url": "", "note": "",
            "contact_name": chat.strip(), "source": "whatsapp-inbound",
            "state": "do-not-contact" if phone and self.is_dnc(phone) else "new",
            "imported_at": stamp(now), "created_at": stamp(now), "opened_at": None,
            "followups": 0, "last_out_at": None, "last_in_at": None, "awaiting": None,
            "replies": {}, "handoff_reason": None, "bot_replies": 0, "unknown_count": 0,
            "confirmations": 0, "awaiting_field": "", "closing": False, "cart": [],
            "order_kind": "",
            "order_name": "", "order_address": "", "order_payment": "",
            "order_change_for_cents": None, "order_change_exact": False, "order_note": "",
            "order_number": "", "ficha": "", "closed_notice_at": None,
        }
        self.save_leads(leads)
        return leads[identifier]

    @staticmethod
    def _next_label(leads: dict[str, dict]) -> str:
        used = 0
        for lead in leads.values():
            match = re.fullmatch(r"cliente-(\d+)", lead.get("label") or "")
            if match:
                used = max(used, int(match.group(1)))
        return f"cliente-{used + 1}"

    def is_blocked(self, customer: dict) -> bool:
        if customer.get("state") == "do-not-contact":
            return True
        if customer.get("phone"):
            return self.is_dnc(customer["phone"])
        return False

    def block_customer(self, customer: dict, reason: str, now: datetime) -> dict:
        if customer.get("phone"):
            self.add_dnc(customer["phone"], reason, now)
        return self.update_lead(customer["id"], state="do-not-contact", awaiting=None)

    def customer_dir(self, customer: dict) -> Path:
        return dossier.client_dir(self.root, customer)

    # Orders --------------------------------------------------------------------------
    def orders(self) -> list[dict]:
        data = _read_json(self.orders_path, {})
        return data.get("orders", []) if isinstance(data, dict) else []

    def next_order_number(self, rules: RestaurantRules, now: datetime) -> str:
        prefix = f"{rules.raw['order_prefix']}-{now.strftime('%Y%m%d')}-"
        used = 0
        for entry in self.orders():
            number = str(entry.get("number") or "")
            if number.startswith(prefix):
                try:
                    used = max(used, int(number.rsplit("-", 1)[-1]))
                except ValueError:
                    continue
        if self.orders_dir.is_dir():
            for folder in self.orders_dir.iterdir():
                number = folder.name
                if number.startswith(prefix):
                    try:
                        used = max(used, int(number.rsplit("-", 1)[-1]))
                    except ValueError:
                        continue
        return order_number(rules.raw["order_prefix"], now, used + 1)

    def save_order(self, rules: RestaurantRules, order: Order, customer: dict,
                   history: list[dict], now: datetime,
                   agent_name: str | None = None) -> Path:
        """Write pedido.md, pedido.json and conversa.md; idempotent by order number."""
        folder = self.orders_dir / order.number
        _private_dir(self.orders_dir)
        _private_dir(folder)
        transcript = dossier.transcript(history, agent_name or rules.agent_name)
        outputs = {
            "pedido.md": order.ficha_markdown(rules, customer, now,
                                              agent_name or rules.agent_name),
            "pedido.json": json.dumps(order.with_totals(rules), ensure_ascii=False, indent=2)
            + "\n",
            "conversa.md": "# Conversa do pedido\n\n" + "\n".join(transcript) + "\n",
        }
        for name, content in outputs.items():
            path = folder / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
        self._index_order(rules, order, customer, now, folder)
        return folder / "pedido.md"

    def _index_order(self, rules: RestaurantRules, order: Order, customer: dict,
                     now: datetime, folder: Path) -> None:
        entries = self.orders()
        if any(entry.get("number") == order.number for entry in entries):
            return
        totals = order.totals(rules)
        entries.append({
            "number": order.number, "at": order.confirmed_at or stamp(now),
            "status": order.status, "customer": order.customer_name or customer.get("name", ""),
            "chat": customer.get("chat", ""), "phone": customer.get("phone", ""),
            "kind": order.kind, "payment": order.payment,
            "total_cents": totals.total_cents,
            "total": f"R$ {totals.total_cents // 100},{totals.total_cents % 100:02d}",
            "items": [{"item": line.item_id, "qty": line.qty, "extras": line.extras,
                       "note": line.note} for line in order.lines],
            "folder": str(folder), "ficha": str(folder / "pedido.md"),
        })
        _write_json(self.orders_path, {"version": 1, "orders": entries})

    def orders_today(self, rules: RestaurantRules, now: datetime) -> list[dict]:
        prefix = f"{rules.raw['order_prefix']}-{now.strftime('%Y%m%d')}-"
        return [entry for entry in self.orders()
                if str(entry.get("number") or "").startswith(prefix)]


__all__ = ["LanchoneteStore"]
