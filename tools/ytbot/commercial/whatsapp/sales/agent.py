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
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import listener, sender
from . import dossier
from . import notify as owner_notify
from .context import effective
from .decide import Decision, decide, stuck
from .pacing import SalesPacing
from .rules import SalesRules, normalize
from .store import SalesStore, stamp
from .transcribe import local_transcriber

REPLYABLE = ("engaged", "qualifying")
# On a new incoming message these states move to `engaged`; others only record it.
REOPENS = ("new", "opened", "followed-up", "closed", "no-response", "engaged")
OWNER_STATES = ("needs-owner", "quote-requested", "owner", "unconfirmed")
NEXT_STATE = {"qualify": "qualifying", "collect": "qualifying", "quote": "quote-requested",
              "close": "closed", "block": "do-not-contact", "handoff": "needs-owner"}
MEDIA_TEXT = {"image": "[imagem]", "video": "[vídeo]", "document": "[documento]",
              "audio": "[áudio]"}


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
        try:
            page.add_init_script(sender.MEDIA_HOOK)
        except Exception:
            pass

    def open(self, lead: dict) -> str:
        try:
            sender.open_chat(self.page, lead["name"], self.typing, phone=lead["phone"])
        except sender.InvalidNumber:
            return "invalid-number"
        return "ready"

    def read_recent(self) -> list[dict]:
        return sender.read_bubbles(self.page, 30)

    def fetch_media(self, bubble: dict) -> tuple[bytes, str] | None:
        return sender.fetch_media(self.page, bubble.get("id", ""), bubble.get("media", ""))

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        return sender.send_sequence(self.page, lead["name"], items, self.typing,
                                    self.journal_path, extra=extra,
                                    link_wait=self.pacing.link_preview)


