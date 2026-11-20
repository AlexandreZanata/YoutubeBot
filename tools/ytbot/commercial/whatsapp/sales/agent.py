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
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import listener, sender
from . import central, dossier, guard, referral
from . import notify as owner_notify
from .context import effective
from .decide import Decision, _fixed, decide, stuck
from .pacing import SalesPacing
from .rules import SalesRules, normalize
from .queue import in_queue, order_key
from .store import SalesStore, reply_is_active, stamp
from .transcribe import local_transcriber

REPLYABLE = ("engaged", "qualifying", "gatekeeper")
# On a new incoming message these states move to `engaged`; others only record it.
REOPENS = ("new", "opened", "followed-up", "closed", "no-response", "engaged", "referred")
OWNER_STATES = ("needs-owner", "quote-requested", "owner", "unconfirmed", "won", "buying", "lost")
# Owner states where material the client still sends (receipt, logo) is saved silently.
SILENT_STATES = ("quote-requested", "won")
# A referral never re-opens a lead the owner is closing a sale with, one whose last send is
# uncertain, a number without WhatsApp or one on the do-not-contact list.
REFERRAL_KEEPS = ("owner", "quote-requested", "won", "buying", "unconfirmed", "opening",
                  "invalid-number", "do-not-contact")
NEXT_STATE = {"qualify": "qualifying", "collect": "qualifying", "quote": "quote-requested",
              "close": "closed", "block": "do-not-contact", "handoff": "needs-owner",
              "won": "won", "buy": "buying", "lose": "lost", "refer": "referred",
              "ask_referral": "needs-owner"}
OWNER_ACTIONS = ("handoff", "quote", "won", "buy", "lose", "ask_referral")
# An app or system already offered (the offer question was asked once): when the client keeps
# describing it, the requirements interview starts instead of offering again.
SYSTEM_OFFERS = ("system_request", "system_price", "app_at_site_price")
# A correction or an addition after the summary, not a plain "yes".
CORRECTION = re.compile(r"\b(mas|porem|faltou|falta|so que|corrig\w*|acrescent\w*|adicion\w*|"
                        r"esquec\w*|inclu\w*|tambem|alem disso|errad\w*|nao|mudar|alterar|trocar)\b")
CONFIRMED = re.compile(
    r"\b(certo|correto|exat\w*|isso mesmo|isso msm|perfeit\w*|esta certo|ta certo|"
    r"tudo certo|tudo ok|ta ok|pode seguir|pode mandar|pode tocar|manda ver|manda brasa|"
    r"bota pra frente|isso a[ie]|iss[ao]e|e isso a[ie]|positivo|afirmativo|confirmad[oa]|"
    r"confirmo|concordo|de acordo|fechou|combinado|beleza|blz|show|top|joia|maravilha|"
    r"tranquilo)\b"
)
SYSTEM_WORDS = re.compile(
    r"sistema|aplicativo|\bapps?\b|loja (virtual|online)|e-?commerce|"
    r"agendamento|cadastro|\blogin\b|painel|delivery|"
    r"cassino|tigrinho|jogo do bicho|jogo de (aposta|azar|cassino)|"
    r"\bbets?\b|aposta|roleta|caca[- ]?niquel|\bslots?\b|\bpoker\b|\bbingo\b|"
    r"\brifas?\b|sorteio|\bbolao\b|loteria|plataforma|marketplace|rede social|"
    r"\bleilao\b|\bsaas\b|streaming|area de membros|clube de assinatura|"
    r"portal (de|do|da|para|com)|cripto|exchange|\berp\b|\bcrm\b|\bpdv\b"
)
SITE_WORDS = re.compile(r"\bsite\b|institucional|pagina")


def interest_of(text: str) -> str:
    """"system", "site" or "" from what a message talks about."""
    plain = normalize(text)
    if SYSTEM_WORDS.search(plain):
        return "system"
    return "site" if SITE_WORDS.search(plain) else ""
MEDIA_TEXT = {"image": "[imagem]", "video": "[vídeo]", "document": "[documento]",
              "audio": "[áudio]"}


def _ours(text: str, sent: list[str]) -> bool:
    """A bubble is ours when it starts like a text we sent (link cards add text)."""
    plain = normalize(text)
    if not plain:
        return True
    return any(item and (item[:24] in plain or plain[:24] in item) for item in sent)


def is_closed_error(error: BaseException) -> bool:
    """The browser page or CDP connection closed (suspend/resume, Chrome restart)."""
    text = str(error)
    return (type(error).__name__ == "TargetClosedError" or "has been closed" in text
            or "Connection closed" in text or "Browser closed" in text)


def _failed_outcome(item: dict) -> bool:
    """True when an action (or its triggered referral opening) failed or is unconfirmed."""
    if item.get("state") in ("error", "unconfirmed"):
        return True
    ref = item.get("referral_opening")
    return isinstance(ref, dict) and ref.get("state") in ("error", "unconfirmed")


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
        self.current = None  # lead whose chat this page shows
        try:
            page.add_init_script(sender.MEDIA_HOOK)
        except Exception:
            pass

    def open(self, lead: dict) -> str:
        """Open the lead's chat; one already on screen is reused instead of reloading."""
        if self.current == lead["id"] and self._showing(lead.get("chat")):
            return "ready"
        self.current = None
        try:
            sender.open_chat(self.page, lead["name"], self.typing, phone=lead["phone"])
        except sender.InvalidNumber:
            return "invalid-number"
        self.current = lead["id"]
        return "ready"

    def _showing(self, chat: str | None) -> bool:
        if not chat:
            return False
        try:
            return (bool(self.page.locator(sender.COMPOSER).count())
                    and sender.chat_title(self.page) == chat)
        except Exception:
            return False

    def chat_title(self) -> str:
        return sender.chat_title(self.page)

    def is_typing(self) -> bool:
        return sender.is_typing(self.page)

    def read_recent(self) -> list[dict]:
        return sender.read_bubbles(self.page, 30)

    def fetch_media(self, bubble: dict) -> list[tuple[bytes, str]]:
        return sender.fetch_media(self.page, bubble.get("id", ""), bubble.get("media", ""))

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        return sender.send_sequence(self.page, lead["name"], items, self.typing,
                                    self.journal_path, extra=extra,
                                    link_wait=self.pacing.link_preview,
                                    debug_dir=self.journal_path.parent / "sales" / "debug")


