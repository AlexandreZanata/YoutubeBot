"""Load and validate the versioned lanchonete rules (`lanchonete_rules.toml`).

The menu, the extras, the fees, the payment methods and every promise live in that file.
The model may map a customer's words to catalog ids, never to a price: totals are always
calculated from the cents in this file.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

from ..sales.rules import ALLOWED_MODELS, Intent, RulesError, links_in, normalize

RULES_PATH = Path(__file__).with_name("lanchonete_rules.toml")
ACTIONS = ("reply", "menu", "handoff", "close", "cancel", "block", "ignore")
REQUIRED_INTENTS = ("opt_out", "bot_question", "human_request", "complaint", "status", "cancel",
                    "menu", "price", "item_info", "hours", "address", "delivery", "payment",
                    "no_order", "thanks", "auto_reply", "media", "unknown")
HANDOFF_ACTIONS = ("handoff",)
MONEY = re.compile(r"r\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")


def brl(cents: int) -> str:
    """1200 -> "R$ 12,00"."""
    value = int(cents)
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}R$ {value // 100},{value % 100:02d}"


def _clock(value: str, name: str) -> time:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (AttributeError, ValueError) as error:
        raise RulesError(f"{name} must be HH:MM") from error


def _alias_pattern(aliases: list[str] | tuple[str, ...]) -> re.Pattern:
    """One normalized, longest-first alternation with word edges (never inside a word)."""
    parts = sorted({normalize(alias).replace("-", " ") for alias in aliases
                    if normalize(alias)}, key=len, reverse=True)
    if not parts:
        raise RulesError("an alias list is empty")
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(part) for part in parts)
                      + r")(?![a-z0-9])")


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    category: str
    price_cents: int
    aliases: tuple[str, ...]
    description: str
    pattern: re.Pattern = field(compare=False, repr=False)

    @property
    def price(self) -> str:
        return brl(self.price_cents)


@dataclass(frozen=True)
class Extra:
    id: str
    name: str
    price_cents: int
    aliases: tuple[str, ...]
    categories: tuple[str, ...]
    pattern: re.Pattern = field(compare=False, repr=False)

    @property
    def price(self) -> str:
        return brl(self.price_cents)

    def applies_to(self, category: str) -> bool:
        return category in self.categories


@dataclass(frozen=True)
class Payment:
    id: str
    name: str
    aliases: tuple[str, ...]
    note: str
    change: bool
    pattern: re.Pattern = field(compare=False, repr=False)


@dataclass(frozen=True)
class RestaurantRules:
    raw: dict
    items: tuple[Item, ...]
    extras: tuple[Extra, ...]
    payments: tuple[Payment, ...]
    intents: tuple[Intent, ...]
    allowed_money: frozenset[str] = field(default_factory=frozenset)

    @property
    def company(self) -> str:
        return self.raw["company"]

    @property
    def agent_name(self) -> str:
        return self.raw["agent_name"]

    @property
    def address(self) -> str:
        return self.raw["address"]

    @property
    def limits(self) -> dict:
        return self.raw["limits"]

    @property
    def pacing(self) -> dict:
        return self.raw["pacing"]

    @property
    def llm(self) -> dict:
        return self.raw["llm"]

    @property
    def context(self) -> dict:
        return self.raw["context"]

    @property
    def texts(self) -> dict:
        return self.raw["texts"]

    @property
    def delivery(self) -> dict:
        return self.raw["delivery"]

    @property
    def payment_config(self) -> dict:
        return self.raw["payment"]

    @property
    def menu_category_names(self) -> dict:
        return self.raw["menu"]["categories"]

    def item(self, item_id: str) -> Item:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def extra(self, extra_id: str) -> Extra:
        for extra in self.extras:
            if extra.id == extra_id:
                return extra
        raise KeyError(extra_id)

    def payment(self, payment_id: str) -> Payment:
        for payment in self.payments:
            if payment.id == payment_id:
                return payment
        raise KeyError(payment_id)

    def intent(self, intent_id: str) -> Intent:
        for intent in self.intents:
            if intent.id == intent_id:
                return intent
        raise KeyError(intent_id)

    def has_intent(self, intent_id: str) -> bool:
        return any(intent.id == intent_id for intent in self.intents)

    def extras_for(self, category: str) -> list[Extra]:
        return [extra for extra in self.extras if extra.applies_to(category)]

    def greeting(self, now: datetime) -> str:
        greetings = self.raw["greetings"]
        if now.hour < 12:
            return greetings["morning"]
        if now.hour < 18:
            return greetings["afternoon"]
        return greetings["evening"]

    def in_window(self, now: datetime, kind: str = "ordering") -> bool:
        hours = self.raw["hours"]
        if now.weekday() not in hours[f"{kind}_days"]:
            return False
        start = _clock(hours[f"{kind}_start"], f"hours.{kind}_start")
        end = _clock(hours[f"{kind}_end"], f"hours.{kind}_end")
        return start <= now.time() < end

    def fill(self, text: str, **values) -> str:
        """Replace the owner's placeholders; prices keep their literal R$."""
        data = {"company": self.company, "agent_name": self.agent_name,
                "address": self.address}
        data.update(values)
        for key, value in data.items():
            text = text.replace("{" + key + "}", str(value))
        return text

    def facts_text(self) -> str:
        lines = []
        for group, items in self.raw["facts"].items():
            lines.append(f"[{group}]")
            lines.extend(f"- {self.fill(item)}" for item in items)
        return "\n".join(lines)

    def menu_lines(self) -> list[str]:
        lines = []
        for category, label in self.menu_category_names.items():
            lines.append(f"*{label}*")
            for item in self.items:
                if item.category == category:
                    lines.append(f"• {item.name} — {item.price}")
        return lines

    def menu_messages(self) -> list[str]:
        """The full menu as WhatsApp bubbles of at most 12 lines and 1100 characters."""
        chunks: list[list[str]] = []
        current: list[str] = []
        for category, label in self.menu_category_names.items():
            block = [f"*{label}*"]
            block += [f"• {item.name} — {item.price}" for item in self.items
                      if item.category == category]
            if not block[1:]:
                continue
            size = len("\n".join(current + block))
            if current and (len(current) + len(block) > 12 or size > 1100):
                chunks.append(current)
                current = []
            current.extend(block)
        if current:
            chunks.append(current)
        messages = ["\n".join(chunk) for chunk in chunks]
        if messages:
            messages[0] = self.fill(self.texts["menu_intro"]) + "\n\n" + messages[0]
        return messages

    def item_text(self, item: Item) -> str:
        return f"*{item.name}* — {item.price}\n{item.description}"

    def price_answer(self, items: list[Item]) -> list[str]:
        if not items:
            return [self.fill(self.texts["item_not_found"])]
        if len(items) == 1:
            item = items[0]
            extras = self.extras_for(item.category)
            text = self.item_text(item)
            if extras:
                text += "\nAdicionais: " + ", ".join(f"{extra.name} {extra.price}"
                                                    for extra in extras) + "."
            return [text]
        return ["\n".join(f"• {item.name} — {item.price}" for item in items)]

    def payment_text(self) -> str:
        lines = []
        for payment in self.payments:
            lines.append(f"• {payment.name}: {payment.note}")
        return "\n".join(lines)


