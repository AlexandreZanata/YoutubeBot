"""WhatsApp ordering agent for Brasa & Pão.

new ─▶ ordering ──"só isso"──▶ asks the missing fields ─▶ confirming ──SIM──▶ confirmed
  │        │                                                  │
  │        └─ refusal/opt-out ─▶ do-not-contact                └─ correction ─▶ updated summary
  └─ outside hours ─▶ closed (one notice per window)

The bot only replies to people who wrote first. Every reply is built from the rules file; the
model, when configured, only reads free-form text into catalog ids. A confirmed order is written
as a ficha under `.local/commercial/whatsapp/lanchonete/pedidos/<number>/` and sent to the owner
before the kitchen starts.
"""

from __future__ import annotations

import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, time as clock_time, timedelta
from zoneinfo import ZoneInfo

from .. import listener, sender
from ..sales import dossier
from ..sales import notify as owner_notify
from ..sales.agent import WhatsAppChannel, split_pending
from ..sales.commands import is_closed
from ..sales.pacing import SalesPacing
from ..sales.rules import normalize
from . import guard, interpreter, parser
from .order import Order, OrderError
from .rules import RestaurantRules, brl
from .store import LanchoneteStore, canonical_phone, phone_key
from ..sales.transcribe import local_transcriber

REPLYABLE = ("new", "ordering", "confirming", "closed", "cancelled")
OWNER_STATES = ("human", "confirmed", "needs-owner", "unconfirmed")
FAQ = ("menu", "price", "item_info", "hours", "address", "delivery", "payment")
FIELDS = ("type", "address", "name", "payment", "change")
GROUP_PREFIX = re.compile(r"^\s*[^:\n]{2,40}:\s")
MEDIA_TEXT = {"image": "[imagem]", "video": "[vídeo]", "document": "[documento]",
              "audio": "[áudio]"}
# A comparative ("mais barato", "o menor", "troca ... por") or an explicit rejection
# ("não o de 500") never adds blindly: the cart decides between swap proposal and removal.
REPLACE_CUE = re.compile(r"\b(mais barat\w*|mais em conta|menor|menores|o pequeno|a pequena|"
                         r"troca|trocar|substitu\w*|ao inves|em vez de|no lugar de|"
                         r"nao (o|a|esse|essa|esses|essas)\b)")
NEG_REF = re.compile(r"\bnao(?: quero)? (o|a|esse|essa|esses|essas)"
                     r"(\s+(de|da|do|das|dos))?\s*"
                     r"(\d{2,4}\s?(?:ml|g)?|[a-zà-ÿ]{3,})")


TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9]+")


def _tokens(value: str) -> list[tuple[str, int, int]]:
    result = []
    for match in TOKEN.finditer(value or ""):
        plain = unicodedata.normalize("NFKD", match.group(0))
        plain = "".join(char for char in plain if not unicodedata.combining(char)).casefold()
        result.append((plain, match.start(), match.end()))
    return result


def clean_incoming(text: str, outgoing: list[str]) -> str:
    """Drop a quoted bot bubble from the text WhatsApp gives us for an incoming message.

    A reply quotes the old bubble above the new text. WhatsApp flattens both into one
    string, so a quote of the cart used to be read as a second order and doubled every item.
    The longest shared token run at the start identifies the quote; the actual reply remains.
    """
    if not text:
        return text
    result = text
    out_tokens = [_tokens(item) for item in outgoing if item]
    for _ in range(3):
        incoming = _tokens(result)
        if not incoming or not out_tokens:
            break
        best = 0
        for tokens in out_tokens:
            for start in range(len(tokens)):
                if tokens[start][0] != incoming[0][0]:
                    continue
                length = 0
                while (start + length < len(tokens) and length < len(incoming)
                       and tokens[start + length][0] == incoming[length][0]):
                    length += 1
                best = max(best, length)
        if best < 6:
            break
        result = result[incoming[best - 1][2]:].strip(" \n\t:-—•*?.,;!")
    lines = result.splitlines()
    while lines:
        line = lines[0].strip()
        if not line:
            lines.pop(0)
            continue
        plain = normalize(line)
        if (plain == "seu pedido ate agora"
                or re.match(r"^(subtotal|total|entrega|pedido|nome|endereco|itens|"
                            r"pagamento|troco|observacao)\s*:", plain)
                or plain.startswith(("confere seu pedido", "quer mais alguma coisa",
                                     "esta tudo certo", "me diga o que voce quer"))
                or re.match(r"^[*•\-]?\s*\d+x\s+.+r\$", line, re.IGNORECASE)):
            lines.pop(0)
            continue
        break
    return "\n".join(lines).strip()


def text_plain(value: str) -> str:
    """Formatting-insensitive text used to recognize the bot's own outgoing bubbles."""
    return re.sub(r"[^a-z0-9]+", " ", normalize(value)).strip()


def is_ours(text: str, sent: list[str]) -> bool:
    plain = text_plain(text)
    if not plain:
        return True
    for item in sent:
        if not item:
            continue
        if plain == item or plain.startswith(item) or item.startswith(plain):
            return True
        if len(plain) >= 24 and (plain[:24] in item or item[:24] in plain):
            return True
    return False


def awaiting_reply(history: list[dict]) -> list[dict]:
    """Customer messages after the last bot answer.

    The owner typing in the chat (`kind == "owner"`) pauses the automation, but it never
    counts as answering the customer: after the owner hands the chat back, the bot still
    owes an answer to what arrived after its own last reply.
    """
    cut = len(history)
    while cut and not (history[cut - 1].get("dir") == "out"
                       and history[cut - 1].get("kind") != "owner"):
        cut -= 1
    return [entry for entry in history[cut:] if entry.get("dir") == "in"]