class SalesAgent:
    def __init__(self, rules: SalesRules, store: SalesStore, channel=None, llm=None,
                 live: bool = False, clock=None, sleep=time.sleep, rng=random,
                 notify=owner_notify.desktop_notify, log=None, transcriber=None):
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
        self.transcriber = transcriber or local_transcriber
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

    def _handoff(self, lead: dict, reason: str, text: str = "", priority: str = "alert",
                 intent: str = "", ficha: str = "") -> dict:
        """Record and notify a conversation the owner must take over, with the contact."""
        lead = self.store.lead(lead["id"]) or lead
        entry = owner_notify.handoff_entry(
            lead, self.store.history(lead["id"]), reason, priority, intent, text, self.now(),
            self.rules.raw.get("agent_name", "Alexandre"), ficha or lead.get("ficha") or "")
        self.store.log_handoff(entry)
        self.notify(entry)
        self.log(f"owner needed for {lead['name']} ({priority}): {reason}")
        return entry

    def _remind(self, lead: dict) -> bool:
        """One reminder per window for a chat already with the owner, not one per message."""
        window = timedelta(minutes=float(self.rules.limits["owner_reminder_minutes"]))
        for entry in reversed(self.store.handoffs()):
            if entry.get("lead") == lead["id"]:
                last = self._parse(entry.get("at"))
                return last is None or self.now() - last >= window
        return True

    def openings_today(self) -> int:
        today = self.now().date()
        return sum(1 for lead in self.store.leads().values()
                   if (opened := self._parse(lead.get("opened_at")))
                   and opened.astimezone(self.zone).date() == today)

    def _items(self, lead: dict, tag: str, messages: list[str], incoming: str | None,
               delays: list[float] | None = None) -> list:
        delays = delays or self.pacing.plan(messages, incoming, self.rng)
        cycle = f"c{lead['cycle']}:" if lead.get("cycle") else ""
        return [{"key": sender.message_key(lead["id"], f"{cycle}{tag}#{index}", None),
                 "text": text,
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
        self._handoff(lead, f"Envio não confirmado ({what}: {worst}); verifique a conversa")

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
            elif lead["state"] == "quote-requested":
                # Late material (logo, photos, audio) still goes into the client folder.
                changes["awaiting"] = event.get("id")
                if self._remind(lead):
                    self._handoff(lead, "Cliente mandou mais material para o orçamento",
                                  event["text"], "hot", "quote_details")
            elif lead["state"] == "do-not-contact":
                self._handoff(lead, "Contato bloqueado voltou a escrever", event["text"])
            elif lead["state"] in OWNER_STATES and self._remind(lead):
                self._handoff(lead, "Nova mensagem numa conversa que está com você",
                              event["text"], "needed")
            self.store.update_lead(lead["id"], **changes)
            touched.append(lead["id"])
        return touched

    # Replies -------------------------------------------------------------------------
    def pending(self) -> list[dict]:
        leads = [lead for lead in self.store.leads().values()
                 if lead.get("awaiting") and lead["state"] in REPLYABLE + ("quote-requested",)]
        return sorted(leads, key=lambda lead: lead.get("last_in_at") or "")

    def reply_pending(self) -> list[dict]:
        if not self.rules.in_window(self.now(), "reply"):
            waiting = len(self.pending())
            if waiting:
                self.log(f"outside reply hours; {waiting} conversation(s) wait for the window")
            return []
        return [self.reply(lead) for lead in self.pending()]

    def _merge_chat(self, lead: dict, bubbles: list[dict]) -> str | None:
        """Store what the contact sent since our last message, as read in the open chat.

        Texts replace the chat-list previews, images and voice messages are downloaded into
        the client folder and audio is transcribed. Returns the text the owner typed when the
        last bubble is an outgoing message the bot did not send.
        """
        history = self.store.history(lead["id"])
        ours = [normalize(entry.get("text", "")) for entry in history if entry.get("dir") == "out"]
        last_out = max((index for index, bubble in enumerate(bubbles) if bubble["dir"] == "out"),
                       default=-1)
        if (bubbles and bubbles[-1]["dir"] == "out" and not bubbles[-1].get("media")
                and not _ours(bubbles[-1]["text"], ours)):
            return bubbles[-1]["text"]
        _, unanswered = split_pending(history)
        seen = {entry.get("message_id") for entry in history if entry.get("message_id")}
        previews = [entry["event"] for entry in unanswered
                    if entry.get("source") == "preview" and entry.get("event")]
        entries = []
        for bubble in bubbles[last_out + 1:]:
            if bubble["dir"] != "in" or (bubble.get("id") and bubble["id"] in seen):
                continue
            entry = self._from_bubble(lead, bubble)
            if entry is not None:
                entries.append(entry)
        if entries and previews:
            entries[0]["replaces"] = previews
        for entry in entries:
            self.store.remember(lead["id"], entry)
        return None

    def _from_bubble(self, lead: dict, bubble: dict) -> dict | None:
        now = self.now()
        text = bubble.get("text", "")
        media = bubble.get("media", "")
        entry = {"at": stamp(now), "dir": "in", "kind": "incoming", "source": "chat",
                 "message_id": bubble.get("id", ""), "text": text}
        if not media:
            return entry if normalize(text) else None
        entry["media"] = media
        if text:
            entry["caption"] = text
        path = None
        if media in ("image", "audio"):
            try:
                fetched = self.channel.fetch_media(bubble)
            except Exception:
                fetched = None
            if fetched:
                folder = dossier.client_dir(self.store.root, lead)
                path = dossier.save_media(folder, fetched[0], fetched[1], media, now)
                entry["file"] = str(path.relative_to(folder))
        if media == "audio":
            transcript = ""
            if path is not None:
                try:
                    transcript = self.transcriber(path)
                except Exception as error:
                    entry["transcription_error"] = str(error)[:200]
            entry["text"] = transcript or MEDIA_TEXT["audio"]
            if transcript:
                entry["transcript"] = transcript
                self.log(f"{lead['name']}: voice message transcribed ({len(transcript)} chars)")
        elif not text:
            entry["text"] = MEDIA_TEXT.get(media, "[mídia]")
        return entry

    def _write_dossier(self, lead: dict, brief: dict | None, status: str) -> str:
        lead = self.store.lead(lead["id"]) or lead
        history = self.store.history(lead["id"])
        if brief is None:
            brief, _ = dossier.extract(self.rules, lead, history, self.llm, self.now(),
                                       usage=self.store.log_usage)
        path = dossier.write(self.store.root, lead, history, brief, status, self.now(),
                             self.rules.raw.get("agent_name", "Alexandre"))
        return str(path)

    def _collect(self, lead: dict, decision: Decision, text: str) -> Decision:
        """Gather the project details; finish the brief when complete or the client is done."""
        history = self.store.history(lead["id"])
        brief, error = dossier.extract(self.rules, lead, history, self.llm, self.now(),
                                       usage=self.store.log_usage)
        turns = lead.get("collect_turns", 0) + 1
        model_ready = self.llm is not None and not error
        done = (dossier.client_said_done(self.rules, text) or brief.get("cliente_terminou")
                or turns >= int(self.rules.brief["max_collect_turns"])
                or (not model_ready and turns >= 2)
                or (model_ready and not brief.get("faltando")
                    and not brief.get("proxima_pergunta")))
        decision.brief = brief
        decision.collect_turns = turns
        if done:
            intent = self.rules.intent("quote_details")
            decision.action, decision.source = "quote", "fixed"
            decision.messages = list(intent.messages)
            decision.priority, decision.owner_reason = intent.priority, intent.reason
        else:
            question = brief.get("proxima_pergunta") or ""
            decision.messages = [question or self.rules.brief["fallback_question"]]
            decision.source = "model" if question else "fixed"
        return decision

    def reply(self, lead: dict) -> dict:
        result = {"lead": lead["id"], "name": lead["name"]}
        if self.store.is_dnc(lead["phone"]):
            self.store.update_lead(lead["id"], state="do-not-contact", awaiting=None)
            return {**result, "state": "do-not-contact"}
        if not self.contact_allowed(lead):
            self.store.update_lead(lead["id"], awaiting=None)
            self._handoff(lead, "Contato fora da regra de respostas (rules.json)")
            return {**result, "state": "blocked-by-rules"}
        today = self.now().date().isoformat()
        replies = lead.get("replies") or {}
        if replies.get(today, 0) >= int(self.rules.limits["max_replies_per_lead_per_day"]):
            self.store.update_lead(lead["id"], state="needs-owner", awaiting=None,
                                   handoff_reason="limite diário de respostas")
            self._handoff(lead, "Limite diário de respostas automáticas atingido",
                          priority="needed")
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
        if lead["state"] == "quote-requested":
            if not self.live:
                return {**result, "state": "planned", "action": "refresh-ficha"}
            ficha = self._write_dossier(lead, None, "orçamento com o dono")
            self.store.update_lead(lead["id"], awaiting=None, ficha=ficha)
            return {**result, "state": "quote-requested", "ficha": ficha}
        prior, unanswered = split_pending(self.store.history(lead["id"]))
        text = "\n".join(entry.get("text", "") for entry in unanswered).strip()
        if not text:
            self.store.update_lead(lead["id"], awaiting=None)
            return {**result, "state": "nothing-to-answer"}
        decision = decide(self.rules, lead, prior, text, self.llm, self.now(),
                          usage=self.store.log_usage)
        decision = self._check_progress(lead, decision)
        if decision.action == "collect":
            decision = self._collect(lead, decision, text)
        self.store.log_decision({"at": stamp(self.now()), "lead": lead["id"],
                                 "live": self.live, "text": text, **decision.record()})
        result.update({"intent": decision.intent, "action": decision.action,
                       "source": decision.source, "messages": decision.messages})
        if not self.live:
            return {**result, "state": "planned"}
        return self._apply(lead, decision, text, result, replies, today)

    def _check_progress(self, lead: dict, decision: Decision) -> Decision:
        """Hand off when the bot is not moving the conversation toward a quote."""
        if decision.action not in ("reply", "qualify", "close"):
            return decision
        intents = lead.get("intents") or []
        if intents and intents[-1] == decision.intent:
            return stuck(self.rules, decision.hint, "pergunta repetida")
        if lead.get("bot_replies", 0) >= int(self.rules.limits["max_bot_replies_before_owner"]):
            return stuck(self.rules, decision.hint, "conversa longa sem orçamento")
        return decision

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
        if decision.action in ("reply", "qualify", "close") and decision.messages:
            changes["intents"] = ((lead.get("intents") or []) + [decision.intent])[-5:]
            changes["bot_replies"] = lead.get("bot_replies", 0) + 1
        if decision.action == "block":
            self.store.add_dnc(lead["phone"], decision.intent, self.now())
            listener.revoke_contact(self.store.contact_rules_path, self._contact_entry(lead))
        if decision.action in ("handoff", "quote"):
            changes["handoff_reason"] = decision.intent
        ficha = ""
        if decision.brief is not None:
            status = "pronta para orçamento" if decision.action == "quote" else "coletando dados"
            ficha = self._write_dossier(lead, decision.brief, status)
            changes.update(ficha=ficha, collect_turns=decision.collect_turns)
            result["ficha"] = ficha
        self.store.update_lead(lead["id"], **changes)
        if decision.action in ("handoff", "quote"):
            self._handoff(lead, decision.owner_reason or decision.intent, text,
                          decision.priority or "needed", decision.intent, ficha)
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
    return store.update_lead(lead_id, state=state, awaiting=None, handoff_reason=None,
                             intents=[], bot_replies=0)


def owner_reset(store: SalesStore, lead_id: str) -> dict:
    """Owner test only: archive the conversation and make the lead new again.

    Never used by the automation. A number on the do-not-contact list cannot be reset.
    """
    lead = store.lead(lead_id)
    if lead is None:
        raise KeyError(lead_id)
    if store.is_dnc(lead["phone"]):
        raise ValueError("the number is on the do-not-contact list")
    cycle = int(lead.get("cycle", 0)) + 1
    history = store.history_path(lead_id)
    if history.exists():
        history.rename(history.with_name(f"{lead_id}.cycle{cycle - 1}.jsonl"))
    return store.update_lead(lead_id, state="new", opened_at=None, followups=0,
                             last_out_at=None, last_in_at=None, awaiting=None, replies={},
                             handoff_reason=None, intents=[], bot_replies=0, collect_turns=0,
                             ficha=None, cycle=cycle)


def owner_block(store: SalesStore, lead_id: str, now: datetime) -> dict:
    lead = store.lead(lead_id)
    if lead is None:
        raise KeyError(lead_id)
    store.add_dnc(lead["phone"], "owner", now)
    listener.revoke_contact(store.contact_rules_path, "+" + lead["phone"])
    return store.update_lead(lead_id, state="do-not-contact", awaiting=None)


__all__ = ["SalesAgent", "WhatsAppChannel", "owner_block", "owner_reset", "owner_resolve",
           "split_pending"]
