"""Conversation state machine of the Zaflas WhatsApp sales agent.

new ─opening─▶ opened ─no answer, 72 h─▶ followed-up ─no answer, 96 h─▶ no-response
                 │                           │
                 └──────── incoming ─────────┴─▶ engaged ◀─▶ qualifying ─▶ quote-requested
engaged ─refusal/opt-out─▶ do-not-contact      engaged ─unknown/call/media─▶ needs-owner
engaged ─already has site/later─▶ closed       any send not confirmed ─▶ unconfirmed
owner answered in the chat ─▶ owner            number without WhatsApp ─▶ invalid-number

Only `live` sends. Every send goes through `sender.send_sequence` (journal + fence); one
conversation at a time with a pause between chats.
"""

from __future__ import annotations

import random
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import listener, sender
from .context import effective
from .decide import Decision, decide
from .pacing import SalesPacing
from .rules import SalesRules, normalize
from .store import SalesStore, stamp

REPLYABLE = ("engaged", "qualifying")
# On a new incoming message these states move to `engaged`; others only record it.
REOPENS = ("new", "opened", "followed-up", "closed", "no-response", "engaged")
OWNER_STATES = ("needs-owner", "quote-requested", "owner", "unconfirmed")
NEXT_STATE = {"qualify": "qualifying", "quote": "quote-requested", "close": "closed",
              "block": "do-not-contact", "handoff": "needs-owner"}


def desktop_notify(title: str, body: str) -> None:
    try:
        subprocess.run(["notify-send", title, body], timeout=5, check=False)
    except Exception:
        pass


def _ours(text: str, sent: list[str]) -> bool:
    """A bubble is ours when it starts like a text we sent (link cards add text)."""
    plain = normalize(text)
    if not plain:
        return True
    return any(item and (item[:24] in plain or plain[:24] in item) for item in sent)


def split_pending(history: list[dict]) -> tuple[list[dict], list[dict]]:
    """(conversation before the unanswered messages, unanswered incoming messages)."""
    entries = effective(history)
    cut = len(entries)
    while cut and entries[cut - 1].get("dir") == "in":
        cut -= 1
    return entries[:cut], [entry for entry in entries[cut:] if entry.get("dir") == "in"]


class WhatsAppChannel:
    """The real browser path: the existing sender, DOM map and journal."""

    def __init__(self, page, pacing: SalesPacing, journal_path):
        self.page = page
        self.pacing = pacing
        self.journal_path = journal_path
        self.typing = sender.Pacing()

    def open(self, lead: dict) -> str:
        try:
            sender.open_chat(self.page, lead["name"], self.typing, phone=lead["phone"])
        except sender.InvalidNumber:
            return "invalid-number"
        return "ready"

    def read_recent(self) -> list[dict]:
        return sender.read_bubbles(self.page, 30)

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        return sender.send_sequence(self.page, lead["name"], items, self.typing,
                                    self.journal_path, extra=extra,
                                    link_wait=self.pacing.link_preview)