def stamp_now(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


class LanchoneteChannel(WhatsAppChannel):
    """The sales browser channel with this module's private debug folder."""

    def __init__(self, page, pacing, journal_path):
        super().__init__(page, pacing, journal_path)
        # The menu is long; a faster but still chunked typing keeps the chat moving.
        self.typing = sender.Pacing(typing_min_ms=10, typing_max_ms=25)

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        return sender.send_sequence(self.page, lead["name"], items, self.typing,
                                    self.journal_path, extra=extra,
                                    link_wait=self.pacing.link_preview,
                                    debug_dir=self.journal_path.parent / "lanchonete"
                                    / "debug")


@dataclass
class Turn:
    messages: list[str] = field(default_factory=list)
    state: str = ""
    updates: dict = field(default_factory=dict)
    intent: str = ""
    handoff_reason: str = ""
    priority: str = ""
    order: Order | None = None
    save_order: bool = False
    block: bool = False
    source: str = "local"


class LanchoneteAgent:
    def __init__(self, rules: RestaurantRules, store: LanchoneteStore, channel=None, llm=None,
                 live: bool = False, clock=None, sleep=time.sleep, rng=random,
                 notify=None, log=None, transcriber=None, only=()):
        self.rules = rules
        self.store = store
        self.channel = channel
        self.llm = llm
        self.live = live
        self.zone = ZoneInfo(rules.raw["timezone"])
        self.clock = clock or (lambda: datetime.now(self.zone))
        self.sleep = sleep
        self.rng = rng
        self.notify = notify or (lambda entry: owner_notify.desktop_notify(entry, rules.company))
        self.log = log or (lambda message: print(f"[lanchonete] {message}", flush=True))
        self.pacing = SalesPacing.from_rules(rules)
        self.transcriber = transcriber or local_transcriber
        self.only_keys = {phone_key(phone) for phone in only if phone_key(phone)}
        self._chats = 0
        self._last_chat = None
        self._planned: set[tuple[str, str]] = set()
        if live and channel is None:
            raise ValueError("live mode needs a WhatsApp channel")

    # Helpers -------------------------------------------------------------------------
    def use_rules(self, rules: RestaurantRules) -> None:
        self.rules = rules
        self.pacing = SalesPacing.from_rules(rules)

    def now(self) -> datetime:
        return self.clock()

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))

    def _next_chat(self, customer: dict) -> None:
        if customer["id"] == self._last_chat:
            return
        if self._chats:
            self.sleep(self.pacing.between_chats(self.rng))
        self._chats += 1
        self._last_chat = customer["id"]

    def _entry(self, customer: dict) -> str:
        return "+" + customer["phone"] if customer.get("phone") else customer.get("chat", "")

    def _greeting(self, now: datetime) -> str:
        return self.rules.fill(self.rules.texts["greeting"],
                               greeting=self.rules.greeting(now))

    def _fill_messages(self, intent, **values) -> list[str]:
        return [self.rules.fill(message, **values) for message in intent.messages]

    def _fixed(self, intent_id: str, **values) -> list[str]:
        return self._fill_messages(self.rules.intent(intent_id), **values)

    def _order_from_lead(self, customer: dict) -> Order:
        return Order.from_lead(self.rules, customer)

    def _service_window(self, customer: dict, order: Order, now: datetime) -> bool:
        if self.rules.in_window(now):
            return True
        if customer.get("state") not in ("ordering", "confirming") or order.is_empty():
            return False
        hours = self.rules.raw["hours"]
        if now.weekday() not in hours["ordering_days"]:
            return False
        try:
            hour, minute = hours["ordering_end"].split(":")
            end = datetime.combine(now.date(), clock_time(int(hour), int(minute)),
                                   tzinfo=now.tzinfo)
        except (AttributeError, ValueError):
            return False
        return now <= end + timedelta(minutes=30)

    def _remind(self, customer: dict) -> bool:
        window = timedelta(minutes=float(self.rules.limits["owner_reminder_minutes"]))
        for entry in reversed(self.store.handoffs()):
            if entry.get("lead") == customer["id"]:
                last = self._parse_date(entry.get("at"))
                return last is None or self.now() - last >= window
        return True

    def _handoff(self, customer: dict, reason: str, priority: str = "needed",
                 intent: str = "", text: str = "", ficha: str = "") -> dict:
        customer = self.store.lead(customer["id"]) or customer
        entry = owner_notify.handoff_entry(
            customer, self.store.history(customer["id"]), reason, priority, intent, text,
            self.now(), self.rules.agent_name, ficha)
        self.store.log_handoff(entry)
        self.notify(entry)
        self.log(f"owner needed for {customer.get('name')} ({priority}): {reason}")
        return entry

    def _with_greeting(self, customer: dict, messages: list[str], now: datetime) -> list[str]:
        if customer.get("state") in ("new", "closed") and messages:
            greeting = self._greeting(now)
            if not messages[0].startswith(greeting):
                return [greeting] + messages
        return messages

    # Incoming ------------------------------------------------------------------------
    @staticmethod
    def group_like(event: dict) -> bool:
        return (not canonical_phone(event.get("chat", ""))
                and bool(GROUP_PREFIX.match(event.get("text", ""))))

    def allowed_chat(self, chat: str) -> bool:
        """An allowlisted phone, or an existing customer whose phone is allowlisted."""
        if not self.only_keys:
            return True
        phone = canonical_phone(chat)
        if phone and phone_key(phone) in self.only_keys:
            return True
        customer = self.store.find_lead(chat)
        return bool(customer and customer.get("phone")
                    and phone_key(customer["phone"]) in self.only_keys)

    def ingest(self, events: list[dict]) -> list[str]:
        touched = []
        contacts = listener.load_rules(self.store.contact_rules_path)
        for event in events:
            chat = (event.get("chat") or "").strip()
            text = event.get("text") or ""
            if not chat or not text:
                continue
            if not self.allowed_chat(chat):
                self.log("chat outside the allowlist skipped")
                continue
            customer = self.store.find_lead(chat)
            if customer is None:
                if self.group_like(event):
                    self.log(f"group-like chat skipped: {chat}")
                    continue
                if contacts["mode"] == "block" and not listener.contact_allowed(chat, contacts):
                    self.log(f"contact blocked by rules.json: {chat}")
                    continue
                customer = self.store.ensure_customer(chat, self.now())
                listener.allow_contact(self.store.contact_rules_path, self._entry(customer))
            elif not listener.contact_allowed(self._entry(customer), contacts) and \
                    contacts["mode"] == "block":
                self.log(f"contact blocked by rules.json: {chat}")
                continue
            history = self.store.history(customer["id"])
            outgoing = [entry.get("text", "") for entry in history if entry.get("dir") == "out"]
            text = clean_incoming(text, outgoing)
            if not text:
                continue
            if any(entry.get("event") == event.get("id") for entry in history):
                continue
            sent = [normalize(entry.get("text", "")) for entry in history[-40:]
                    if entry.get("dir") == "out"]
            if normalize(text) in sent:
                continue
            now = stamp = self.now().isoformat(timespec="seconds")
            self.store.remember(customer["id"], {
                "at": now, "dir": "in", "text": text, "kind": "incoming",
                "event": event.get("id"), "message_at": event.get("message_at", ""),
                "source": "preview"})
            changes = {"last_in_at": stamp, "chat": chat}
            state = customer["state"]
            if state in REPLYABLE:
                changes["awaiting"] = event.get("id")
            elif state == "do-not-contact":
                if self._remind(customer):
                    self._handoff(customer, "Contato bloqueado voltou a escrever", "alert",
                                  "blocked_customer", text)
            elif state in OWNER_STATES:
                priority = "needed"
                intent = state
                reason = "Nova mensagem numa conversa que está com você"
                if state == "confirmed":
                    intent = "order_status"
                    if self.rules.intent("complaint").matches(normalize(text)):
                        priority, reason = "hot", self.rules.texts["owner_reason_complaint"]
                    elif self.rules.intent("cancel").matches(normalize(text)):
                        priority, reason = "hot", self.rules.texts["owner_reason_cancel"]
                    elif self.rules.intent("status").matches(normalize(text)):
                        priority, reason = "hot", self.rules.texts["owner_reason_status"]
                    else:
                        reason = "Nova mensagem depois do pedido confirmado"
                if priority == "hot" or self._remind(customer):
                    self._handoff(customer, reason, priority, intent, text)
            self.store.update_lead(customer["id"], **changes)
            touched.append(customer["id"])
        return touched

    # Reply loop ----------------------------------------------------------------------
    def pending(self) -> list[dict]:
        return sorted((customer for customer in self.store.leads().values()
                       if customer.get("awaiting") and customer["state"] in REPLYABLE),
                      key=lambda customer: customer.get("last_in_at") or "")

    def reply_pending(self) -> list[dict]:
        """Answer every waiting customer; one customer's failure never blocks the others.

        A lost browser page (`is_closed`) still aborts the cycle so the run loop can
        reconnect; any other error fences only that customer and the rest continue.
        """
        results = []
        for customer in self.pending():
            try:
                results.append(self.reply(customer))
            except Exception as error:
                if is_closed(error):
                    raise
                self.log(f"customer {customer.get('id')} failed ({error}); others continue")
                results.append({"customer": customer["id"], "name": customer.get("name"),
                                "state": "error", "error": str(error)[:300]})
        return results

    def _open_chat(self, customer: dict) -> str:
        status = self.channel.open(customer)
        title_of = getattr(self.channel, "chat_title", None)
        if status != "ready" or not callable(title_of):
            return status
        expected = (customer.get("chat") or "").strip()
        title = (title_of() or "").strip()
        if expected:
            for _ in range(10):
                if title and title.casefold() == expected.casefold():
                    break
                page = getattr(self.channel, "page", None)
                if page is not None:
                    page.wait_for_timeout(500)
                title = (title_of() or "").strip()
            if title and title.casefold() != expected.casefold():
                # A stale/new tab can still show the previous chat just after navigation.
                self.channel.current = None
                status = self.channel.open(customer)
                if status == "ready":
                    for _ in range(6):
                        title = (title_of() or "").strip()
                        if title and title.casefold() == expected.casefold():
                            break
                        page = getattr(self.channel, "page", None)
                        if page is not None:
                            page.wait_for_timeout(500)
        if expected and title and title.casefold() != expected.casefold():
            self.log(f"chat title {title!r} does not match {expected!r}; not sending")
            return "wrong-chat"
        if title and title != customer.get("chat"):
            owner = self.store.find_lead(title)
            if (owner is None or owner["id"] == customer["id"]) and                     (not expected or expected == customer.get("phone")):
                self.store.update_lead(customer["id"], chat=title)
                customer["chat"] = title
        return status

    def _owner_typed(self, customer: dict, bubbles: list[dict]) -> list[str]:
        history = self.store.history(customer["id"])
        ours = [text_plain(entry.get("text", "")) for entry in history
                if entry.get("dir") == "out"]
        anchor = max((index for index, bubble in enumerate(bubbles)
                      if bubble["dir"] == "out" and bubble.get("text")
                      and is_ours(bubble["text"], ours)), default=None)
        if anchor is None:
            last = bubbles[-1] if bubbles else None
            if last and last["dir"] == "out" and not last.get("media") \
                    and not is_ours(last["text"], ours):
                return [last["text"]]
            return []
        return [bubble["text"] for bubble in bubbles[anchor + 1:]
                if bubble["dir"] == "out" and bubble.get("text")
                and not is_ours(bubble["text"], ours)]

    def _from_bubble(self, customer: dict, bubble: dict) -> dict | None:
        now = self.now()
        text = bubble.get("text", "")
        media = bubble.get("media", "")
        entry = {"at": now.isoformat(timespec="seconds"), "dir": "in", "kind": "incoming",
                 "source": "chat", "message_id": bubble.get("id", ""), "text": text}
        if not media:
            return entry if normalize(text) else None
        entry["media"] = media
        if text:
            entry["caption"] = text
        path = None
        if media in ("image", "audio"):
            try:
                fetched = self.channel.fetch_media(bubble) or []
            except Exception:
                fetched = []
            if fetched and isinstance(fetched, tuple):
                fetched = [fetched]
            folder = self.store.customer_dir(customer)
            files = []
            for data, extension in fetched:
                files.append(dossier.save_media(folder, data, extension, media, now))
            if files:
                path = files[0]
                entry["file"] = str(path.relative_to(folder))
                entry["files"] = [str(item.relative_to(folder)) for item in files]
        if media == "audio":
            transcript = ""
            if path is not None:
                try:
                    heard = self.transcriber(path)
                except Exception as error:
                    entry["transcription_error"] = str(error)[:200]
                else:
                    if isinstance(heard, dict):
                        transcript = heard.get("text", "")
                        if heard.get("uncertain"):
                            entry["uncertain"] = heard["uncertain"]
                        entry["engine"] = heard.get("engine", "")
                    else:
                        transcript = heard or ""
            entry["text"] = transcript or MEDIA_TEXT["audio"]
            if transcript:
                entry["transcript"] = transcript
                self.log(f"{customer.get('name')}: voice message transcribed")
        elif not text:
            entry["text"] = MEDIA_TEXT.get(media, "[mídia]")
        return entry

    def _merge_chat(self, customer: dict, bubbles: list[dict]) -> list[str] | None:
        typed = self._owner_typed(customer, bubbles)
        if typed:
            return typed
        history = self.store.history(customer["id"])
        last_out = max((index for index, bubble in enumerate(bubbles)
                        if bubble["dir"] == "out"), default=-1)
        _, unanswered = split_pending(history)
        seen = {entry.get("message_id") for entry in history if entry.get("message_id")}
        previews = [entry["event"] for entry in unanswered
                    if entry.get("source") == "preview" and entry.get("event")]
        outgoing = [entry.get("text", "") for entry in history if entry.get("dir") == "out"]
        entries = []
        for bubble in bubbles[last_out + 1:]:
            if bubble["dir"] != "in" or (bubble.get("id") and bubble["id"] in seen):
                continue
            entry = self._from_bubble(customer, bubble)
            if entry is not None:
                entry["text"] = clean_incoming(entry.get("text", ""), outgoing)
                if entry["text"]:
                    entries.append(entry)
        if entries and previews:
            entries[0]["replaces"] = previews
        for entry in entries:
            self.store.remember(customer["id"], entry)
        return None

    def _owner_took_over(self, customer: dict, texts: list[str], result: dict) -> dict:
        now = self.now().isoformat(timespec="seconds")
        for text in texts:
            self.store.remember(customer["id"], {"at": now, "dir": "out", "text": text,
                                                 "kind": "owner", "state": "sent"})
        self.store.update_lead(customer["id"], state="human", awaiting=None)
        self.log(f"{customer.get('name')}: the owner wrote in the chat; automation paused")
        return {**result, "state": "human"}

    # Decision ------------------------------------------------------------------------
    def _intent(self, customer: dict, text: str) -> str:
        plain = normalize(text)
        if not plain:
            return "unknown"
        if customer.get("awaiting_field") == "confirm":
            if any(re.search(pattern, plain) for pattern in self.rules.context["affirmative"]):
                return "affirmative"
            if any(re.search(pattern, plain) for pattern in self.rules.context["negative"]):
                return "negative"
        for intent_id in ("opt_out", "bot_question", "human_request", "complaint", "status",
                          "cancel", "media"):
            intent = self.rules.intent(intent_id)
            if intent.matches(plain):
                return intent_id
        for intent in self.rules.intents:
            if intent.id in ("opt_out", "bot_question", "human_request", "complaint", "status",
                             "cancel", "media", "unknown"):
                continue
            if intent.matches(plain):
                return intent.id
        return "unknown"

    def _ask(self, order: Order, field_name: str, include_cart: bool = True) -> Turn:
        texts = self.rules.texts
        question = {"type": texts["ask_type"], "address": texts["ask_address"],
                    "name": texts["ask_name"], "payment": texts["ask_payment"],
                    "change": texts["ask_change"]}[field_name]
        messages = [order.cart_text(self.rules)] if include_cart and not order.is_empty() else []
        messages.append(self.rules.fill(question, total=brl(order.total_cents(self.rules))))
        return Turn(messages, "ordering", {"awaiting_field": field_name, "closing": True},
                    "ask_" + field_name, order=order)

    def _missing_field(self, order: Order) -> str:
        if not order.kind:
            return "type"
        if order.kind == "delivery" and not order.address:
            return "address"
        if not order.customer_name:
            return "name"
        if not order.payment:
            return "payment"
        if order.payment == "cash" and order.change_for_cents is None and not order.change_exact:
            return "change"
        return ""

    def _advance(self, customer: dict, order: Order) -> Turn:
        if order.is_empty():
            return Turn([self.rules.texts["cart_empty"]], "ordering", {
                "awaiting_field": "", "closing": False}, "empty")
        if order.over_limit(self.rules):
            return self._large_order(order)
        field_name = self._missing_field(order)
        if field_name:
            first_ask = (customer.get("awaiting_field") or "") not in FIELDS
            return self._ask(order, field_name, include_cart=first_ask)
        if order.payment == "cash" and order.totals(self.rules).change_too_low:
            return self._change_low(order)
        if order.kind == "delivery" and order.totals(self.rules).missing_min_cents:
            missing = brl(order.totals(self.rules).missing_min_cents)
            return Turn([self.rules.fill(self.rules.texts["below_min"], missing=missing),
                         self.rules.texts["below_min_question"]], "ordering", {
                             "awaiting_field": "", "closing": True}, "below_min", order=order)
        summary = order.summary_text(self.rules)
        return Turn([summary, self.rules.texts["summary_question"]], "confirming", {
            "awaiting_field": "confirm", "confirmations": 0, "closing": True}, "summary",
            order=order)

    def _large_order(self, order: Order) -> Turn:
        return Turn([order.cart_text(self.rules), self.rules.texts["large_order"]],
                    "needs-owner", {"awaiting_field": ""},
                    "large_order", self.rules.texts["owner_reason_large"], "needed",
                    order=order)

    def _cancel_turn(self, customer: dict, order: Order) -> Turn:
        if customer.get("state") == "confirmed" or customer.get("order_number"):
            return Turn([self.rules.texts["cancelled_after_kitchen"]], "needs-owner", {},
                        "cancel", self.rules.texts["owner_reason_cancel"], "hot", order=order)
        updates = {"awaiting_field": "", "confirmations": 0, "unknown_count": 0,
                   "closing": False}
        updates.update(Order().to_lead_fields())
        return Turn([self.rules.texts["cancelled"]], "cancelled", updates, "cancel")

    def _unknown(self, customer: dict, intent: str = "unknown") -> Turn:
        count = int(customer.get("unknown_count", 0)) + 1
        if count >= int(self.rules.limits["max_unknown"]):
            return Turn([self.rules.texts["handoff_ack"]], "needs-owner",
                        {"awaiting_field": "", "unknown_count": 0}, intent,
                        self.rules.texts["owner_reason_unknown"], "needed")
        return Turn([self.rules.texts["not_understood"]], "ordering",
                    {"unknown_count": count}, intent)

    @staticmethod
    def _change_from_text(text: str) -> tuple[int | None, bool]:
        cents, exact = parser.parse_change(text)
        if exact:
            return None, True
        if cents is not None:
            return cents, False
        plain = normalize(text)
        words = {"vinte": 2000, "trinta": 3000, "quarenta": 4000, "cinquenta": 5000,
                 "sessenta": 6000, "setenta": 7000, "oitenta": 8000, "noventa": 9000,
                 "cem": 10000}
        for word, value in words.items():
            if re.search(rf"\b{word}\b", plain):
                return value, False
        match = re.search(r"(?:r\$\s*)?(\d{1,4})(?:[,.](\d{1,2}))?", plain)
        if match and not re.search(r"\b(rua|avenida|numero|número|quadra|lote)\b", plain):
            return int(match.group(1)) * 100 + (int(match.group(2).ljust(2, "0"))
                                               if match.group(2) else 0), False
        return None, False

    def _apply_parsed(self, customer: dict, order: Order, parsed, text: str
                      ) -> tuple[bool, list[str]]:
        """Apply the parsed order; return (changed, extra messages the customer must see)."""
        notes: list[str] = []
        changed = False
        awaiting = customer.get("awaiting_field") or ""
        plain = normalize(text)
        select = bool(re.search(r"\b(quero|vou|pode ser|prefiro|pago|pagarei|paguei|no|na)\b",
                                plain))
        max_qty = int(self.rules.limits["max_qty_per_item"])
        for item in parsed.items:
            if item.item_id:
                try:
                    if item.remove:
                        if order.remove(self.rules, item.item_id, item.qty):
                            changed = True
                        continue
                    if item.qty > max_qty:
                        notes.append(self.rules.fill(self.rules.texts["max_qty"], max=max_qty))
                        continue
                    existing = next((line for line in order.lines
                                     if line.item_id == item.item_id), None)
                    if item.qty == 0 and existing is not None:
                        for extra_id in item.extras:
                            try:
                                order.add_extra(self.rules, item.item_id, extra_id)
                                changed = True
                            except OrderError:
                                notes.append(self.rules.fill(
                                    self.rules.texts["extra_not_found"],
                                    extras=", ".join(extra.name for extra in self.rules.extras)))
                        if item.note and item.note not in existing.note:
                            existing.note = "; ".join(part for part in
                                                      (existing.note, item.note) if part)[:60]
                            changed = True
                        continue
                    order.add(self.rules, item.item_id, item.qty or 1, item.extras, item.note)
                    changed = True
                except (KeyError, OrderError):
                    notes.append(self.rules.texts["item_not_found"])
                continue
            # An extra without an item belongs to the last line.
            if not order.lines:
                notes.append(self.rules.texts["cart_empty"])
                continue
            for extra_id in item.extras:
                try:
                    order.add_extra(self.rules, order.lines[-1].item_id, extra_id)
                    changed = True
                except (KeyError, OrderError):
                    notes.append(self.rules.fill(
                        self.rules.texts["extra_not_found"],
                        extras=", ".join(extra.name for extra in self.rules.extras)))
        for extra_id in parsed.remove_extras:
            for line in order.lines:
                if extra_id in line.extras:
                    line.extras.remove(extra_id)
                    changed = True

        fields = parsed.fields
        words = plain.split()
        short_answer = len(words) <= 4 and "?" not in plain
        kind = fields.get("kind") or ""
        kind_short = short_answer and bool(re.search(r"\b(entrega|retirada|retirar|delivery)\b",
                                                     plain))
        if kind and kind != order.kind and (awaiting == "type" or select or kind_short):
            order.kind = kind
            if kind == "pickup":
                order.address = ""
            changed = True
        payment = fields.get("payment") or ""
        payment_short = short_answer and bool(re.match(
            r"^(pix|dinheiro|cartao|debito|credito|pago|paguei|pagarei|no pix|na entrega|"
            r"em dinheiro|com cartao)\b", plain))
        if payment and payment != order.payment and (awaiting == "payment" or select
                                                     or payment_short):
            order.payment = payment
            if payment != "cash":
                order.change_for_cents = None
                order.change_exact = False
            changed = True
        name_hint = re.search(r"\b(meu nome|nome e|aqui e|me chamo|sou o|sou a|pode ser|"
                              r"no nome)\b", plain)
        if fields.get("name") and fields["name"] != order.customer_name and \
                (awaiting == "name" or name_hint):
            order.customer_name = fields["name"]
            changed = True
        address_hint = re.search(r"\b(rua|avenida|travessa|alameda|rodovia|estrada|passagem|"
                                 r"beco|quadra|lote|bairro|moro|endereco|entrega em|"
                                 r"entregar em)\b", plain)
        if fields.get("address") and fields["address"] != order.address and \
                (awaiting == "address" or address_hint):
            order.address = fields["address"]
            changed = True
        if order.payment == "cash" and (awaiting == "change" or "troco" in plain):
            if fields.get("change_exact"):
                order.change_exact = True
                order.change_for_cents = None
                changed = True
            elif "change_for_cents" in fields:
                order.change_for_cents = fields["change_for_cents"]
                order.change_exact = False
                changed = True

        if awaiting == "type" and not order.kind:
            kind = parser.parse_kind(text)
            if kind:
                order.kind, changed = kind, True
        if awaiting == "payment" and not order.payment:
            payment = parser.parse_payment(self.rules, text)
            if payment:
                order.payment, changed = payment, True
        if awaiting == "address" and not order.address:
            address = parser.parse_address(text)
            if address:
                order.address, changed = address, True
        if awaiting == "name" and not order.customer_name:
            name = parser.parse_name(text)
            if name:
                order.customer_name, changed = name, True
        if awaiting == "change" and order.payment == "cash" and \
                order.change_for_cents is None and not order.change_exact:
            cents, exact = self._change_from_text(text)
            if exact:
                order.change_exact, changed = True, True
            elif cents is not None:
                order.change_for_cents, changed = cents, True
        if changed:
            notes = []
        return changed, notes

    def _pending_question(self, order: Order, awaiting: str) -> list[str]:
        if awaiting not in FIELDS or not order.lines:
            return []
        field_name = self._missing_field(order)
        if not field_name:
            return []
        return self._ask(order, field_name, include_cart=False).messages[-1:]

    def _change_low(self, order: Order) -> Turn:
        total = brl(order.total_cents(self.rules))
        return Turn([self.rules.fill(self.rules.texts["change_too_low"], total=total),
                     self.rules.texts["ask_change"]], "ordering",
                    {"awaiting_field": "change"}, "change_low", order=order)

    def _is_yes(self, text: str) -> bool:
        plain = normalize(text)
        return any(re.search(pattern, plain) for pattern in self.rules.context["affirmative"])

    def _is_no(self, text: str) -> bool:
        plain = normalize(text)
        return any(re.search(pattern, plain) for pattern in self.rules.context["negative"])

    @staticmethod
    def _base_name(name: str) -> str:
        parts = (name or "").split()
        return parts[0].casefold() if parts else ""

    def _same_variant(self, first, second) -> bool:
        """Same category and same base name: Açaí 300 ml ~ Açaí 500 ml, but never ~ Milk-Shake."""
        return (first.category == second.category
                and self._base_name(first.name) == self._base_name(second.name))

    @staticmethod
    def _name_matches(token: str, name: str) -> bool:
        """A rejection token ("500", "500ml", "calabresa") names a cart item."""
        token = normalize(token or "")
        if not token:
            return False
        flat = normalize(name).replace(" ", "")
        if token.replace(" ", "") in flat:
            return True
        digits = re.sub(r"\D", "", token)
        return bool(digits) and digits in re.sub(r"\D", "", name or "")

    def _swap_proposal(self, customer: dict, order: Order, parsed, text: str
                       ) -> tuple[str, str, int] | None:
        """(from_id, to_id, qty) when the text exchanges a cart item, else None.

        "Quero o açaí mais barato" with Açaí 500 in the cart proposes Açaí 500 → Açaí 300.
        The cart is never touched here; the customer confirms first (see `_apply_swap`).
        A bare rejection without an addition ("não o de 500") is a removal, not a swap.
        """
        if order.is_empty():
            return None
        plain = normalize(text)
        if not REPLACE_CUE.search(plain):
            return None
        mentioned = [item.item_id for item in parsed.items
                     if item.item_id and not item.remove]
        if not mentioned:
            return None
        neg = NEG_REF.search(plain)
        token = neg.group(4) if neg else ""
        scored: dict[str, int] = {}
        for line in order.lines:
            try:
                item = self.rules.item(line.item_id)
            except KeyError:
                continue
            score = 0
            if line.item_id in mentioned:
                score = 2
            else:
                for mid in mentioned:
                    try:
                        other = self.rules.item(mid)
                    except KeyError:
                        continue
                    if self._same_variant(item, other):
                        score = max(score, 1)
            if token and self._name_matches(token, item.name):
                score = max(score, 2)
            if score:
                scored[line.item_id] = max(scored.get(line.item_id, 0), score)
        if not scored:
            return None
        best = max(scored.values())
        affected = [line_id for line_id, score in scored.items() if score == best]
        if len(affected) != 1:
            return None
        current = self.rules.item(affected[0])
        candidates = [candidate for candidate in self.rules.items
                      if candidate.category == current.category
                      and candidate.id != current.id
                      and self._base_name(candidate.name) == self._base_name(current.name)]
        if not candidates:
            return None
        if re.search(r"\b(maior|maiores|grande|grandes)\b", plain):
            target = max(candidates, key=lambda candidate: candidate.price_cents)
        else:
            target = min(candidates, key=lambda candidate: candidate.price_cents)
        qty = next(line.qty for line in order.lines if line.item_id == current.id)
        return (current.id, target.id, qty)

    def _direct_remove(self, order: Order, text: str) -> str | None:
        """The cart item a bare rejection names ("não o de 500"), when it is unique."""
        neg = NEG_REF.search(normalize(text))
        if not neg or not neg.group(4):
            return None
        hits = []
        for line in order.lines:
            try:
                name = self.rules.item(line.item_id).name
            except KeyError:
                continue
            if self._name_matches(neg.group(4), name):
                hits.append(line.item_id)
        return hits[0] if len(hits) == 1 else None

    def _apply_swap(self, customer: dict, order: Order, pending: dict, updates: dict,
                    now: datetime) -> Turn:
        """The customer confirmed the swap: exchange the items 1:1 and show the cart."""
        try:
            from_item = self.rules.item(pending["from"])
            to_item = self.rules.item(pending["to"])
        except KeyError:
            fresh = {**updates, **order.to_lead_fields(), "pending_replace": None}
            return Turn([order.cart_text(self.rules)], "ordering", fresh, "order", order=order)
        qty = max(int(pending.get("qty") or 1), 1)
        order.remove(self.rules, from_item.id)
        order.add(self.rules, to_item.id, qty)
        fresh = {**updates, **order.to_lead_fields(), "pending_replace": None}
        messages = [order.cart_text(self.rules), self.rules.texts["cart_question"]]
        return Turn(self._with_greeting(customer, messages, now), "ordering", fresh,
                    "swap", order=order)

    def _turn(self, customer: dict, text: str) -> Turn:
        now = self.now()
        state = customer["state"]
        plain = normalize(text)
        order = self._order_from_lead(customer)
        parsed = parser.parse(self.rules, text)
        intent = self._intent(customer, text)
        first = state in ("new", "closed", "cancelled")
        base_state = "ordering" if first else state
        awaiting = customer.get("awaiting_field") or ""
        updates: dict = {"unknown_count": 0}
        if state == "closed" and (order.lines or order.number or order.customer_name):
            order = Order()
            updates.update(order.to_lead_fields())
            updates["order_number"] = ""

        if intent == "opt_out":
            return Turn(self._fixed("opt_out"), "do-not-contact", {}, intent, block=True)

        if re.search(r"\b(tudo|todos os itens|cardapio inteiro|o cardapio todo)\b", plain) and \
                "cardapio" in plain:
            return Turn([self.rules.texts["large_order"]], "needs-owner",
                        {"awaiting_field": ""}, "large_order",
                        self.rules.texts["owner_reason_large"], "needed", order=order)

        if not self._service_window(customer, order, now):
            last = self._parse_date(customer.get("closed_notice_at"))
            window = timedelta(minutes=float(self.rules.limits["closed_notice_minutes"]))
            if last is not None and now - last < window:
                return Turn([], "closed", {"awaiting": None}, "closed")
            reset = Order().to_lead_fields()
            return Turn([self.rules.fill(self.rules.texts["closed"],
                                         greeting=self.rules.greeting(now))],
                        "closed", {"closed_notice_at": now.isoformat(timespec="seconds"),
                                   "awaiting": None, **reset}, "closed")

        if intent in ("human_request", "complaint"):
            messages = self._fixed(intent)
            reason = self.rules.intent(intent).reason
            return Turn(self._with_greeting(customer, messages, now), "needs-owner", {},
                        intent, reason, self.rules.intent(intent).priority)

        if intent == "media":
            messages = self._fixed("media")
            return Turn(self._with_greeting(customer, messages, now), "needs-owner", {},
                        intent, self.rules.texts["owner_reason_media"], "needed")

        if intent == "cancel" or parsed.cancel:
            turn = self._cancel_turn(customer, order)
            turn.messages = self._with_greeting(customer, turn.messages, now)
            return turn

        pending = customer.get("pending_replace") or {}
        if pending:
            if self._is_yes(text):
                return self._apply_swap(customer, order, pending, dict(updates), now)
            if self._is_no(text):
                fresh = {**updates, **order.to_lead_fields(), "pending_replace": None}
                messages = [order.cart_text(self.rules), self.rules.texts["cart_question"]]
                return Turn(self._with_greeting(customer, messages, now), base_state, fresh,
                            "keep", order=order)
            if parsed.changed or parsed.done or parsed.cancel:
                updates["pending_replace"] = None  # the new message supersedes the proposal

        if intent == "status":
            if customer.get("order_number") or state == "confirmed":
                messages = self._fixed("status")
                return Turn(messages, "needs-owner", {},
                            intent, self.rules.texts["owner_reason_status"], "hot")
            intent = "delivery"  # no order yet: "quanto tempo demora?" is the delivery fact

        if intent in ("thanks", "auto_reply"):
            return Turn([], state, {}, intent)

        honest = self._fixed("bot_question") if intent == "bot_question" else []

        if intent == "no_order":
            updates.update(Order().to_lead_fields())
            updates["awaiting_field"] = ""
            updates["closing"] = False
            return Turn(self._with_greeting(customer, [self.rules.texts["no_order"]], now),
                        "closed", updates, intent)

        question_first = bool(re.match(
            r"^(quanto|qual|quais|preco|valor|o que|como|tem|vem|ingredientes)\b", plain))
        if intent in ("price", "item_info") and parsed.question_items and \
                (question_first or not parser.ADD_CUE.search(plain)):
            items = [self.rules.item(item_id) for item_id in parsed.question_items]
            answers = (self.rules.price_answer(items) if intent == "price"
                       else [self.rules.item_text(item) for item in items])
            messages = honest + answers
            if first:
                messages.append(self.rules.texts["menu_question"])
            elif not order.is_empty():
                messages.append(self.rules.texts["cart_question"])
            return Turn(self._with_greeting(customer, messages, now), base_state, updates,
                        intent, order=order)

        if intent == "menu" and not parsed.items and not parsed.done:
            messages = list(self.rules.menu_messages())
            if not order.is_empty():
                messages.append(self.rules.texts["cart_question"])
            messages += self._pending_question(order, awaiting)
            return Turn(self._with_greeting(customer, messages, now), base_state, updates,
                        intent, order=order)

        # Free-form order: the local parser first, the model only when it found nothing.
        # A rejection or a comparative never falls through to a blind add: a bare "não o
        # de 500" removes that cart item, and "o açaí mais barato" proposes the swap first.
        if not parsed.done:
            adds = [item for item in parsed.items if item.item_id and not item.remove]
            if adds:
                proposal = self._swap_proposal(customer, order, parsed, text)
                if proposal is not None:
                    from_item = self.rules.item(proposal[0])
                    to_item = self.rules.item(proposal[1])
                    fresh = {**updates, **order.to_lead_fields(),
                             "pending_replace": {"from": proposal[0], "to": proposal[1],
                                                 "qty": proposal[2]}}
                    messages = [order.cart_text(self.rules),
                                self.rules.fill(self.rules.texts["swap_question"],
                                                fro=from_item.name, to=to_item.name)]
                    return Turn(self._with_greeting(customer, messages, now), base_state, fresh,
                                "swap_ask", order=order)
            else:
                removed_id = self._direct_remove(order, text)
                if removed_id is not None:
                    removed_name = self.rules.item(removed_id).name
                    order.remove(self.rules, removed_id)
                    fresh = {**updates, **order.to_lead_fields(), "unknown_count": 0}
                    if order.is_empty():
                        messages = [self.rules.fill(self.rules.texts["removed_item"],
                                                    item=removed_name),
                                    self.rules.texts["cart_empty"]]
                    else:
                        messages = [self.rules.fill(self.rules.texts["removed_item"],
                                                    item=removed_name),
                                    order.cart_text(self.rules),
                                    self.rules.texts["cart_question"]]
                    return Turn(self._with_greeting(customer, messages, now), base_state, fresh,
                                "remove", order=order)
        cart_before = order.to_lead_fields()["cart"]
        changed, notes = self._apply_parsed(customer, order, parsed, text)
        cart_changed = order.to_lead_fields()["cart"] != cart_before
        source = "local"
        if not changed and not parsed.done and intent == "unknown" and self.llm is not None:
            model, error = interpreter.interpret(
                self.rules, order, text, self.llm, now, usage=self.store.log_usage,
                session_id=f"brasa-pao-{customer['id']}")
            if model is not None:
                model_changed, model_notes = self._apply_parsed(customer, order, model, text)
                if model_changed or model.done or model.cancel:
                    parsed, changed, notes, source = model, model_changed, model_notes, "model"
                    cart_changed = order.to_lead_fields()["cart"] != cart_before
                if parsed.cancel:
                    return self._cancel_turn(customer, order)
            else:
                self.log(f"model order read skipped: {error}")

        updates.update(order.to_lead_fields())
        if changed:
            updates["unknown_count"] = 0

        if state == "confirming" or awaiting == "confirm":
            if changed or notes:
                confirmations = int(customer.get("confirmations", 0)) + 1
                if confirmations > int(self.rules.limits["max_confirmations"]):
                    return Turn([order.cart_text(self.rules),
                                 self.rules.texts["handoff_ack"]], "needs-owner", updates,
                                "summary", self.rules.texts["owner_reason_confirm"], "needed",
                                order=order)
                if order.is_empty() or self._missing_field(order):
                    result = self._advance(customer, order)
                else:
                    result = Turn([order.summary_text(self.rules),
                                   self.rules.texts["summary_question"]], "confirming",
                                  {"awaiting_field": "confirm"}, "summary", order=order)
                result.updates.update(updates)
                result.updates["confirmations"] = confirmations
                result.source = source
                return result
            if intent == "negative":
                confirmations = int(customer.get("confirmations", 0)) + 1
                if confirmations > int(self.rules.limits["max_confirmations"]):
                    return Turn([self.rules.texts["handoff_ack"]], "needs-owner", updates,
                                "summary", self.rules.texts["owner_reason_confirm"], "needed",
                                order=order)
                return Turn([self.rules.texts["ask_what_to_adjust"]], "confirming",
                            {**updates, "confirmations": confirmations}, "negative",
                            order=order)
            if intent == "affirmative" or (parsed.done and not changed):
                return self._confirm(customer, order, now, updates)
            if order.payment == "cash" and order.totals(self.rules).change_too_low:
                result = self._change_low(order)
                result.updates.update(updates)
                return result
            answers = honest + (self._fixed(intent) if intent in FAQ else [])
            if answers:
                return Turn(answers + [order.summary_text(self.rules),
                                       self.rules.texts["summary_question"]], "confirming",
                            {**updates, "awaiting_field": "confirm"}, intent, order=order)
            return Turn([self.rules.texts["ask_what_to_adjust"]], "confirming",
                        {**updates,
                         "confirmations": int(customer.get("confirmations", 0)) + 1},
                        intent, order=order)

        if parsed.done:
            result = self._advance(customer, order)
            messages = honest + notes + result.messages
            result.messages = self._with_greeting(customer, messages, now)
            result.updates.update(updates)
            result.source = source
            return result

        if changed or notes:
            messages = list(notes)
            closing = bool(customer.get("closing")) or bool(updates.get("closing"))
            if closing and changed and order.lines and awaiting not in FIELDS:
                advance = self._advance(customer, order)
                updates.update(advance.updates)
                if cart_changed:
                    messages.append(order.cart_text(self.rules))
                messages += advance.messages
                return Turn(self._with_greeting(customer, [text for text in messages if text],
                                                now), advance.state, updates,
                            advance.intent or "order", advance.handoff_reason,
                            advance.priority, order=order, source=source)
            if changed and (cart_changed or awaiting not in FIELDS):
                messages.append(order.cart_text(self.rules) if not order.is_empty()
                                else self.rules.texts["cart_empty"])
            asked = self._pending_question(order, awaiting)
            field_name = self._missing_field(order)
            if awaiting in FIELDS:
                if field_name:
                    ask_turn = self._ask(order, field_name, include_cart=False)
                    asked = ask_turn.messages
                    updates.update(ask_turn.updates)
                elif order.payment == "cash" and order.totals(self.rules).change_too_low:
                    ask_turn = self._change_low(order)
                    asked = ask_turn.messages
                    updates.update(ask_turn.updates)
                else:
                    advance = self._advance(customer, order)
                    asked = advance.messages
                    updates.update(advance.updates)
                    if advance.state == "confirming":
                        messages = list(notes) + asked
                        messages = [text for text in messages if text]
                        return Turn(self._with_greeting(customer, messages, now),
                                    "confirming", updates, "summary", order=order,
                                    source=source)
            messages += asked
            if not asked:
                messages.append(self.rules.texts["menu_question"] if order.is_empty()
                                else self.rules.texts["cart_question"])
            messages = [text for text in messages if text]
            if intent in FAQ and (("?" in text) or re.search(
                    r"\b(taxa|prazo|horario|endereco|onde|como|quanto)\b", normalize(text))):
                messages += self._fixed(intent)
            return Turn(self._with_greeting(customer, messages, now), base_state, updates,
                        "order", order=order, source=source)

        if intent in FAQ:
            answers = honest + self._fixed(intent)
            answers += self._pending_question(order, awaiting)
            return Turn(self._with_greeting(customer, answers, now), base_state, updates,
                        intent, order=order)

        if honest:
            messages = honest
            if not order.is_empty():
                messages.append(self.rules.texts["cart_question"])
            elif first:
                messages.append(self.rules.texts["menu_question"])
            return Turn(self._with_greeting(customer, messages, now), base_state, updates,
                        "bot_question", order=order)

        if first:
            messages = list(self.rules.menu_messages()) + [self.rules.texts["menu_question"]]
            return Turn(self._with_greeting(customer, messages, now), "ordering", updates,
                        "greeting")

        if awaiting:
            result = self._ask(order, awaiting, include_cart=False)
            result.updates.update(updates)
            result.messages = [self.rules.texts["not_understood"]] + result.messages
            result.intent = "ask_" + awaiting
            return result

        return self._unknown(customer, intent)

    def _confirm(self, customer: dict, order: Order, now: datetime, updates: dict) -> Turn:
        field_name = self._missing_field(order)
        if field_name:
            result = self._ask(order, field_name)
            result.updates.update(updates)
            return result
        totals = order.totals(self.rules)
        if order.payment == "cash" and totals.change_too_low:
            result = self._change_low(order)
            result.updates.update(updates)
            return result
        if order.kind == "delivery" and totals.missing_min_cents:
            return self._advance(customer, order)
        if order.over_limit(self.rules):
            return self._large_order(order)
        order.number = self.store.next_order_number(self.rules, now)
        order.status = "confirmed"
        order.created_at = order.created_at or now.isoformat(timespec="seconds")
        order.confirmed_at = now.isoformat(timespec="seconds")
        texts = self.rules.texts
        messages = [texts["confirmed_title"],
                    self.rules.fill(texts["confirmed_number"], number=order.number,
                                    kind=order.kind_label()),
                    self.rules.fill(texts["confirmed_total"],
                                    total=brl(totals.total_cents),
                                    payment=order.payment_label(self.rules))]
        if order.payment == "pix":
            messages.append(texts["confirmed_pix"])
        if order.kind == "delivery":
            messages.append(self.rules.fill(texts["confirmed_delivery"],
                                            estimate=self.rules.delivery["estimate"]))
        else:
            messages.append(self.rules.fill(texts["confirmed_pickup"],
                                            address=self.rules.address,
                                            estimate=self.rules.delivery["pickup_estimate"]))
        messages.append(texts["confirmed_thanks"])
        return Turn(messages, "confirmed",
                    {**updates, **order.to_lead_fields(), "awaiting_field": "",
                     "confirmations": 0, "unknown_count": 0, "closing": False},
                    "confirm", order=order, save_order=True)

    # Sending -------------------------------------------------------------------------
    def _items(self, customer: dict, tag: str, messages: list[str],
               incoming: str | None) -> list[dict]:
        """Journal keys bind the reply to its cause AND its content.

        `tag` is the turn (reply/opening), the cause is the incoming event that triggered
        it, and the content is the normalized text. The same text for the same incoming
        message is a duplicate; a new text (or a new incoming message) is a new key, so a
        skipped greeting block never shifts the following keys.
        """
        delays = self.pacing.plan(messages, incoming, self.rng)
        cause = str(customer.get("awaiting") or "manual")
        return [{"key": sender.message_key(customer["id"],
                                           f"{tag}:{cause}:{text_plain(text)}", None),
                 "text": text, "delay": delay}
                for text, delay in zip(messages, delays)]

    def _remember_sent(self, customer: dict, items: list[dict], results: list[dict],
                       kind: str, intent: str) -> tuple[bool, str]:
        states = {result["key"]: result["state"] for result in results}
        now = self.now().isoformat(timespec="seconds")
        worst = "sent"
        for item in items:
            state = states.get(item["key"], "not-sent")
            if state == "duplicate":
                continue
            if state in ("sent", "unconfirmed"):
                self.store.remember(customer["id"], {"at": now, "dir": "out",
                                                     "text": item["text"], "kind": kind,
                                                     "intent": intent, "state": state})
            if state != "sent":
                worst = state if worst == "sent" else worst
        return worst == "sent", worst

    def _fence(self, customer: dict, worst: str, what: str) -> None:
        self.store.update_lead(customer["id"], state="unconfirmed", awaiting=None,
                               handoff_reason=f"{what}: {worst}")
        self._handoff(customer, f"Envio não confirmado ({what}: {worst}); verifique a conversa",
                      "alert", "unconfirmed")

    def reply(self, customer: dict) -> dict:
        result = {"customer": customer["id"], "name": customer.get("name")}
        if self.store.is_blocked(customer):
            self.store.update_lead(customer["id"], state="do-not-contact", awaiting=None)
            return {**result, "state": "do-not-contact"}
        today = self.now().date().isoformat()
        replies = customer.get("replies") or {}
        if replies.get(today, 0) >= int(self.rules.limits["max_replies_per_customer_per_day"]):
            self.store.update_lead(customer["id"], state="needs-owner", awaiting=None,
                                   handoff_reason="limite diário de respostas")
            self._handoff(customer, "Limite diário de respostas automáticas atingido",
                          "needed", "reply_limit")
            return {**result, "state": "needs-owner"}
        if not self.live:
            planned = (customer["id"], str(customer.get("awaiting")))
            if planned in self._planned:
                return {**result, "state": "already-planned"}
            self._planned.add(planned)

        if self.live:
            self._next_chat(customer)
            try:
                status = self._open_chat(customer)
            except Exception as error:
                return {**result, "state": "error", "error": str(error)[:300]}
            if status != "ready":
                self.store.update_lead(customer["id"], state="unconfirmed", awaiting=None,
                                       handoff_reason="chat did not open")
                return {**result, "state": "unconfirmed"}
            typed = self._merge_chat(customer, self.channel.read_recent())
            if typed is not None:
                return self._owner_took_over(customer, typed, result)

        unanswered = awaiting_reply(self.store.history(customer["id"]))
        text = "\n".join(entry.get("text", "") for entry in unanswered).strip()
        customer = self.store.lead(customer["id"]) or customer
        if not text:
            self.store.update_lead(customer["id"], awaiting=None)
            return {**result, "state": "nothing-to-answer"}
        if customer.get("bot_replies", 0) >= int(self.rules.limits["max_bot_replies_before_owner"]) \
                and customer["state"] in ("ordering", "confirming"):
            turn = Turn([self.rules.texts["handoff_ack"]], "needs-owner", {},
                        "long_chat", self.rules.texts["owner_reason_unknown"], "needed")
        else:
            turn = self._turn(customer, text)
            if turn.intent == "greeting" and customer["state"] == "new":
                turn.intent = "greeting"

        problems = guard.violations(self.rules, turn.messages, turn.order) \
            if turn.messages else []
        if problems:
            self.store.log_decision({"at": stamp_now(self.now()), "lead": customer["id"],
                                     "live": self.live, "text": text,
                                     "intent": turn.intent, "source": turn.source,
                                     "violations": problems, "messages": turn.messages})
            turn = Turn([self.rules.texts["handoff_ack"]], "needs-owner", {},
                        turn.intent, "Mensagem bloqueada pelo guard: " + "; ".join(problems[:3]),
                        "alert")
            problems = guard.violations(self.rules, turn.messages, turn.order)

        self.store.log_decision({"at": stamp_now(self.now()), "lead": customer["id"],
                                 "live": self.live, "text": text, "intent": turn.intent,
                                 "action": turn.state, "source": turn.source,
                                 "violations": problems, "messages": turn.messages,
                                 "order": turn.order.number if turn.order else ""})
        result.update({"intent": turn.intent, "state": turn.state,
                       "messages": turn.messages})
        if self.store.is_blocked(customer):
            self.store.update_lead(customer["id"], state="do-not-contact", awaiting=None)
            return {**result, "state": "do-not-contact"}
        if not self.live:
            return {**result, "state": "planned"}

        if turn.messages:
            items = self._items(customer, f"{turn.state}#{customer.get('awaiting')}",
                                turn.messages, text)
            results = self.channel.send(customer, items, {
                "kind": "lanchonete-order", "lead": customer["id"], "intent": turn.intent})
            done, worst = self._remember_sent(customer, items, results, "reply", turn.intent)
            if not done:
                self._fence(customer, worst, "resposta")
                return {**result, "state": "unconfirmed"}
        if turn.block:
            self.store.block_customer(customer, "opt_out", self.now())
            listener.revoke_contact(self.store.contact_rules_path, self._entry(customer))
        changes = {"state": turn.state or customer["state"], "awaiting": None,
                   "replies": {today: replies.get(today, 0) + (1 if turn.messages else 0)},
                   "unknown_count": turn.updates.get("unknown_count",
                                                     customer.get("unknown_count", 0))}
        if turn.messages:
            changes["last_out_at"] = self.now().isoformat(timespec="seconds")
            changes["bot_replies"] = customer.get("bot_replies", 0) + 1
        if turn.updates:
            changes.update(turn.updates)
        self.store.update_lead(customer["id"], **changes)

        ficha = ""
        if turn.save_order and turn.order is not None:
            customer = self.store.lead(customer["id"])
            try:
                ficha = str(self.store.save_order(self.rules, turn.order, customer,
                                                   self.store.history(customer["id"]),
                                                   self.now(), self.rules.agent_name))
            except OSError as error:
                self.store.update_lead(customer["id"], state="needs-owner",
                                       handoff_reason=f"ficha do pedido não gravada: {error}")
                self._handoff(customer, "Pedido confirmado, mas a ficha não foi gravada; "
                              "confira o pedido na conversa", "alert", "order_ficha",
                              text, str(error))
                return {**result, "state": "needs-owner", "error": str(error)}
            self.store.update_lead(customer["id"], ficha=ficha,
                                   order_number=turn.order.number,
                                   state="confirmed", awaiting=None)
            self._handoff(customer,
                          f"Novo pedido {turn.order.number}: {brl(turn.order.total_cents(self.rules))}"
                          f" · {turn.order.kind_label()} · "
                          f"{turn.order.payment_label(self.rules)}",
                          "hot", "order_confirmed", text, ficha)
            result["ficha"] = ficha
            result["order"] = turn.order.number

        if turn.handoff_reason:
            self.store.update_lead(customer["id"], state="needs-owner",
                                   handoff_reason=turn.handoff_reason)
            self._handoff(self.store.lead(customer["id"]) or customer, turn.handoff_reason,
                          turn.priority or "needed", turn.intent, text)
        return {**result, "state": self.store.lead(customer["id"])["state"]}

    @staticmethod
    def _sent_before(text: str, history: list[dict]) -> bool:
        """A menu block already recorded as sent is not repeated by an owner opening."""
        needle = text_plain(text)
        if not needle:
            return True
        for entry in history:
            if entry.get("dir") != "out" or entry.get("state", "sent") != "sent":
                continue
            hay = text_plain(entry.get("text", ""))
            if hay and (needle[:30] in hay or hay[:30] in needle):
                return True
        return False

    def opening(self, customer: dict) -> dict:
        """Owner action: send the greeting and menu once, then keep the bot in charge.

        It never replays the old conversation; only a new opening is sent. A greeting already
        in the history is not repeated, so a customer who received the first bubble before a
        failed send continues from the menu.
        """
        result = {"customer": customer["id"], "name": customer.get("name")}
        customer = self.store.lead(customer["id"]) or customer
        now = self.now()
        history = self.store.history(customer["id"])
        greeting = self._greeting(now)
        already = any(entry.get("dir") == "out" and entry.get("state", "sent") == "sent"
                      and (entry.get("text") or "").startswith(greeting[:40])
                      for entry in history)
        messages = ([] if already else [greeting]) + list(self.rules.menu_messages()) + [
            self.rules.texts["menu_question"]]
        messages = [message for message in messages if not self._sent_before(message, history)]
        if not messages:
            self.store.update_lead(customer["id"], state="ordering", awaiting=None,
                                   awaiting_field="", closing=False, handoff_reason=None)
            return {**result, "state": "ordering", "messages": []}
        if not self.live:
            return {**result, "state": "planned", "messages": messages}
        self._next_chat(customer)
        try:
            status = self._open_chat(customer)
        except Exception as error:
            return {**result, "state": "error", "error": str(error)[:300]}
        if status != "ready":
            self.store.update_lead(customer["id"], state="unconfirmed", awaiting=None,
                                   handoff_reason="chat did not open")
            return {**result, "state": "unconfirmed"}
        # An owner-started opening is explicit: it does not read the old chat first, so a
        # message from the previous (sales) bot is never mistaken for the owner typing.
        delays = self.pacing.plan(messages, None, self.rng)
        items = [{"key": sender.message_key(customer["id"], f"opening:{text}", None),
                  "text": text, "delay": delay}
                 for text, delay in zip(messages, delays)]
        results = self.channel.send(customer, items, {
            "kind": "lanchonete-opening", "lead": customer["id"], "intent": "opening"})
        done, worst = self._remember_sent(customer, items, results, "opening", "opening")
        if not done:
            self._fence(customer, worst, "abertura")
            return {**result, "state": "unconfirmed"}
        self.store.update_lead(customer["id"], state="ordering", awaiting=None,
                               awaiting_field="", closing=False, unknown_count=0,
                               handoff_reason=None,
                               last_out_at=now.isoformat(timespec="seconds"),
                               bot_replies=customer.get("bot_replies", 0) + 1)
        return {**result, "state": "ordering"}

    def cycle(self, events: list[dict]) -> dict:
        summary = {"ingested": self.ingest(events), "replies": self.reply_pending()}
        summary["orders"] = [item.get("order") for item in summary["replies"]
                             if item.get("order")]
        return summary


def owner_resolve(store: LanchoneteStore, customer_id: str, state: str) -> dict:
    if state not in ("ordering", "confirming", "confirmed", "closed", "cancelled", "human"):
        raise ValueError("state must be ordering, confirming, confirmed, closed, cancelled "
                         "or human")
    customer = store.lead(customer_id)
    if customer is None:
        raise KeyError(customer_id)
    unanswered = awaiting_reply(store.history(customer_id))
    awaiting = f"resume-{len(store.history(customer_id))}" if unanswered else None
    return store.update_lead(customer_id, state=state, awaiting=awaiting,
                             handoff_reason=None, unknown_count=0, confirmations=0)


def owner_block(store: LanchoneteStore, customer_id: str, now: datetime) -> dict:
    customer = store.lead(customer_id)
    if customer is None:
        raise KeyError(customer_id)
    store.block_customer(customer, "owner", now)
    listener.revoke_contact(store.contact_rules_path,
                            "+" + customer["phone"] if customer.get("phone")
                            else customer.get("chat", ""))
    return store.update_lead(customer_id, state="do-not-contact", awaiting=None)


__all__ = ["LanchoneteAgent", "LanchoneteChannel", "Turn", "owner_block", "owner_resolve"]