def _require(raw: dict, section: str, keys: tuple[str, ...]) -> None:
    if not isinstance(raw.get(section), dict):
        raise RulesError(f"missing [{section}]")
    for key in keys:
        if key not in raw[section]:
            raise RulesError(f"missing {section}.{key}")


def _require_int(value, name: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RulesError(f"{name} must be an integer >= {minimum}")
    return value


def _texts(raw: dict) -> list[str]:
    texts = [value for value in raw.get("texts", {}).values() if isinstance(value, str)]
    for items in raw.get("facts", {}).values():
        texts.extend(items)
    for intent in raw.get("intents", []):
        texts.extend(intent.get("messages", []))
    for method in (raw.get("payment") or {}).get("methods", []):
        if method.get("note"):
            texts.append(method["note"])
    delivery = raw.get("delivery") or {}
    if delivery.get("note"):
        texts.append(delivery["note"])
    return texts


def build(raw: dict) -> RestaurantRules:
    for key in ("version", "company", "agent_name", "order_prefix", "timezone", "address",
                "tagline"):
        if not raw.get(key):
            raise RulesError(f"missing {key}")
    _require(raw, "limits", ("max_replies_per_customer_per_day", "max_bot_replies_before_owner",
                             "max_unknown", "max_confirmations", "max_messages_per_reply",
                             "max_message_chars", "max_qty_per_item", "max_extras_per_item",
                             "max_lines", "max_order_cents", "owner_reminder_minutes",
                             "closed_notice_minutes"))
    _require(raw, "hours", ("ordering_days", "ordering_start", "ordering_end"))
    _require(raw, "delivery", ("fee_cents", "free_above_cents", "min_order_cents", "estimate",
                               "pickup_estimate"))
    _require(raw, "payment", ("methods",))
    _require(raw, "pacing", ("typing_chars_per_second", "min_seconds", "max_seconds",
                             "reading_chars_per_second", "reading_min_seconds",
                             "reading_max_seconds", "jitter", "link_preview_seconds",
                             "between_chats_min_seconds", "between_chats_max_seconds"))
    _require(raw, "llm", ("base_url", "models_url", "api_key_env", "fallback", "exclude",
                          "temperature", "max_output_tokens", "timeout_seconds",
                          "free_timeout_seconds", "probe_timeout_seconds", "cooldown_seconds",
                          "no_credit_cooldown_seconds", "catalog_refresh_seconds",
                          "quick_timeout_seconds", "quick_attempts"))
    _require(raw, "greetings", ("morning", "afternoon", "evening"))
    _require(raw, "context", ("affirmative", "negative", "done", "cancel"))
    _require(raw, "facts", ())
    _require(raw, "texts", ("greeting", "menu_intro", "menu_question", "closed", "cart_empty",
                            "cart_header", "cart_subtotal", "cart_question", "ask_type",
                            "ask_address", "ask_name", "ask_payment", "ask_change",
                            "summary_intro", "summary_question", "confirmed_title",
                            "confirmed_number", "confirmed_total", "confirmed_pix",
                            "confirmed_delivery", "confirmed_pickup", "confirmed_thanks",
                            "cancelled", "cancelled_after_kitchen", "not_understood",
                            "ask_what_to_adjust", "below_min", "below_min_question",
                            "max_qty", "max_order", "swap_question", "removed_item",
                            "item_not_found", "extra_not_found", "payment_unknown",
                            "change_too_low", "handoff_ack", "correction_notice",
                            "large_order", "harassment_warn", "harassment_handoff",
                            "partial_added", "partial_missing_extra",
                            "partial_missing_item", "keep_only_question",
                            "clear_cart_question", "keep_which_question",
                            "value_jump_question", "audio_uncertain_question",
                            "alive_reply", "handoff_waiting",
                            "owner_reason_unknown", "owner_reason_confirm",
                            "owner_reason_large", "owner_reason_cancel",
                            "owner_reason_status", "owner_reason_complaint",
                            "owner_reason_human", "owner_reason_media",
                            "owner_reason_harassment", "owner_reason_waiting"))
    _require(raw, "guard", ("forbidden", "human_claims"))
    _require(raw, "context_rules", ("model_only_reads", "never_invent_item",
                                    "never_invent_price", "confirm_before_kitchen",
                                    "pix_key_only_from_owner"))
    menu = raw.get("menu")
    if not isinstance(menu, dict) or not menu.get("categories") or not menu.get("items"):
        raise RulesError("missing [menu.categories] or [[menu.items]]")
    categories = menu["categories"]
    items = []
    seen_ids = set()
    seen_aliases: dict[str, str] = {}
    for entry in menu["items"]:
        item_id = str(entry.get("id") or "").strip()
        if not item_id or item_id in seen_ids:
            raise RulesError(f"menu item id missing or repeated: {item_id!r}")
        seen_ids.add(item_id)
        category = entry.get("category")
        if category not in categories:
            raise RulesError(f"menu item {item_id}: unknown category {category!r}")
        if not str(entry.get("name") or "").strip():
            raise RulesError(f"menu item {item_id}: missing name")
        price = _require_int(entry.get("price_cents"), f"menu item {item_id}.price_cents", 1)
        aliases = tuple(str(alias).strip() for alias in entry.get("aliases", [])
                        if str(alias).strip())
        if not aliases:
            raise RulesError(f"menu item {item_id}: missing aliases")
        for alias in aliases:
            key = normalize(alias)
            if key in seen_aliases and seen_aliases[key] != item_id:
                raise RulesError(f"alias {alias!r} is used by {seen_aliases[key]} and {item_id}")
            seen_aliases[key] = item_id
        items.append(Item(item_id, str(entry["name"]).strip(), category, price, aliases,
                          str(entry.get("description") or "").strip(), _alias_pattern(aliases)))
    extras = []
    extra_ids = set()
    for entry in menu.get("extras", []):
        extra_id = str(entry.get("id") or "").strip()
        if not extra_id or extra_id in extra_ids:
            raise RulesError(f"extra id missing or repeated: {extra_id!r}")
        extra_ids.add(extra_id)
        extra_categories = tuple(entry.get("categories", []))
        if not extra_categories or any(value not in categories for value in extra_categories):
            raise RulesError(f"extra {extra_id}: unknown category")
        price = _require_int(entry.get("price_cents"), f"extra {extra_id}.price_cents", 1)
        aliases = tuple(str(alias).strip() for alias in entry.get("aliases", [])
                        if str(alias).strip())
        if not aliases:
            raise RulesError(f"extra {extra_id}: missing aliases")
        extras.append(Extra(extra_id, str(entry.get("name") or extra_id).strip(), price, aliases,
                            extra_categories, _alias_pattern(aliases)))
    payments = []
    payment_ids = set()
    for entry in raw["payment"]["methods"]:
        payment_id = str(entry.get("id") or "").strip()
        if not payment_id or payment_id in payment_ids:
            raise RulesError(f"payment id missing or repeated: {payment_id!r}")
        payment_ids.add(payment_id)
        aliases = tuple(str(alias).strip() for alias in entry.get("aliases", [])
                        if str(alias).strip())
        if not aliases:
            raise RulesError(f"payment {payment_id}: missing aliases")
        payments.append(Payment(payment_id, str(entry.get("name") or payment_id).strip(),
                                aliases, str(entry.get("note") or "").strip(),
                                bool(entry.get("change")), _alias_pattern(aliases)))
    if not payments:
        raise RulesError("payment.methods must not be empty")
    if "pix" not in payment_ids:
        raise RulesError("payment.methods needs pix")

    intents = []
    seen_intents = set()
    for entry in raw.get("intents", []):
        intent_id = entry.get("id")
        if not intent_id or intent_id in seen_intents:
            raise RulesError(f"intent id missing or repeated: {intent_id!r}")
        seen_intents.add(intent_id)
        action = entry.get("action")
        if action not in ACTIONS:
            raise RulesError(f"intent {intent_id}: action must be one of {', '.join(ACTIONS)}")
        if action not in ("menu", "ignore") and not entry.get("messages"):
            raise RulesError(f"intent {intent_id}: action {action} needs messages")
        if action in HANDOFF_ACTIONS and not entry.get("reason"):
            raise RulesError(f"intent {intent_id}: a hand-off needs a reason for the owner")
        try:
            patterns = tuple(re.compile(pattern) for pattern in entry.get("patterns", []))
        except re.error as error:
            raise RulesError(f"intent {intent_id}: bad pattern ({error})") from error
        priority = entry.get("priority", "needed")
        if priority not in ("hot", "needed", "alert"):
            raise RulesError(f"intent {intent_id}: bad priority")
        intents.append(Intent(intent_id, action, bool(entry.get("fixed", True)),
                              entry.get("when", ""), patterns,
                              tuple(entry.get("messages", [])), priority,
                              entry.get("reason", "")))
    missing = [intent for intent in REQUIRED_INTENTS if intent not in seen_intents]
    if missing:
        raise RulesError(f"missing intents: {', '.join(missing)}")
    if next(intent for intent in intents if intent.id == "opt_out").action != "block":
        raise RulesError("intent opt_out must use action block")
    for key in ("affirmative", "negative", "done", "cancel", "change_exact"):
        for pattern in raw["context"].get(key, []):
            try:
                re.compile(pattern)
            except re.error as error:
                raise RulesError(f"context.{key}: bad pattern ({error})") from error

    delivery = raw["delivery"]
    fee = _require_int(delivery["fee_cents"], "delivery.fee_cents")
    free_above = _require_int(delivery["free_above_cents"], "delivery.free_above_cents")
    minimum = _require_int(delivery["min_order_cents"], "delivery.min_order_cents")
    if not fee or free_above <= 0 or minimum <= 0:
        raise RulesError("delivery values must be positive")
    if free_above < minimum:
        raise RulesError("delivery.free_above_cents must be >= delivery.min_order_cents")
    limits = raw["limits"]
    for key in ("max_replies_per_customer_per_day", "max_bot_replies_before_owner",
                "max_messages_per_reply", "max_message_chars", "max_qty_per_item",
                "max_extras_per_item", "max_lines", "max_order_cents", "owner_reminder_minutes",
                "closed_notice_minutes", "max_unknown", "max_confirmations"):
        _require_int(limits[key], f"limits.{key}", 1)
    if int(limits["max_messages_per_reply"]) < 1:
        raise RulesError("limits.max_messages_per_reply must be positive")
    pacing = raw["pacing"]
    if not 0 < float(pacing["min_seconds"]) <= float(pacing["max_seconds"]):
        raise RulesError("pacing.min_seconds must be positive and not above max_seconds")
    _clock(raw["hours"]["ordering_start"], "hours.ordering_start")
    _clock(raw["hours"]["ordering_end"], "hours.ordering_end")
    fallback = raw["llm"]["fallback"]
    if not fallback or any(model not in ALLOWED_MODELS for model in fallback):
        raise RulesError(f"llm.fallback may only use {', '.join(ALLOWED_MODELS)}")
    for key in ("base_url", "models_url"):
        if not str(raw["llm"][key]).startswith("https://opencode.ai/"):
            raise RulesError(f"llm.{key} must be an https://opencode.ai/ address")
    allowed = {f"{value // 100}.{value % 100:02d}"
               for value in [item.price_cents for item in items]
               + [extra.price_cents for extra in extras] + [fee, free_above, minimum]}
    for text in _texts(raw):
        for whole, cents in MONEY.findall(normalize(text)):
            value = f"{int(whole.replace('.', ''))}.{(cents or '0').ljust(2, '0')}"
            if value not in allowed:
                raise RulesError(f"money value {value} is not in the menu, extras or fees: {text}")
        if links_in(text):
            raise RulesError(f"the rules may not contain links: {text[:80]}")
    return RestaurantRules(raw, tuple(items), tuple(extras), tuple(payments), tuple(intents),
                           frozenset(allowed))


def load(path: Path | None = None) -> RestaurantRules:
    path = path or RULES_PATH
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RulesError(f"cannot read {path.name}: {error}") from error
    return build(raw)


__all__ = ["RULES_PATH", "Extra", "Item", "Payment", "RestaurantRules", "RulesError", "brl",
           "build", "load", "normalize"]