class SalesAgent:
    def __init__(self, rules: SalesRules, store: SalesStore, channel=None, llm=None,
                 live: bool = False, clock=None, sleep=time.sleep, rng=random,
                 notify=owner_notify.desktop_notify, log=None, transcriber=None,
                 paced_openings: bool = False, allowed_leads: set[str] | None = None,
                 reply_debounce: float | None = None):
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
        self.paced_openings = paced_openings
        self.allowed_leads = set(allowed_leads) if allowed_leads is not None else None
        self._chats = 0
        self._last_chat = None
        self._last_was_opening = False
        self._last_activity_at: datetime | None = None
        self._next_opening_at: datetime | None = None
        self._last_blocker = ""
        self._central_mtime: float | None = None
        self._typing_cycle: set[str] = set()
        self._planned: set[tuple[str, str]] = set()
        # Opt-in: the live loop passes the rule value; unit tests keep answering at once.
        self.reply_debounce = float(reply_debounce or 0.0)
        if live and channel is None:
            raise ValueError("live mode needs a WhatsApp channel")

    # Helpers -------------------------------------------------------------------------
    def _channel_typing(self) -> bool:
        """True only when the open WhatsApp chat header shows the contact is typing."""
        checker = getattr(self.channel, "is_typing", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _typing_timed_out(self, lead: dict) -> bool:
        since = self._parse(lead.get("typing_since"))
        if since is None:
            return False
        return (self.now() - since).total_seconds() >= self.pacing.max_typing_wait

    def _mark_typing(self, lead: dict) -> dict:
        """Categorize the lead in the 'typing' wait state without sending any message."""
        fresh = self.store.lead(lead["id"]) or lead
        already = bool(fresh.get("typing"))
        since = fresh.get("typing_since") or stamp(self.now())
        if not already or not fresh.get("typing_since"):
            self.store.update_lead(lead["id"], typing=True, typing_since=since)
            if not already:
                self.log(f"{fresh['name']}: aguardando (digitando...)")
        return {"lead": lead["id"], "name": fresh["name"], "state": "typing", "action": "wait"}

    def _clear_typing(self, lead_id: str) -> None:
        fresh = self.store.lead(lead_id)
        if fresh and (fresh.get("typing") or fresh.get("typing_since")):
            self.store.update_lead(lead_id, typing=False, typing_since=None)

    def _in_scope(self, lead_id: str) -> bool:
        """When scoped (`--only-leads` / `--only-csv`), ignore leads outside the target batch."""
        return self.allowed_leads is None or lead_id in self.allowed_leads

    @staticmethod
    def _is_echo(plain: str, sent: list[str]) -> bool:
        """True when a chat-list preview is our own last message (including link/ellipsis)."""
        if not plain:
            return False
        if plain in sent:
            return True
        stripped = plain.rstrip(".… ")
        if len(stripped) >= 24 and any(item.startswith(stripped) for item in sent):
            return True
        return any(item.startswith("https://") and item in plain for item in sent)
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

    def _next_chat(self, lead: dict, opening: bool = False) -> None:
        """Pause between two different chats; consecutive cold openings use the opening interval."""
        if lead["id"] == self._last_chat:
            self._last_was_opening = opening
            return
        if self._chats:
            if opening and self._last_was_opening and not self.paced_openings:
                self.sleep(self.pacing.between_openings(self.rng))
            elif self.paced_openings and self._last_activity_at is not None:
                elapsed = (self.now() - self._last_activity_at).total_seconds()
                pause = self.pacing.between_chats(self.rng)
                if elapsed < pause:
                    self.sleep(pause - max(0.0, elapsed))
            else:
                self.sleep(self.pacing.between_chats(self.rng))
        self._chats += 1
        self._last_chat = lead["id"]
        self._last_was_opening = opening

    def _open_chat(self, lead: dict) -> str:
        """Open the lead's chat by number and remember the name WhatsApp shows for it.

        A number the owner saved ("Maria Padaria") is listed under that name, not the
        number, so the listener events only reach the lead through this binding. A name
        already bound to another lead is never taken over.
        """
        status = self.channel.open(lead)
        title_of = getattr(self.channel, "chat_title", None)
        if status != "ready" or not callable(title_of):
            return status
        title = (title_of() or "").strip()
        if title and title != lead.get("chat"):
            owner = self.store.find_lead(title)
            if owner is None or owner["id"] == lead["id"]:
                self.store.update_lead(lead["id"], chat=title)
                lead["chat"] = title
        return status

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

    def openings_today(self, kind: str | None = None) -> int:
        """First contacts started today: all, only "cold" or only "referral" ones."""
        today = self.now().date()
        return sum(1 for lead in self.store.leads().values()
                   if (opened := self._parse(lead.get("opened_at")))
                   and opened.astimezone(self.zone).date() == today
                   and (kind is None or bool(lead.get("referral")) == (kind == "referral")))

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
        """Store listener events of funnel leads; other chats are never touched.

        A contact showing the live 'digitando...' / 'typing...' indicator is categorized in
        the `typing` wait state without recording the indicator as an incoming text message.
        """
        touched = []
        typing_now: set[str] = set()
        for event in events:
            lead = self.store.find_lead(event.get("chat", ""))
            if lead is None or not self._in_scope(lead["id"]):
                continue
            if (event.get("kind") == "typing" or event.get("typing")
                    or listener.is_typing_text(event.get("text", ""))):
                typing_now.add(lead["id"])
                self._mark_typing(lead)
                continue
            if not event.get("text"):
                continue
            history = self.store.history(lead["id"])
            if any(entry.get("event") == event.get("id") for entry in history):
                continue
            sent = [normalize(entry.get("text", "")) for entry in history[-40:]
                    if entry.get("dir") == "out"]
            # Only our latest outgoing bubble can appear as a chat-list preview echo; older
            # opening bubbles like "Bom dia" or "Tudo bem?" must never swallow a real reply.
            if self._is_echo(normalize(event["text"]), sent[-1:]):
                continue  # the chat list echoing our own last message
            now = stamp(self.now())
            self.store.remember(lead["id"], {"at": now, "dir": "in", "text": event["text"],
                                             "kind": "incoming", "event": event.get("id"),
                                             "message_at": event.get("message_at", ""),
                                             "source": "preview"})
            typing_now.discard(lead["id"])
            changes = {"last_in_at": now, "chat": event.get("chat") or lead.get("chat"),
                       "typing": False, "typing_since": None}
            if not reply_is_active(lead) and lead["state"] not in ("do-not-contact",
                                                                       "invalid-number"):
                changes["state"] = "needs-owner"
                self.store.update_lead(lead["id"], **changes)
                if self._remind(lead):
                    self._handoff(lead, "Mensagem de um contato com respostas automáticas "
                                  "pausadas", event["text"], "needed")
                touched.append(lead["id"])
                continue
            if lead["state"] in REOPENS:
                changes["state"] = "engaged"
                changes["awaiting"] = event.get("id")
                if lead["state"] == "new":
                    listener.allow_contact(self.store.contact_rules_path,
                                           self._contact_entry(lead))
            elif lead["state"] in ("qualifying", "gatekeeper"):
                changes["awaiting"] = event.get("id")
            elif lead["state"] == "won":
                # After the Pix keys every message matters: a receipt or a question.
                changes["awaiting"] = event.get("id")
                paid = self.rules.intent("payment_sent").matches(normalize(event["text"]))
                if paid or self._remind(lead):
                    self._handoff(lead, self.rules.intent("payment_sent").reason if paid
                                  else "Cliente escreveu depois de receber as chaves Pix",
                                  event["text"], "hot", "payment_sent" if paid else "close_site")
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
        self._typing_cycle = typing_now
        return touched

    # Replies -------------------------------------------------------------------------
    def pending(self) -> list[dict]:
        leads = [lead for lead in self.store.leads().values()
                 if lead.get("awaiting") and lead["state"] in REPLYABLE + SILENT_STATES
                 and self._in_scope(lead["id"])]
        return sorted(leads, key=lambda lead: lead.get("last_in_at") or "")

    def _in_reply_debounce(self, lead: dict) -> bool:
        """True while the contact may still be typing another bubble.

        A person often sends two or three messages in a row; replying to the first
        one reads like a machine. The rules set the quiet window (default 30 s).
        """
        window = self.reply_debounce
        if window <= 0:
            return False
        last = self._parse(lead.get("last_in_at"))
        if last is None:
            return False
        return (self.now() - last).total_seconds() < window

    def reply_pending(self) -> list[dict]:
        if not self.rules.in_window(self.now(), "reply"):
            waiting = len(self.pending())
            if waiting:
                self.log(f"outside reply hours; {waiting} conversation(s) wait for the window")
            return []
        results = []
        for lead in self.pending():
            if self._in_reply_debounce(lead):
                self.log(f"{lead.get('name', lead['id'])}: aguardando "
                         f"{self.rules.pacing.get('reply_debounce_seconds', 30):.0f}s "
                         "para ver se vem outra mensagem")
                continue
            outcome = self.reply(lead)
            results.append(outcome)
            if _failed_outcome(outcome):
                break
        return results

    def _merge_chat(self, lead: dict, bubbles: list[dict]) -> list[str] | None:
        """Store what the contact sent since our last message, as read in the open chat.

        Texts replace the chat-list previews, images and voice messages are downloaded into
        the client folder and audio is transcribed. Returns the texts the owner typed when an
        outgoing message after our latest message was not sent by the bot.
        """
        history = self.store.history(lead["id"])
        ours = [normalize(entry.get("text", "")) for entry in history if entry.get("dir") == "out"]
        last_out = max((index for index, bubble in enumerate(bubbles) if bubble["dir"] == "out"),
                       default=-1)
        typed = self._owner_typed(bubbles, ours)
        if typed:
            return typed
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

    @staticmethod
    def _owner_typed(bubbles: list[dict], ours: list[str]) -> list[str]:
        """Texts the owner typed in the chat after our latest message, if any.

        Older personal messages (before the bot's latest turn, or from an archived test cycle)
        do not count. Without a bot message in view, only a last outgoing bubble the bot did not
        send counts.
        """
        anchor = max((index for index, bubble in enumerate(bubbles)
                      if bubble["dir"] == "out" and bubble.get("text")
                      and _ours(bubble["text"], ours)), default=None)
        if anchor is None:
            last = bubbles[-1] if bubbles else None
            if last and last["dir"] == "out" and not last.get("media") and \
                    not _ours(last["text"], ours):
                return [last["text"]]
            return []
        return [bubble["text"] for bubble in bubbles[anchor + 1:]
                if bubble["dir"] == "out" and bubble.get("text")
                and not _ours(bubble["text"], ours)]

    def _owner_took_over(self, lead: dict, texts: list[str], result: dict) -> dict:
        now = stamp(self.now())
        for text in texts:
            self.store.remember(lead["id"], {"at": now, "dir": "out", "text": text,
                                             "kind": "owner", "state": "sent"})
        self.store.update_lead(lead["id"], state="owner", awaiting=None)
        self.log(f"{lead['name']}: the owner wrote in the chat; automation paused")
        return {**result, "state": "owner"}

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
                fetched = self.channel.fetch_media(bubble) or []
            except Exception:
                fetched = []
            if fetched and isinstance(fetched, tuple):
                fetched = [fetched]
            folder = dossier.client_dir(self.store.root, lead)
            files = [dossier.save_media(folder, data, extension, media, now)
                     for data, extension in fetched]
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

    def _collect_system(self, lead: dict, decision: Decision, text: str) -> Decision:
        """App/system requirements: ask, restate, confirm the summary, then hand over.

        Owner, 2026-11-18: the bot does not hand the chat over as soon as the client wants a
        system; it asks gently until the requirements are clear, shows its understanding for
        the client to confirm, and only then passes the complete ficha to the owner.
        """
        texts = self.rules.brief_system
        work = {**lead, **decision.updates}
        brief, error = dossier.extract(self.rules, work, self.store.history(lead["id"]),
                                       self.llm, self.now(), usage=self.store.log_usage,
                                       kind="system")
        starting = bool(decision.start)
        turns = 0 if starting else int(lead.get("collect_turns", 0)) + 1
        stage = "asking" if starting else (lead.get("collect_stage") or "asking")
        buy = bool(work.get("buy_intent"))
        model_ready = self.llm is not None and not error
        decision.brief, decision.collect_turns = brief, turns
        decision.intent, decision.action = "quote_details", "collect"
        if stage == "confirming":
            confirmations = int(lead.get("confirmations", 0)) + 1
            plain = normalize(text)
            agreed = (not CORRECTION.search(plain)
                      and (bool(CONFIRMED.search(plain)) or bool(decision.updates.get("buy_intent"))
                           or bool(brief.get("cliente_terminou"))
                           or dossier.client_said_done(self.rules, text)
                           or any(re.search(pattern, plain)
                                  for pattern in self.rules.context["affirmative"])))
            summary = self._summary(brief) if model_ready else ""
            if agreed or not summary or confirmations >= int(texts["max_confirmations"]):
                return self._finish_system(decision, buy)
            # A correction or an addition: show the updated understanding once more.
            decision.updates.update(collect_stage="confirming", confirmations=confirmations)
            decision.messages = [texts["confirm_intro"], summary, texts["confirm_question"]]
            decision.source = "model"
            return decision
        question = (brief.get("proxima_pergunta") or "").strip()
        done = (not starting and (
                    dossier.client_said_done(self.rules, text)
                    or brief.get("cliente_terminou")
                    or (model_ready and not brief.get("faltando") and not question))
                or turns >= int(texts["max_collect_turns"])
                or (not model_ready and turns >= 2))
        start_key = {"buy": "start_buy", "custom": "start_custom"}.get(decision.start, "start")
        intro = list(texts[start_key]) if starting else []
        if done:
            summary = self._summary(brief) if model_ready else ""
            if not summary:
                return self._finish_system(decision, buy)
            decision.updates.update(collect_stage="confirming", confirmations=0)
            decision.messages = intro + [texts["confirm_intro"], summary, texts["confirm_question"]]
            decision.source = "model"
            return decision
        decision.updates.setdefault("collect_stage", "asking")
        if question:
            decision.messages, decision.source = intro + [question], "model"
        else:
            first_key = "first_question_custom" if decision.start == "custom" else "first_question"
            fallback = texts[first_key] if starting else texts["fallback_question"]
            decision.messages, decision.source = intro + [fallback], "fixed"
        return decision

    def _summary(self, brief: dict) -> str:
        """The client-facing summary to confirm; empty when it is missing or unsafe."""
        for key in ("confirmacao", "resumo"):
            text = (brief.get(key) or "").strip()
            if text and not guard.violations(self.rules, [text]):
                return text
        return ""

    def _finish_system(self, decision: Decision, buy: bool) -> Decision:
        texts = self.rules.brief_system
        decision.action = "buy" if buy else "quote"
        decision.messages = list(texts["done_messages_buy" if buy else "done_messages"])
        decision.source, decision.priority = "fixed", "hot"
        decision.owner_reason = ("Quer comprar o sistema: ficha de requisitos completa" if buy
                                 else "Ficha do sistema completa: orçamento a fazer")
        decision.updates.update(collect_stage="done")
        return decision

    def _collect(self, lead: dict, decision: Decision, text: str) -> Decision:
        """Gather the project details; finish the brief when complete or the client is done."""
        if (decision.updates.get("brief_kind") or lead.get("brief_kind")) == "system":
            return self._collect_system(lead, decision, text)
        history = self.store.history(lead["id"])
        brief, error = dossier.extract(self.rules, lead, history, self.llm, self.now(),
                                       usage=self.store.log_usage)
        turns = lead.get("collect_turns", 0) + 1
        model_ready = self.llm is not None and not error
        question = (brief.get("proxima_pergunta") or "").strip()
        asks_domain = (bool(brief.get("pedir_dominio"))
                       or bool(re.search(r"\bdomini|registro\.br|\.com\.br", normalize(question)))
                       or (bool(re.search(r"\bdomini|registro\.br", normalize(text)))
                           and "?" in text))
        kind = normalize(str((brief.get("pedido") or {}).get("tipo") or ""))
        only_mobile_app = bool(re.search(r"\baplicativo|\bapp\b", kind)) and "site" not in kind
        domain_sent = any("registro.br" in (entry.get("text") or "").lower()
                          for entry in effective(history)
                          if entry.get("dir") == "out" and entry.get("state", "sent") == "sent")
        done = (dossier.client_said_done(self.rules, text) or brief.get("cliente_terminou")
                or turns >= int(self.rules.brief["max_collect_turns"])
                or (not model_ready and turns >= 2)
                or (model_ready and not brief.get("faltando") and not question
                    and not brief.get("pedir_dominio")))
        decision.brief = brief
        decision.collect_turns = turns
        if done:
            intent = self.rules.intent("quote_details")
            decision.action, decision.source = "quote", "fixed"
            decision.messages = list(intent.messages)
            decision.priority, decision.owner_reason = intent.priority, intent.reason
        elif asks_domain and not only_mobile_app and not domain_sent:
            decision.messages = guard.split_links(list(self.rules.brief["domain_messages"]))
            decision.source = "fixed"
        elif asks_domain and not question:
            decision.messages = [self.rules.brief["domain_messages"][-1]]
            decision.source = "fixed"
        elif question:
            decision.messages = guard.split_links([question])
            decision.source = "model"
        else:
            decision.messages = [self.rules.brief["fallback_question"]]
            decision.source = "fixed"
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
        if lead["id"] in self._typing_cycle and not self._typing_timed_out(lead):
            return self._mark_typing(lead)
        if not self.live:
            planned = (lead["id"], str(lead.get("awaiting")))
            if planned in self._planned:
                return {**result, "state": "already-planned"}
            self._planned.add(planned)
        if self.live:
            self._next_chat(lead)
            try:
                status = self._open_chat(lead)
            except Exception as error:
                if is_closed_error(error):
                    self._last_chat = None
                    raise
                return {**result, "state": "error", "error": str(error)[:300]}
            if status != "ready":
                self._last_activity_at = self.now()
                self.store.update_lead(lead["id"], state="invalid-number", awaiting=None,
                                       typing=False, typing_since=None)
                return {**result, "state": "invalid-number"}
            if self._channel_typing() and not self._typing_timed_out(lead):
                return self._mark_typing(lead)
            owner_text = self._merge_chat(lead, self.channel.read_recent())
            if owner_text is not None:
                self._last_activity_at = self.now()
                self._clear_typing(lead["id"])
                return self._owner_took_over(lead, owner_text, result)
        if lead["state"] in SILENT_STATES:
            if not self.live:
                return {**result, "state": "planned", "action": "refresh-ficha"}
            status = {"won": "venda fechada: aguardando a entrada"}.get(lead["state"],
                                                                         "orçamento com o dono")
            ficha = self._write_dossier(lead, None, status)
            self.store.update_lead(lead["id"], awaiting=None, ficha=ficha,
                                   typing=False, typing_since=None)
            return {**result, "state": lead["state"], "ficha": ficha}
        prior, unanswered = split_pending(self.store.history(lead["id"]))
        text = "\n".join(entry.get("text", "") for entry in unanswered).strip()
        if not text:
            self.store.update_lead(lead["id"], awaiting=None, typing=False, typing_since=None)
            return {**result, "state": "nothing-to-answer"}
        decision = decide(self.rules, lead, prior, text, self.llm, self.now(),
                          usage=self.store.log_usage)
        decision = self._sales_turn(lead, decision, text)
        decision = self._check_progress(lead, decision)
        if decision.action == "collect":
            decision = self._collect(lead, decision, text)
        if self.live and decision.messages and self._channel_typing() \
                and not self._typing_timed_out(lead):
            # The contact started typing again while the model was thinking: wait for the rest.
            return self._mark_typing(lead)
        self._clear_typing(lead["id"])
        self.store.log_decision({"at": stamp(self.now()), "lead": lead["id"],
                                 "live": self.live, "text": text, **decision.record()})
        result.update({"intent": decision.intent, "action": decision.action,
                       "source": decision.source, "messages": decision.messages,
                       "model": decision.model})
        if not self.live:
            return {**result, "state": "planned"}
        return self._apply(lead, decision, text, result, replies, today)

    def _sales_turn(self, lead: dict, decision: Decision, text: str) -> Decision:
        """Turn a decision into the sales outcome the conversation reached.

        Closing the simple site sends the Pix keys; closing an app or a system goes to the
        owner; a refusal after real interest is "lost" (the owner decides), not a block; a staff
        member is asked for the decision maker's contact.
        """
        interest = interest_of(text) or lead.get("interest", "")
        interviewing = lead["state"] == "qualifying" and lead.get("brief_kind") == "system"
        if decision.intent == "ready_to_buy" and interest == "system" and interviewing:
            # Wants to close in the middle of the interview: finish the requirements first.
            decision = Decision("quote_details", "collect", [], "local", decision.hint,
                                updates={"buy_intent": True})
        elif decision.intent == "ready_to_buy" and interest == "system":
            decision = self._start_interview(decision, "buy")
        elif decision.intent == "custom_platform" and lead["state"] == "engaged":
            # Unusual or custom platform request: start the requirements interview directly.
            decision = self._start_interview(decision, "custom")
        elif interest == "system" and lead["state"] == "engaged" and (
                decision.intent in ("quote_accept", "unknown")
                or (decision.intent in SYSTEM_OFFERS
                    and any(item in SYSTEM_OFFERS for item in lead.get("intents") or []))):
            # Owner, 2026-11-18: never stop at "it is a different system"; understand it first.
            decision = self._start_interview(decision, "quote")
        elif decision.intent == "ready_to_buy" and interest == "site":
            decision = _fixed(self.rules, "close_site", decision.hint, "fixed")
        elif decision.intent == "ready_to_buy" and interest != "system":
            decision.owner_reason = "Quer fechar, mas não ficou claro se é site ou sistema"
        elif decision.intent == "refusal" and lead.get("interest"):
            decision.action, decision.priority = "ask_referral", "needed"
            decision.owner_reason = "Recusou depois de se interessar: pedido de indicação enviado"
        elif decision.intent == "gatekeeper" or (
                lead["state"] == "gatekeeper"
                and decision.intent not in ("referral", "forwarded_to_decider")):
            decision = self._gatekeeper(lead, decision, text)
        return decision

    def _start_interview(self, decision: Decision, start: str) -> Decision:
        """Begin the app/system requirements interview (the first question comes from _collect)."""
        return Decision("quote_details", "collect", [], "local", decision.hint, start=start,
                        updates={"brief_kind": "system", "buy_intent": start == "buy",
                                 "collect_stage": "asking", "confirmations": 0,
                                 "interest": "system"})

    def _gatekeeper(self, lead: dict, decision: Decision, text: str) -> Decision:
        found = referral.names(text, self.llm, f"zaflas-staff-{lead['id']}")
        staff = found["staff"] or lead.get("staff_name") or ""
        if found["staff"]:
            self.store.update_lead(lead["id"], staff_name=found["staff"])
        texts = self.rules.raw["referral"]
        if lead["state"] == "gatekeeper" and decision.intent == "gatekeeper":
            # Asked once already: close kindly instead of insisting.
            decision.action, decision.messages = "close", [texts["gave_up"]]
        elif lead["state"] == "gatekeeper" and found["staff"] and not lead.get("staff_name"):
            decision.action = "reply"
            decision.messages = [texts["ask_contact_again"].replace("{staff}", staff)]
        elif decision.intent == "gatekeeper" and not staff:
            decision.messages = list(decision.messages) + [texts["ask_name"]]
        decision.intent = decision.intent if decision.intent != "gatekeeper" else "gatekeeper"
        return decision

    def _referral_ask(self) -> list[str]:
        """The owner's indication request, always in short bubbles and only after a refusal."""
        ask = self.rules.raw.get("referral_ask") or {}
        if not ask.get("enabled"):
            return []
        return list(ask.get("messages") or [])

    def _refer(self, lead: dict, decision: Decision, text: str) -> Decision:
        """Save the number a staff member passed on as a new lead and thank them."""
        texts = self.rules.raw["referral"]
        numbers = referral.phones(text, own=lead["phone"])
        if not numbers:
            decision.action, decision.priority = "handoff", "needed"
            decision.owner_reason = texts["contact_card"]
            decision.messages = [texts["thanks_unnamed"].replace("{who}", texts["who_unnamed"])]
            return decision
        found = referral.names(text, self.llm, f"zaflas-staff-{lead['id']}")
        staff = found["staff"] or lead.get("staff_name") or ""
        decider = found["decider"]
        row = {"name": f"{decider or 'Responsável'} · {lead['name']}", "phone": numbers[0],
               "category": lead.get("category", ""), "city": lead.get("city", ""),
               "maps_url": lead.get("maps_url", ""),
               "note": f"Indicado por {staff or 'funcionário'} ({lead.get('label', '')})"}
        report = self.store.import_rows(
            [row], self.now(), "referral",
            extra={"referral": {"from": lead["id"], "staff": staff, "company": lead["name"],
                                "decider": decider}})
        if report["do_not_contact"]:
            decision.action, decision.priority = "handoff", "needed"
            decision.owner_reason = "O número indicado está na lista de não contatar"
        decision.referred = report["ids"][0] if report["ids"] else ""
        if report["duplicates"] and not report["ids"]:
            # Already a lead: the referral still gets its own opening (owner, 2026-11-18),
            # unless the owner is closing a sale there or a send to it is uncertain.
            known = self.store.find_lead(numbers[0])
            if known and known["id"] != lead["id"] and known["state"] not in REFERRAL_KEEPS:
                self._retarget(known, lead, staff, decider)
                decision.referred = known["id"]
            else:
                where = (f" ({known.get('label') or known['name']}, estado {known['state']})"
                         if known else "")
                decision.action, decision.priority = "handoff", "needed"
                decision.owner_reason = (f"O número indicado já está nos contatos{where}; "
                                         "decida como seguir com ele")
        if decision.referred and self.allowed_leads is not None:
            self.allowed_leads.add(decision.referred)
        who = decider or texts["who_unnamed"]
        thanks = texts["thanks"] if staff else texts["thanks_unnamed"]
        decision.messages = [thanks.replace("{staff}", staff).replace("{who}", who)]
        self.store.update_lead(lead["id"], staff_name=staff or lead.get("staff_name"))
        return decision

    def _retarget(self, known: dict, source: dict, staff: str, decider: str) -> None:
        """A referral to a number already in the contacts: a new cycle opened as a referral.

        The earlier conversation stays in its history; the new cycle keeps the journal keys
        of the first opening apart, so the referral opening is not mistaken for a repeat.
        """
        note = f"Indicado por {staff or 'funcionário'} ({source.get('label', '')})"
        self.store.update_lead(
            known["id"], state="new", opened_at=None, followups=0, last_out_at=None,
            last_in_at=None, awaiting=None, replies={}, handoff_reason=None, intents=[],
            bot_replies=0, collect_turns=0, cycle=int(known.get("cycle", 0)) + 1,
            note=note, referral={"from": source["id"], "staff": staff,
                                 "company": source["name"], "decider": decider})

    def _check_progress(self, lead: dict, decision: Decision) -> Decision:
        """Hand off when the bot is not moving the conversation toward a quote."""
        if decision.action not in ("reply", "qualify", "close") \
                or decision.intent in ("gatekeeper", "forwarded_to_decider"):
            return decision  # staff and forwarding flows have their own kind close
        intents = lead.get("intents") or []
        if intents and intents[-1] == decision.intent:
            return stuck(self.rules, decision.hint, "pergunta repetida")
        if lead.get("bot_replies", 0) >= int(self.rules.limits["max_bot_replies_before_owner"]):
            return stuck(self.rules, decision.hint, "conversa longa sem orçamento")
        return decision

    def _apply(self, lead: dict, decision: Decision, text: str, result: dict, replies: dict,
               today: str) -> dict:
        lead = self.store.lead(lead["id"])
        if decision.action == "refer":
            decision = self._refer(lead, decision, text)
            lead = self.store.lead(lead["id"])
        if decision.action == "ask_referral":
            decision.messages = self._referral_ask()
        if decision.messages:
            items = self._items(lead, f"reply#{lead['awaiting']}", decision.messages, text)
            results = self.channel.send(lead, items, {"kind": "sales-reply", "lead": lead["id"],
                                                      "intent": decision.intent})
            self._last_activity_at = self.now()
            done, worst = self._remember_sent(lead, items, results, "reply", decision.intent)
            if not done:
                self._fence(lead, worst, "resposta")
                return {**result, "state": "unconfirmed"}
        state = NEXT_STATE.get(decision.action, lead["state"])
        if decision.action in ("reply", "ignore"):
            state = lead["state"] if lead["state"] in REPLYABLE else "engaged"
            if decision.intent == "gatekeeper" or lead["state"] == "gatekeeper":
                state = "gatekeeper"
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
        if decision.action in OWNER_ACTIONS:
            changes["handoff_reason"] = decision.intent
        interest = interest_of(text) or lead.get("interest", "")
        if decision.intent in ("system_request", "system_price", "app_at_site_price",
                               "custom_platform"):
            interest = "system"
        elif decision.intent in ("site_institutional", "hosting", "domain", "close_site") and \
                interest != "system":
            interest = "site"
        if interest:
            changes["interest"] = interest
        if getattr(decision, "referred", ""):
            changes["referred_to"] = decision.referred
        ficha = ""
        changes.update(decision.updates)
        if decision.brief is not None:
            stage = decision.updates.get("collect_stage") or lead.get("collect_stage")
            status = ("pronta para orçamento" if decision.action == "quote"
                      else "quer comprar: ficha completa" if decision.action == "buy"
                      else "aguardando confirmação do cliente" if stage == "confirming"
                      else "coletando dados")
            ficha = self._write_dossier({**lead, **decision.updates}, decision.brief, status)
            changes.update(ficha=ficha, collect_turns=decision.collect_turns)
            result["ficha"] = ficha
        self.store.update_lead(lead["id"], **changes)
        if decision.action in OWNER_ACTIONS:
            self._handoff(lead, decision.owner_reason or decision.intent, text,
                          decision.priority or "needed", decision.intent, ficha)
        referred = getattr(decision, "referred", "")
        if referred and self.rules.in_window(self.now(), "opening") and \
                self.openings_today("referral") < int(self.rules.raw["referral"]["daily_limit"]):
            result["referral_opening"] = self.open_lead(self.store.lead(referred))
        return {**result, "state": state}

    # Openings and follow-ups ---------------------------------------------------------
    def opening_blocker(self, queue_only: bool = False) -> str:
        """Why no first contact may start now ("" when one may), in the owner's words."""
        hours = self.rules.raw["hours"]
        if not self.rules.in_window(self.now(), "opening"):
            days = ("segunda a sexta" if list(hours["opening_days"]) == [0, 1, 2, 3, 4]
                    else "nos dias de abertura")
            return (f"fora do horário de abertura ({hours['opening_start']} às "
                    f"{hours['opening_end']}, {days})")
        limit = int(self.rules.limits["daily_openings"])
        cold = limit - self.openings_today("cold")
        referral = int(self.rules.raw["referral"]["daily_limit"]) - self.openings_today("referral")
        if cold <= 0 and (queue_only or referral <= 0):
            return f"limite diário de {limit} aberturas atingido"
        return ""

    def reconcile_openings(self) -> list[dict]:
        """An opening that started and never finished (a crash) becomes unconfirmed.

        It is never sent again and the owner checks the chat. Only safe while this process
        holds the run lock, so no other process is in the middle of that send.
        """
        found = []
        for lead in list(self.store.leads().values()):
            if lead.get("state") != "opening":
                continue
            self.store.update_lead(lead["id"], state="unconfirmed",
                                   handoff_reason="abertura interrompida")
            self._handoff(lead, "Abertura interrompida antes de confirmar: confira a conversa "
                          "no WhatsApp; nada foi reenviado")
            found.append({"lead": lead["id"], "name": lead["name"], "state": "unconfirmed"})
        return found

    def _ensure_opening_cooldown(self) -> None:
        """On startup, honor the opening interval after any cold opening already sent today."""
        if self._next_opening_at is not None or not self.live:
            return
        now = self.now()
        today = now.date()
        recent = []
        for lead in self.store.leads().values():
            if lead.get("referral"):
                continue
            opened = self._parse(lead.get("opened_at"))
            if not opened or opened.astimezone(self.zone).date() != today:
                continue
            when = self._parse(lead.get("last_out_at") if lead.get("state") == "opened"
                               else lead.get("opened_at")) or opened
            recent.append(when.astimezone(self.zone))
        if not recent:
            return
        latest = max(recent)
        elapsed = (now - latest).total_seconds()
        if 0 <= elapsed < self.pacing.between_openings_min:
            wait = self.pacing.between_openings(self.rng)
            self._next_opening_at = latest + timedelta(seconds=wait)
            self.log(f"pacing openings: next company at {self._next_opening_at.strftime('%H:%M:%S')}")

    def _prospect_paced(self, limit: int | None = None) -> list[dict]:
        """Open at most one company when the opening cooldown has elapsed (non-blocking)."""
        if limit is not None and limit <= 0:
            return []
        if self.live:
            self._ensure_opening_cooldown()
            if self._next_opening_at is not None and self.now() < self._next_opening_at:
                return []
        results = self.prospect(1)
        if self.live and any(item["state"] in ("opened", "error") for item in results):
            wait = self.pacing.between_openings(self.rng)
            self._next_opening_at = self.now() + timedelta(seconds=wait)
            self.log(f"next opening in {wait:.0f}s (at {self._next_opening_at.strftime('%H:%M:%S')})")
        return results

    def prospect(self, limit: int | None = None, queue_only: bool = False) -> list[dict]:
        """Open new leads one at a time; `queue_only` keeps to the Maps queue (`sales queue`)."""
        blocked = self.opening_blocker(queue_only)
        if blocked:
            if blocked != self._last_blocker:
                self.log(f"no first contact now: {blocked}")
                self._last_blocker = blocked
            return []
        self._last_blocker = ""
        left = {"cold": int(self.rules.limits["daily_openings"]) - self.openings_today("cold"),
                "referral": int(self.rules.raw["referral"]["daily_limit"])
                - self.openings_today("referral")}
        # Referred numbers first: someone at the business asked us to talk to them. Maps
        # leads keep the owner's CSV order (`queue_position`). A lead whose chat failed
        # to open (`open_error`, nothing was typed) is skipped by the automatic run and
        # left for an explicit manual `queue send`; only an `unconfirmed` send (something
        # was typed) stops the line.
        candidates = sorted((lead for lead in self.store.leads().values()
                             if lead["state"] == "new" and not lead.get("opened_at")
                             and self._in_scope(lead["id"])
                             and (in_queue(lead) or not queue_only)
                             and (queue_only or not lead.get("open_error"))),
                            key=lambda lead: (not lead.get("referral"), *order_key(lead)))
        results = []
        for lead in candidates:
            kind = "referral" if lead.get("referral") else "cold"
            if left[kind] <= 0:
                continue
            if limit is not None and sum(1 for item in results
                                         if item["state"] in ("opened", "unconfirmed",
                                                              "planned")) >= limit:
                break
            outcome = self.open_lead(lead)
            results.append(outcome)
            if outcome["state"] in ("opened", "unconfirmed", "planned"):
                left[kind] -= 1
            if outcome["state"] in ("unconfirmed", "error"):
                # Never retried: unconfirmed stays fenced, error stays new with open_error.
                # A replacement goes to the end of the queue. The automatic run moves on;
                # an explicit manual `queue send` stops at the first unconfirmed instead.
                if not queue_only:
                    self._backfill(lead, outcome["state"])
                if outcome["state"] == "unconfirmed":
                    self.log(f"opening unconfirmed for {lead.get('name', lead['id'])}; "
                             "fenced, never retried"
                             + (", moving on" if not queue_only else ""))
                    if queue_only:
                        break
                else:
                    self.log(f"opening failed for {lead.get('name', lead['id'])} before "
                             f"typing ({outcome.get('error', 'error')}); skipping to the next")
        return results

    def _backfill(self, failed: dict, reason: str) -> None:
        """Replace a failed opening with the next owner-approved reserve lead."""
        try:
            rows = self.store.take_reserve(city=failed.get("city", "") or "", limit=1)
        except Exception as error:
            self.log(f"backfill indisponível: {error}")
            return
        if not rows:
            self.log(f"sem reserva para repor {failed.get('name', failed.get('id'))}; "
                     "o dono precisa aprovar mais empresas")
            return
        report = self.store.import_rows(rows, self.now(), "google-maps-manual")
        if report.get("imported"):
            added = rows[0].get("name", "?")
            self.log(f"backfill: {added} entrou no fim da fila no lugar de "
                     f"{failed.get('name', failed.get('id'))} ({reason})")
        else:
            self.log(f"backfill: reserva {rows[0].get('name', '?')} já era lead/DNC: "
                     f"{report.get('duplicates', 0)} duplicada(s), "
                     f"{len(report.get('rejected', []))} rejeitada(s)")

    def open_lead(self, lead: dict) -> dict:
        result = {"lead": lead["id"], "name": lead["name"]}
        if lead.get("opened_at") or lead["state"] != "new":
            return {**result, "state": "already-opened"}
        if self.store.is_dnc(lead["phone"]):
            self.store.update_lead(lead["id"], state="do-not-contact")
            return {**result, "state": "do-not-contact"}
        now = self.now()
        source = lead.get("referral") or {}
        messages = (self.rules.referral_opening(now, source.get("staff", ""),
                                                source.get("company", lead["name"]))
                    if source else self.rules.opening_messages(now, lead.get("name", "")))
        if not self.live:
            return {**result, "state": "planned", "messages": messages}
        items = self._items(lead, "opening", messages, None, self.rules.opening_delays())
        if any(sender.journal_state(self.store.journal_path, item["key"]) for item in items):
            self.store.update_lead(lead["id"], state="unconfirmed", opened_at=stamp(now))
            return {**result, "state": "already-opened"}
        self._next_chat(lead, opening=not bool(source))
        # Recorded before the browser acts, so a crash never sends the opening twice.
        self.store.update_lead(lead["id"], state="opening", opened_at=stamp(now))
        try:
            status = self._open_chat(lead)
        except Exception as error:
            # Nothing was typed yet: the lead stays new and the error is shown in the queue.
            closed = is_closed_error(error)
            self.store.update_lead(lead["id"], state="new", opened_at=None,
                                   open_error=None if closed else str(error)[:200])
            if closed:
                self._last_chat = None
                raise
            return {**result, "state": "error", "error": str(error)[:300]}
        if status != "ready":
            self._last_activity_at = self.now()
            self.store.update_lead(lead["id"], state="invalid-number", opened_at=None)
            return {**result, "state": "invalid-number"}
        listener.allow_contact(self.store.contact_rules_path, self._contact_entry(lead))
        self.store.update_lead(lead["id"], open_error=None)
        results = self.channel.send(lead, items, {"kind": "sales-opening", "lead": lead["id"]})
        self._last_activity_at = self.now()
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
            if not self._in_scope(lead["id"]) or lead.get("last_in_at"):
                continue
            if (lead["id"] in self._typing_cycle or lead.get("typing")) \
                    and not self._typing_timed_out(lead):
                continue
            last_out = self._parse(lead.get("last_out_at"))
            if last_out is None:
                continue
            waited = now - last_out
            if (lead["state"] == "opened" and lead.get("followups", 0) < int(limits["max_followups"])
                    and waited >= timedelta(hours=float(limits["followup_after_hours"]))):
                if self.rules.in_window(now, "opening"):
                    outcome = self._followup(lead)
                    results.append(outcome)
                    if _failed_outcome(outcome):
                        break
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
        self._next_chat(lead)
        try:
            status = self._open_chat(lead)
        except Exception as error:
            if is_closed_error(error):
                self._last_chat = None
                raise
            return {**result, "state": "error", "error": str(error)[:300]}
        if status != "ready":
            self._last_activity_at = self.now()
            self.store.update_lead(lead["id"], state="invalid-number")
            return {**result, "state": "invalid-number"}
        if self._channel_typing() and not self._typing_timed_out(lead):
            return self._mark_typing(lead)
        owner_text = self._merge_chat(lead, self.channel.read_recent())
        if owner_text is not None:
            self._last_activity_at = self.now()
            return self._owner_took_over(lead, owner_text, result)
        results = self.channel.send(lead, items, {"kind": "sales-followup", "lead": lead["id"]})
        self._last_activity_at = self.now()
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
        ingested = self.ingest(events)
        replies = self.reply_pending()
        still_typing = set(self._typing_cycle) | {
            item["lead"] for item in replies if item.get("state") == "typing"
        }
        for lead in list(self.store.leads().values()):
            if lead.get("typing") and lead["id"] not in still_typing:
                self._clear_typing(lead["id"])
        failed = any(_failed_outcome(item) for item in replies)
        followups = [] if failed else self.followups()
        failed = failed or any(_failed_outcome(item) for item in followups)
        if prospect and not failed:
            openings = (self._prospect_paced(limit) if self.paced_openings and self.live
                        else self.prospect(limit))
        else:
            openings = []
        summary = {"ingested": ingested, "replies": replies,
                   "followups": followups, "openings": openings,
                   "typing": sorted(still_typing)}
        try:
            leads_mtime = (self.store.leads_path.stat().st_mtime
                           if self.store.leads_path.exists() else None)
            if (any(summary.values()) or self._central_mtime is None
                    or leads_mtime != self._central_mtime):
                central.write(self.store, self.now())
                self._central_mtime = leads_mtime
        except OSError as error:
            self.log(f"central.json not written: {error}")
        return summary


def owner_resolve(store: SalesStore, lead_id: str, state: str) -> dict:
    """The owner hands a conversation back (or closes it) after handling it personally."""
    if state not in ("engaged", "qualifying", "closed", "opened", "do-not-contact"):
        raise ValueError("state must be engaged, qualifying, closed, opened or do-not-contact")
    lead = store.lead(lead_id)
    if lead is None:
        raise KeyError(lead_id)
    _, unanswered = split_pending(store.history(lead_id))
    awaiting = None
    if state in REPLYABLE and unanswered:
        # Messages that arrived while the owner had the chat are answered on the next cycle.
        awaiting = f"resume-{len(store.history(lead_id))}"
    return store.update_lead(lead_id, state=state, awaiting=awaiting, handoff_reason=None,
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