class SalesAgent:
    def __init__(self, rules: SalesRules, store: SalesStore, channel=None, llm=None,
                 live: bool = False, clock=None, sleep=time.sleep, rng=random,
                 notify=desktop_notify, log=None):
        self.rules = rules
        self.store = store
        self.channel = channel
        self.llm = llm
        self.live = live
        self.zone = ZoneInfo(rules.raw["timezone"])
        self.clock = clock or (lambda: datetime.now(self.zone))
        self.sleep = sleep
        self.rng = rng
        self.notify = notify
        self.log = log or (lambda message: print(f"[sales] {message}", flush=True))
        self.pacing = SalesPacing.from_rules(rules)
        self._chats = 0
        self._planned: set[tuple[str, str]] = set()
        if live and channel is None:
            raise ValueError("live mode needs a WhatsApp channel")

    # Helpers -------------------------------------------------------------------------
    def use_rules(self, rules: SalesRules) -> None:
        """Switch to an edited rules file between cycles (the owner tunes texts live)."""
        self.rules = rules
        self.pacing = SalesPacing.from_rules(rules)

    def now(self) -> datetime:
        return self.clock()

    def _parse(self, value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=self.zone)

    def _next_chat(self) -> None:
        if self._chats:
            self.sleep(self.pacing.between_chats(self.rng))
        self._chats += 1

    def _contact_entry(self, lead: dict) -> str:
        return "+" + lead["phone"]

    def contact_allowed(self, lead: dict) -> bool:
        """rules.json decides: allow mode needs one listed identity, block mode none."""
        rules = listener.load_rules(self.store.contact_rules_path)
        names = [name for name in (lead.get("chat"), self._contact_entry(lead), lead["name"])
                 if name]
        if rules["mode"] == "block":
            return all(listener.contact_allowed(name, rules) for name in names)
        return any(listener.contact_allowed(name, rules) for name in names)

    def _handoff(self, lead: dict, reason: str, text: str = "") -> None:
        now = self.now()
        self.store.log_handoff({"at": stamp(now), "lead": lead["id"], "name": lead["name"],
                                "state": lead.get("state"), "reason": reason, "text": text})
        self.notify("Zaflas vendas", f"{lead['name']}: {reason}")
        self.log(f"owner needed for {lead['name']}: {reason}")

    def openings_today(self) -> int:
        today = self.now().date()
        return sum(1 for lead in self.store.leads().values()
                   if (opened := self._parse(lead.get("opened_at")))
                   and opened.astimezone(self.zone).date() == today)

    def _items(self, lead: dict, tag: str, messages: list[str], incoming: str | None,
               delays: list[float] | None = None) -> list:
        delays = delays or self.pacing.plan(messages, incoming, self.rng)
        return [{"key": sender.message_key(lead["id"], f"{tag}#{index}", None), "text": text,
                 "delay": delay} for index, (text, delay) in enumerate(zip(messages, delays))]

    def _remember_sent(self, lead: dict, items: list[dict], results: list[dict], kind: str,
                       intent: str = "") -> tuple[bool, str]:
        """Record what was sent; return (all confirmed, worst state)."""
        states = {result["key"]: result["state"] for result in results}
        now = stamp(self.now())
        worst = "sent"
        for item in items:
            state = states.get(item["key"], "not-sent")
            if state == "duplicate":
                continue
            if state in ("sent", "unconfirmed"):
                self.store.remember(lead["id"], {"at": now, "dir": "out", "text": item["text"],
                                                 "kind": kind, "intent": intent, "state": state})
            if state != "sent":
                worst = state if worst == "sent" else worst
        return worst == "sent", worst

    def _fence(self, lead: dict, worst: str, what: str) -> None:
        self.store.update_lead(lead["id"], state="unconfirmed",
                               handoff_reason=f"{what}: {worst}")
        self._handoff(lead, f"envio não confirmado ({what}: {worst}); verifique a conversa")

    # Incoming ------------------------------------------------------------------------
    def ingest(self, events: list[dict]) -> list[str]:
        """Store listener events of funnel leads; other chats are never touched."""
        touched = []
        for event in events:
            lead = self.store.find_lead(event.get("chat", ""))
            if lead is None or not event.get("text"):
                continue
            history = self.store.history(lead["id"])
            if any(entry.get("event") == event.get("id") for entry in history):
                continue
            sent = [normalize(entry.get("text", "")) for entry in history[-40:]
                    if entry.get("dir") == "out"]
            if normalize(event["text"]) in sent:
                continue  # the chat list echoing our own last message
            now = stamp(self.now())
            self.store.remember(lead["id"], {"at": now, "dir": "in", "text": event["text"],
                                             "kind": "incoming", "event": event.get("id"),
                                             "message_at": event.get("message_at", ""),
                                             "source": "preview"})
            changes = {"last_in_at": now, "chat": event.get("chat") or lead.get("chat")}
            if lead["state"] in REOPENS:
                changes["state"] = "engaged"
                changes["awaiting"] = event.get("id")
                if lead["state"] == "new":
                    listener.allow_contact(self.store.contact_rules_path,
                                           self._contact_entry(lead))
            elif lead["state"] == "qualifying":
                changes["awaiting"] = event.get("id")
            elif lead["state"] == "do-not-contact":
                self._handoff(lead, "contato bloqueado voltou a escrever", event["text"])
            elif lead["state"] in OWNER_STATES:
                self._handoff(lead, "nova mensagem numa conversa com você", event["text"])
            self.store.update_lead(lead["id"], **changes)
            touched.append(lead["id"])
        return touched

    # Replies -------------------------------------------------------------------------
    def pending(self) -> list[dict]:
        leads = [lead for lead in self.store.leads().values()
                 if lead.get("awaiting") and lead["state"] in REPLYABLE]
        return sorted(leads, key=lambda lead: lead.get("last_in_at") or "")

    def reply_pending(self) -> list[dict]:
        if not self.rules.in_window(self.now(), "reply"):
            waiting = len(self.pending())
            if waiting:
                self.log(f"outside reply hours; {waiting} conversation(s) wait for the window")
            return []
        return [self.reply(lead) for lead in self.pending()]

    def _merge_chat(self, lead: dict, bubbles: list[dict]) -> str | None:
        """Add full incoming texts read in the chat; detect a reply the owner typed."""
        history = self.store.history(lead["id"])
        ours = [normalize(entry.get("text", "")) for entry in history if entry.get("dir") == "out"]
        last_out = max((index for index, bubble in enumerate(bubbles) if bubble["dir"] == "out"),
                       default=-1)
        if bubbles and bubbles[-1]["dir"] == "out" and not _ours(bubbles[-1]["text"], ours):
            return bubbles[-1]["text"]
        _, unanswered = split_pending(history)
        known = {normalize(entry.get("text", "")).rstrip(".… ") for entry in unanswered}
        previews = [entry for entry in unanswered if entry.get("source") == "preview"]
        now = stamp(self.now())
        for bubble in bubbles[last_out + 1:]:
            plain = normalize(bubble["text"])
            if bubble["dir"] != "in" or not plain or plain in known:
                continue
            entry = {"at": now, "dir": "in", "text": bubble["text"], "kind": "incoming",
                     "source": "chat"}
            for preview in previews:
                head = normalize(preview.get("text", "")).rstrip(".… ")
                if head and plain.startswith(head):
                    entry["replaces"] = preview.get("event")
            self.store.remember(lead["id"], entry)
        return None

    def reply(self, lead: dict) -> dict:
        result = {"lead": lead["id"], "name": lead["name"]}
        if self.store.is_dnc(lead["phone"]):
            self.store.update_lead(lead["id"], state="do-not-contact", awaiting=None)
            return {**result, "state": "do-not-contact"}
        if not self.contact_allowed(lead):
            self.store.update_lead(lead["id"], awaiting=None)
            self._handoff(lead, "contato fora da regra de respostas (rules.json)")
            return {**result, "state": "blocked-by-rules"}
        today = self.now().date().isoformat()
        replies = lead.get("replies") or {}
        if replies.get(today, 0) >= int(self.rules.limits["max_replies_per_lead_per_day"]):
            self.store.update_lead(lead["id"], state="needs-owner", awaiting=None,
                                   handoff_reason="limite diário de respostas")
            self._handoff(lead, "limite diário de respostas automáticas atingido")
            return {**result, "state": "needs-owner"}
        if not self.live:
            planned = (lead["id"], str(lead.get("awaiting")))
            if planned in self._planned:
                return {**result, "state": "already-planned"}
            self._planned.add(planned)
        if self.live:
            self._next_chat()
            try:
                status = self.channel.open(lead)
            except Exception as error:
                return {**result, "state": "error", "error": str(error)[:300]}
            if status != "ready":
                self.store.update_lead(lead["id"], state="invalid-number", awaiting=None)
                return {**result, "state": "invalid-number"}
            owner_text = self._merge_chat(lead, self.channel.read_recent())
            if owner_text is not None:
                self.store.remember(lead["id"], {"at": stamp(self.now()), "dir": "out",
                                                 "text": owner_text, "kind": "owner",
                                                 "state": "sent"})
                self.store.update_lead(lead["id"], state="owner", awaiting=None)
                self.log(f"{lead['name']}: the owner already answered; automation paused")
                return {**result, "state": "owner"}
        prior, unanswered = split_pending(self.store.history(lead["id"]))
        text = "\n".join(entry.get("text", "") for entry in unanswered).strip()
        if not text:
            self.store.update_lead(lead["id"], awaiting=None)
            return {**result, "state": "nothing-to-answer"}
        decision = decide(self.rules, lead, prior, text, self.llm, self.now(),
                          usage=self.store.log_usage)
        self.store.log_decision({"at": stamp(self.now()), "lead": lead["id"],
                                 "live": self.live, "text": text, **decision.record()})
        result.update({"intent": decision.intent, "action": decision.action,
                       "source": decision.source, "messages": decision.messages})
        if not self.live:
            return {**result, "state": "planned"}
        return self._apply(lead, decision, text, result, replies, today)

    def _apply(self, lead: dict, decision: Decision, text: str, result: dict, replies: dict,
               today: str) -> dict:
        lead = self.store.lead(lead["id"])
        if decision.messages:
            items = self._items(lead, f"reply#{lead['awaiting']}", decision.messages, text)
            results = self.channel.send(lead, items, {"kind": "sales-reply", "lead": lead["id"],
                                                      "intent": decision.intent})
            done, worst = self._remember_sent(lead, items, results, "reply", decision.intent)
            if not done:
                self._fence(lead, worst, "resposta")
                return {**result, "state": "unconfirmed"}
        state = NEXT_STATE.get(decision.action, lead["state"])
        if decision.action in ("reply", "ignore"):
            state = lead["state"] if lead["state"] in REPLYABLE else "engaged"
        changes = {"state": state, "awaiting": None,
                   "replies": {today: replies.get(today, 0) + (1 if decision.messages else 0)}}
        if decision.messages:
            changes["last_out_at"] = stamp(self.now())
        if decision.action == "block":
            self.store.add_dnc(lead["phone"], decision.intent, self.now())
            listener.revoke_contact(self.store.contact_rules_path, self._contact_entry(lead))
        if decision.action in ("handoff", "quote"):
            changes["handoff_reason"] = decision.intent
        self.store.update_lead(lead["id"], **changes)
        if decision.action in ("handoff", "quote"):
            self._handoff(lead, f"{decision.intent}: responda pessoalmente", text)
        return {**result, "state": state}

    # Openings and follow-ups ---------------------------------------------------------
    def prospect(self, limit: int | None = None) -> list[dict]:
        now = self.now()
        if not self.rules.in_window(now, "opening"):
            self.log("outside opening hours; no first contact now")
            return []
        remaining = int(self.rules.limits["daily_openings"]) - self.openings_today()
        if limit is not None:
            remaining = min(remaining, limit)
        if remaining <= 0:
            self.log("daily opening limit reached")
            return []
        candidates = sorted((lead for lead in self.store.leads().values()
                             if lead["state"] == "new" and not lead.get("opened_at")),
                            key=lambda lead: lead.get("imported_at") or "")
        results = []
        used = 0
        for lead in candidates:
            if used >= remaining:
                break
            outcome = self.open_lead(lead)
            results.append(outcome)
            if outcome["state"] in ("opened", "unconfirmed", "planned"):
                used += 1
            if outcome["state"] in ("error", "unconfirmed"):
                break
        return results

    def open_lead(self, lead: dict) -> dict:
        result = {"lead": lead["id"], "name": lead["name"]}
        if lead.get("opened_at") or lead["state"] != "new":
            return {**result, "state": "already-opened"}
        if self.store.is_dnc(lead["phone"]):
            self.store.update_lead(lead["id"], state="do-not-contact")
            return {**result, "state": "do-not-contact"}
        now = self.now()
        messages = self.rules.opening_messages(now)
        if not self.live:
            return {**result, "state": "planned", "messages": messages}
        items = self._items(lead, "opening", messages, None, self.rules.opening_delays())
        if any(sender.journal_state(self.store.journal_path, item["key"]) for item in items):
            self.store.update_lead(lead["id"], state="unconfirmed", opened_at=stamp(now))
            return {**result, "state": "already-opened"}
        self._next_chat()
        # Recorded before the browser acts, so a crash never sends the opening twice.
        self.store.update_lead(lead["id"], state="opening", opened_at=stamp(now))
        try:
            status = self.channel.open(lead)
        except Exception as error:
            self.store.update_lead(lead["id"], state="new", opened_at=None)
            return {**result, "state": "error", "error": str(error)[:300]}
        if status != "ready":
            self.store.update_lead(lead["id"], state="invalid-number", opened_at=None)
            return {**result, "state": "invalid-number"}
        listener.allow_contact(self.store.contact_rules_path, self._contact_entry(lead))
        results = self.channel.send(lead, items, {"kind": "sales-opening", "lead": lead["id"]})
        done, worst = self._remember_sent(lead, items, results, "opening")
        if not done:
            self._fence(lead, worst, "abertura")
            return {**result, "state": "unconfirmed"}
        self.store.update_lead(lead["id"], state="opened", last_out_at=stamp(self.now()))
        return {**result, "state": "opened"}

    def followups(self) -> list[dict]:
        now = self.now()
        limits = self.rules.limits
        results = []
        for lead in list(self.store.leads().values()):
            if lead.get("last_in_at"):
                continue
            last_out = self._parse(lead.get("last_out_at"))
            if last_out is None:
                continue
            waited = now - last_out
            if (lead["state"] == "opened" and lead.get("followups", 0) < int(limits["max_followups"])
                    and waited >= timedelta(hours=float(limits["followup_after_hours"]))):
                if self.rules.in_window(now, "opening"):
                    results.append(self._followup(lead))
            elif (lead["state"] in ("opened", "followed-up")
                  and waited >= timedelta(hours=float(limits["no_response_after_followup_hours"]))
                  and lead.get("followups", 0) >= int(limits["max_followups"])):
                self.store.update_lead(lead["id"], state="no-response")
                results.append({"lead": lead["id"], "name": lead["name"], "state": "no-response"})
        return results

    def _followup(self, lead: dict) -> dict:
        result = {"lead": lead["id"], "name": lead["name"]}
        messages = self.rules.followup_messages()
        if self.store.is_dnc(lead["phone"]):
            self.store.update_lead(lead["id"], state="do-not-contact")
            return {**result, "state": "do-not-contact"}
        if not self.live:
            return {**result, "state": "planned", "messages": messages}
        number = lead.get("followups", 0) + 1
        items = self._items(lead, f"followup#{number}", messages, None)
        self._next_chat()
        try:
            status = self.channel.open(lead)
        except Exception as error:
            return {**result, "state": "error", "error": str(error)[:300]}
        if status != "ready":
            self.store.update_lead(lead["id"], state="invalid-number")
            return {**result, "state": "invalid-number"}
        results = self.channel.send(lead, items, {"kind": "sales-followup", "lead": lead["id"]})
        self.store.update_lead(lead["id"], followups=number)
        done, worst = self._remember_sent(lead, items, results, "followup")
        if not done:
            self._fence(lead, worst, "follow-up")
            return {**result, "state": "unconfirmed"}
        self.store.update_lead(lead["id"], state="followed-up", last_out_at=stamp(self.now()))
        return {**result, "state": "followed-up"}

    # Cycle ---------------------------------------------------------------------------
    def cycle(self, events: list[dict], prospect: bool = False,
              limit: int | None = None) -> dict:
        """One pass: store incoming, answer, follow up, then (optionally) open new leads."""
        summary = {"ingested": self.ingest(events), "replies": self.reply_pending(),
                   "followups": self.followups()}
        summary["openings"] = self.prospect(limit) if prospect else []
        return summary


def owner_resolve(store: SalesStore, lead_id: str, state: str) -> dict:
    """The owner hands a conversation back (or closes it) after handling it personally."""
    if state not in ("engaged", "closed", "opened", "do-not-contact"):
        raise ValueError("state must be engaged, closed, opened or do-not-contact")
    lead = store.lead(lead_id)
    if lead is None:
        raise KeyError(lead_id)
    return store.update_lead(lead_id, state=state, awaiting=None, handoff_reason=None)


def owner_block(store: SalesStore, lead_id: str, now: datetime) -> dict:
    lead = store.lead(lead_id)
    if lead is None:
        raise KeyError(lead_id)
    store.add_dnc(lead["phone"], "owner", now)
    listener.revoke_contact(store.contact_rules_path, "+" + lead["phone"])
    return store.update_lead(lead_id, state="do-not-contact", awaiting=None)


__all__ = ["SalesAgent", "WhatsAppChannel", "owner_block", "owner_resolve", "split_pending"]
