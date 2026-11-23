"""End-to-end validation of a paced multi-company WhatsApp sales campaign.

Exercises the full production loop (`commands.run_cycles` -> `SalesAgent.cycle` ->
`sender.send_sequence` journal/fence -> `SalesStore` -> `central.json`) with synthetic
numbers and a stateful simulated WhatsApp channel that advances virtual time on every
bubble send, pause and scan tick. Never touches the real WhatsApp account or network.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sales_fixtures import MONDAY, PHONES, Clock, FakeModel, write_csv
from tools.ytbot.commercial.whatsapp import listener, sender
from tools.ytbot.commercial.whatsapp.sales import classifier, commands, queue
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent
from tools.ytbot.commercial.whatsapp.sales.pacing import SalesPacing
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore, canonical_phone, lead_id


class TargetClosedError(Exception):
    """Matches Playwright's TargetClosedError name for reconnect tests."""


CLINIC_ROWS = [
    {"name": "Vitalli Odontologia - Dentistas em Sinop", "phone": PHONES[0],
     "city": "Sinop", "category": "Clínica odontológica"},
    {"name": "Toledo Odontologia", "phone": PHONES[1],
     "city": "Sinop", "category": "Cirurgião dentista"},
    {"name": "Dra Francieli Secchi", "phone": PHONES[2],
     "city": "Sinop", "category": "Dentista"},
    {"name": "Silver Dent Sinop", "phone": PHONES[3],
     "city": "Sinop", "category": "Dentista"},
    {"name": "Dra Natalia Nogueira - Dentista em Sinop - Urgência 24h", "phone": PHONES[4],
     "city": "Sinop", "category": "Dentista"},
    {"name": "Dra Mychelle Zarbin - Dentista Urgência l 24h Sinop MT", "phone": PHONES[5],
     "city": "Sinop", "category": "Clínica odontológica"},
    {"name": "Vem Sorrir em Sinop.", "phone": PHONES[6],
     "city": "Sinop", "category": "Clínica odontológica"},
    {"name": "Doce Sorriso Odontologia | JULIO CAMPOS", "phone": PHONES[7],
     "city": "Sinop", "category": "Dentista"},
    {"name": "Dra. Débora Gobbi", "phone": PHONES[8],
     "city": "Sinop", "category": "Ortodontista"},
    {"name": "Clínica Salem", "phone": PHONES[9],
     "city": "Sinop", "category": "Dentista"},
]


class SimulatedWhatsApp:
    """Stateful multi-chat WhatsApp stand-in with per-lead bubble logs and real journaling."""

    def __init__(self, journal_path: Path, clock: Clock, invalid: set[str] | None = None,
                 fail_open_once: dict[str, Exception] | None = None,
                 send_states: dict[str, list[str]] | None = None):
        self.journal_path = journal_path
        self.clock = clock
        self.invalid = set(invalid or ())
        self.fail_open_once = dict(fail_open_once or {})
        self.send_states = {key: list(values) for key, values in (send_states or {}).items()}
        self.current_lead: dict | None = None
        self.bubbles: dict[str, list[dict]] = {}
        self.opened_log: list[tuple[str, object]] = []
        self.sent: list[dict] = []
        self.opening_windows: list[tuple[str, object, object]] = []
        self._bubble_seq = 0

    def push_incoming(self, lead_id_key: str, texts: list[str]) -> None:
        for text in texts:
            self._bubble_seq += 1
            self.bubbles.setdefault(lead_id_key, []).append(
                {"dir": "in", "text": text, "id": f"false_{lead_id_key}_{self._bubble_seq}",
                 "media": ""})

    def open(self, lead: dict) -> str:
        lid = lead["id"]
        if lid in self.fail_open_once:
            raise self.fail_open_once.pop(lid)
        self.opened_log.append((lid, self.clock()))
        if lid in self.invalid:
            self.current_lead = None
            return "invalid-number"
        self.current_lead = lead
        self.bubbles.setdefault(lid, [])
        return "ready"

    def chat_title(self) -> str:
        if not self.current_lead:
            return ""
        digits = self.current_lead["phone"]
        return f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"

    def read_recent(self) -> list[dict]:
        if not self.current_lead:
            return []
        return list(self.bubbles.get(self.current_lead["id"], []))

    def fetch_media(self, bubble: dict) -> list[tuple[bytes, str]]:
        return []

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        lid = lead["id"]
        started_at = self.clock()

        def deliver(page, text, pacing, delay=None, link_wait=0.0, **kwargs):
            self.clock.now += timedelta(seconds=float(delay or 2.0))
            queue_states = self.send_states.get(lid)
            state = queue_states.pop(0) if queue_states else "sent"
            if state == "sent":
                self._bubble_seq += 1
                self.bubbles.setdefault(lid, []).append(
                    {"dir": "out", "text": text, "id": f"true_{lid}_{self._bubble_seq}",
                     "media": ""})
                self.sent.append({"lead": lid, "text": text, "delay": delay, "at": self.clock(),
                                  "kind": (extra or {}).get("kind", "")})
            return state

        results = sender.send_sequence(None, lead["name"], items, sender.Pacing(),
                                       self.journal_path, extra=extra, deliver_fn=deliver)
        if (extra or {}).get("kind") == "sales-opening" and all(
                item["state"] == "sent" for item in results):
            self.opening_windows.append((lid, started_at, self.clock()))
        return results


class ScriptedPage:
    """Minimal Playwright page stand-in that advances virtual time on wait_for_timeout."""

    def __init__(self, clock: Clock):
        self.clock = clock

    def wait_for_timeout(self, ms: int) -> None:
        self.clock.now += timedelta(milliseconds=ms)


class ScriptedSession:
    def __init__(self, clock: Clock, channel: SimulatedWhatsApp):
        self.clock = clock
        self.page = ScriptedPage(clock)
        self.channel = channel
        self.reopened = 0

    def reopen(self, agent: SalesAgent, error: BaseException) -> None:
        self.reopened += 1
        self.page = ScriptedPage(self.clock)
        if agent.live:
            agent.channel = self.channel


class ScriptedLLM:
    """Deterministic model stand-in supporting replies and dossier JSON extraction."""

    def __init__(self, fail_chats: set[str] | None = None,
                 bad_price_chats: set[str] | None = None):
        self.fail_chats = set(fail_chats or ())
        self.bad_price_chats = set(bad_price_chats or ())
        self.calls: list[dict] = []

    def complete(self, messages, session_id, quick=False, long=False):
        from tools.ytbot.commercial.whatsapp.sales.llm import LlmError, LlmReply
        self.calls.append({"session_id": session_id, "quick": quick, "long": long})
        system_text = messages[0]["content"]
        user_text = messages[-1]["content"]
        if any(cid in session_id for cid in self.fail_chats):
            raise LlmError("HTTP 500: simulated upstream failure", "server")
        if any(cid in session_id for cid in self.bad_price_chats):
            payload = {"intent": "price", "messages": ["Faço por R$ 300 só hoje!"],
                       "handoff": False, "do_not_contact": False, "reason": "bad price"}
            return LlmReply(json.dumps(payload, ensure_ascii=False), "beam-free", 50, 20, 0.0, 10)
        if long:
            is_system = "sistema" in system_text.lower() or "aplicativo" in user_text.lower()
            if is_system:
                has_details = "dentista" in user_text.lower() or "navegador" in user_text.lower()
                brief = {
                    "empresa": {"nome": "Vem Sorrir em Sinop", "ramo": "Clínica odontológica",
                                "cidade": "Sinop", "contato": ""},
                    "pedido": {"tipo": "sistema de agendamento",
                               "objetivo": "agendar consultas online",
                               "funcionalidades": ["agendamento", "lembrete WhatsApp"],
                               "usuarios": "recepção e pacientes",
                               "onde_usa": "navegador", "integracoes": "WhatsApp",
                               "resumo": "Sistema de agendamento online para a clínica."},
                    "identidade": {"cores": "", "estilo": "", "tem_logo": False},
                    "dominio": {"desejado": "", "opcao": ""},
                    "midia": [], "duvidas": [],
                    "faltando": [] if has_details else ["quem vai usar e onde vai rodar"],
                    "proxima_pergunta": ("" if has_details
                                         else "Quem vai usar no dia a dia e prefere no celular "
                                              "ou no navegador do computador?"),
                    "confirmacao": ("Entendi que vocês precisam de um sistema de agendamento "
                                    "online no navegador para a recepção e pacientes, integrado "
                                    "ao WhatsApp." if has_details else ""),
                    "resumo": "Sistema de agendamento online para clínica odontológica.",
                    "cliente_terminou": False,
                }
            else:
                brief = {
                    "empresa": {"nome": "Vitalli Odontologia", "ramo": "Clínica odontológica",
                                "cidade": "Sinop", "contato": "seg a sex 8h-18h"},
                    "pedido": {"tipo": "site institucional",
                               "objetivo": "mostrar serviços odontológicos",
                               "servicos": ["implantes", "clareamento"],
                               "resumo": "Site institucional da Vitalli Odontologia."},
                    "identidade": {"cores": "branco e azul", "estilo": "limpo e moderno",
                                   "tem_logo": True},
                    "dominio": {"desejado": "vitalliodonto.com.br", "opcao": "nós compramos"},
                    "midia": [], "duvidas": [], "faltando": [], "pedir_dominio": False,
                    "proxima_pergunta": "",
                    "resumo": "Site institucional para Vitalli Odontologia em Sinop.",
                    "cliente_terminou": True,
                }
            return LlmReply(json.dumps(brief, ensure_ascii=False), "beam-free", 100, 60, 0.0, 12)
        if "staff" in session_id:
            return LlmReply(json.dumps({"staff": "Ana", "decider": "Dra Carla"},
                                       ensure_ascii=False), "beam-free", 30, 10, 0.0, 5)
        latest = user_text.rsplit("NOVA MENSAGEM DO CLIENTE:", 1)[-1].strip().lower()
        if latest in ("sim", "quero sim", "pode fazer"):
            payload = {"intent": "quote_accept", "messages": [], "handoff": False,
                       "do_not_contact": False, "reason": "accept"}
        elif "sistema" in latest or "agendamento" in latest:
            payload = {"intent": "system_request", "messages": [], "handoff": False,
                       "do_not_contact": False, "reason": "system"}
        elif "domínio" in latest or "dominio" in latest:
            payload = {"intent": "domain", "messages": [], "handoff": False,
                       "do_not_contact": False, "reason": "dominio"}
        elif "quanto custa" in latest or "valor" in latest:
            payload = {
                "intent": "price",
                "messages": [
                    "O site institucional fica em média R$ 500, com entrada de R$ 250, e "
                    "servidor de R$ 39,90 por mês no boleto ou Pix (ou R$ 45 no cartão).",
                    "Você gostaria que eu fizesse um orçamento?",
                ],
                "handoff": False, "do_not_contact": False, "reason": "price",
            }
        elif "bom dia" in latest or "tudo bem" in latest:
            payload = {
                "intent": "greeting_reply",
                "messages": ["Tudo ótimo, obrigado! Ficou com alguma dúvida sobre os exemplos?"],
                "handoff": False, "do_not_contact": False, "reason": "greeting",
            }
        else:
            payload = {"intent": "unknown", "messages": [], "handoff": True,
                       "do_not_contact": False, "reason": "out of scope"}
        return LlmReply(json.dumps(payload, ensure_ascii=False), "beam-free", 80, 30, 0.0, 8)


def _run_args(**overrides):
    defaults = {"rules": None, "max_chats": 30, "prospect": True, "limit": 10,
                "once": False, "max_cycles": 0, "interval": 2,
                "only_leads": None, "only_csv": None}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class CampaignEndToEndTests(unittest.TestCase):
    rules = load()
    rules.limits["auto_conversation"] = True  # automated mode under test

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.base = self.root / "whatsapp"
        self.store = SalesStore(self.base)
        self.clock = Clock(MONDAY)
        self.notes: list[dict] = []
        self.logs: list[str] = []

    def tearDown(self):
        self.directory.cleanup()

    def _sleep(self, seconds: float) -> None:
        self.clock.now += timedelta(seconds=float(seconds))

    def _import_clinics(self) -> tuple[Path, list[dict]]:
        csv_path = write_csv(self.root / "sinop-10.csv", CLINIC_ROWS)
        self.store.import_csv(csv_path, self.clock(), source="google-maps-manual")
        leads = [self.store.lead(lead_id(canonical_phone(row["phone"]))) for row in CLINIC_ROWS]
        return csv_path, leads

    def test_full_ten_company_campaign_interleaves_openings_and_multi_replies(self):
        # Pre-existing test leads that MUST NOT be touched when scoped to the CSV batch.
        self.store.import_rows(
            [{"name": "Felipe Teste", "phone": PHONES[20], "category": "Teste"},
             {"name": "João Teste", "phone": PHONES[21], "category": "Restaurante"}],
            self.clock() - timedelta(days=1), source="manual",
        )
        old_ids = list(self.store.leads().keys())
        self.store.update_lead(old_ids[0], state="owner", chat="Felipe")
        self.store.update_lead(old_ids[1], state="quote-requested", chat="João Flávio")

        csv_path, clinics = self._import_clinics()
        allowed = commands._allowed_leads(SimpleNamespace(only_leads=None, only_csv=str(csv_path)))
        self.assertEqual(len(allowed), 10)
        self.assertFalse(set(old_ids) & allowed)

        # Clinic #6 (index 5) has no WhatsApp: must be skipped cleanly without stalling #7..#10.
        invalid_id = clinics[5]["id"]
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock, invalid={invalid_id})
        llm = ScriptedLLM()
        agent = SalesAgent(self.rules, self.store, channel, llm, live=True,
                           clock=self.clock, sleep=self._sleep, rng=random.Random(42),
                           notify=self.notes.append, log=self.logs.append,
                           paced_openings=True, allowed_leads=allowed)
        session = ScriptedSession(self.clock, channel)

        # Scheduled events injected at realistic moments during and after the 10-company run.
        event_seq = 0
        delivered_triggers: set[str] = set()
        first_reply_before_second_opening = {"ok": False}

        def make_event(chat: str, text: str) -> dict:
            nonlocal event_seq
            event_seq += 1
            return {"id": f"ev-{event_seq}", "at": self.clock().isoformat(timespec="seconds"),
                    "message_at": self.clock().strftime("%H:%M"), "chat": chat,
                    "text": text, "unread": True, "allowed": True}

        def chat_of(lead: dict) -> str:
            digits = lead["phone"]
            return f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"

        def opened_count() -> int:
            return len(channel.opening_windows)

        def fake_listen(page, base, once=True, limit=30):
            events = []
            # Non-target chatter throughout the run: must be 100% ignored.
            if "noise-1" not in delivered_triggers and opened_count() >= 1:
                delivered_triggers.add("noise-1")
                events.append(make_event("Felipe", "oi, cadê você?"))
                events.append(make_event("João Flávio", "mandei outra foto"))
                events.append(make_event("Mãe", "bom dia filho"))
                events.append(make_event("Shopee", "Promoção de hoje!"))

            # Clinic #1 replies "Bom dia" (echo-bug regression!) 20s after opening #1,
            # BEFORE opening #2 happens!
            if ("c1-hello" not in delivered_triggers and opened_count() == 1
                    and self.clock() >= channel.opening_windows[0][2] + timedelta(seconds=20)):
                delivered_triggers.add("c1-hello")
                channel.push_incoming(clinics[0]["id"], ["Bom dia"])
                events.append(make_event(chat_of(clinics[0]), "Bom dia"))

            # Verify Clinic #1 got replied BEFORE Clinic #2 was opened!
            if ("c1-hello" in delivered_triggers and opened_count() == 1
                    and any(item["lead"] == clinics[0]["id"] and item["kind"] == "sales-reply"
                            for item in channel.sent)):
                first_reply_before_second_opening["ok"] = True

            # Clinic #1 continues the funnel: price -> accept quote -> details -> ficha.
            c1_replies = [item for item in channel.sent
                          if item["lead"] == clinics[0]["id"] and item["kind"] == "sales-reply"]
            if "c1-price" not in delivered_triggers and len(c1_replies) >= 1:
                delivered_triggers.add("c1-price")
                channel.push_incoming(clinics[0]["id"], ["Quanto custa um site?"])
                events.append(make_event(chat_of(clinics[0]), "Quanto custa um site?"))
            elif "c1-accept" not in delivered_triggers and len(c1_replies) >= 2:
                delivered_triggers.add("c1-accept")
                channel.push_incoming(clinics[0]["id"], ["Sim"])
                events.append(make_event(chat_of(clinics[0]), "Sim"))
            elif ("c1-details" not in delivered_triggers
                  and self.store.lead(clinics[0]["id"])["state"] == "qualifying"):
                delivered_triggers.add("c1-details")
                detail = ("Vitalli Odontologia em Sinop, implantes e clareamento, seg a sex "
                          "8h-18h, cores branco e azul, estilo limpo e moderno, domínio "
                          "vitalliodonto.com.br podem comprar")
                channel.push_incoming(clinics[0]["id"], [detail])
                events.append(make_event(chat_of(clinics[0]), detail))

            # Clinic #2 sends a LONG (>150 chars) WhatsApp Business auto-reply -> must ignore!
            if ("c2-auto" not in delivered_triggers
                    and self.store.lead(clinics[1]["id"])["state"] == "opened"):
                delivered_triggers.add("c2-auto")
                auto_msg = ("Olá! Bem-vindo à Toledo Odontologia! Agradecemos o seu contato. "
                            "Nosso horário de atendimento é de segunda a sexta das 08h às 18h. "
                            "Em breve nossa equipe retornará sua mensagem!")
                channel.push_incoming(clinics[1]["id"], [auto_msg])
                events.append(make_event(chat_of(clinics[1]), auto_msg))

            # Clinic #3: receptionist (gatekeeper) -> gives doctor's phone (referral)!
            if ("c3-staff" not in delivered_triggers
                    and self.store.lead(clinics[2]["id"])["state"] == "opened"):
                delivered_triggers.add("c3-staff")
                msg = "Aqui é da recepção, a Dra. está em atendimento, vou passar pra ela"
                channel.push_incoming(clinics[2]["id"], [msg])
                events.append(make_event(chat_of(clinics[2]), msg))
            elif ("c3-ref" not in delivered_triggers
                  and self.store.lead(clinics[2]["id"])["state"] == "gatekeeper"):
                delivered_triggers.add("c3-ref")
                msg = f"Sou a Ana, pode falar com a Dra Carla no {PHONES[25]}"
                channel.push_incoming(clinics[2]["id"], [msg])
                events.append(make_event(chat_of(clinics[2]), msg))

            # Clinic #4 refuses -> permanently blocked on do-not-contact list.
            if ("c4-refuse" not in delivered_triggers
                    and self.store.lead(clinics[3]["id"])["state"] == "opened"):
                delivered_triggers.add("c4-refuse")
                msg = "Nesse momento não estou precisando"
                channel.push_incoming(clinics[3]["id"], [msg])
                events.append(make_event(chat_of(clinics[3]), msg))

            # Clinic #5 cannot open links -> save-contact reply (no handoff), then asks domain.
            if ("c5-links" not in delivered_triggers
                    and self.store.lead(clinics[4]["id"])["state"] == "opened"):
                delivered_triggers.add("c5-links")
                msg = "Os links não abrem aqui"
                channel.push_incoming(clinics[4]["id"], [msg])
                events.append(make_event(chat_of(clinics[4]), msg))
            elif ("c5-domain" not in delivered_triggers
                  and any("salvar meu contato" in item["text"] for item in channel.sent
                          if item["lead"] == clinics[4]["id"])):
                delivered_triggers.add("c5-domain")
                msg = "O que é domínio?"
                channel.push_incoming(clinics[4]["id"], [msg])
                events.append(make_event(chat_of(clinics[4]), msg))

            # Clinic #7 (index 6, "Vem Sorrir em Sinop.") asks for scheduling system -> interview.
            if ("c7-sys" not in delivered_triggers
                    and self.store.lead(clinics[6]["id"])["state"] == "opened"):
                delivered_triggers.add("c7-sys")
                msg = "Quero um sistema de agendamento online para a clínica"
                channel.push_incoming(clinics[6]["id"], [msg])
                events.append(make_event(chat_of(clinics[6]), msg))
            elif ("c7-yes" not in delivered_triggers
                  and any("orçamento?" in item["text"] for item in channel.sent
                          if item["lead"] == clinics[6]["id"])):
                delivered_triggers.add("c7-yes")
                channel.push_incoming(clinics[6]["id"], ["Quero sim"])
                events.append(make_event(chat_of(clinics[6]), "Quero sim"))
            elif ("c7-desc" not in delivered_triggers
                  and self.store.lead(clinics[6]["id"])["state"] == "qualifying"):
                delivered_triggers.add("c7-desc")
                msg = "Para os dentistas e recepção no navegador, com lembrete no WhatsApp"
                channel.push_incoming(clinics[6]["id"], [msg])
                events.append(make_event(chat_of(clinics[6]), msg))
            elif ("c7-confirm" not in delivered_triggers
                  and self.store.lead(clinics[6]["id"]).get("collect_stage") == "confirming"):
                delivered_triggers.add("c7-confirm")
                channel.push_incoming(clinics[6]["id"], ["Issae chefia"])
                events.append(make_event(chat_of(clinics[6]), "Issae chefia"))

            # Clinic #8 asks to call back tomorrow -> hot handoff.
            if ("c8-later" not in delivered_triggers
                    and self.store.lead(clinics[7]["id"])["state"] == "opened"):
                delivered_triggers.add("c8-later")
                msg = "Agora estou atendendo, me chama amanhã"
                channel.push_incoming(clinics[7]["id"], [msg])
                events.append(make_event(chat_of(clinics[7]), msg))

            # Clinic #9 sends 3 bubbles in one burst -> site close -> Pix keys + won!
            if ("c9-burst" not in delivered_triggers
                    and self.store.lead(clinics[8]["id"])["state"] == "opened"):
                delivered_triggers.add("c9-burst")
                burst = ["Oi", "Gostei muito", "Quero fechar o site institucional"]
                channel.push_incoming(clinics[8]["id"], burst)
                events.append(make_event(chat_of(clinics[8]), burst[-1]))

            return events

        # Stop once all 10 clinics have been processed AND every scripted reply settled.
        all_done_at = {"when": None}

        def should_stop() -> bool:
            # 9 cold clinics opened + 1 invalid-number (#6) + 1 referral opened = 10 openings total.
            if self.store.lead(clinics[9]["id"])["state"] == "opened" and all_done_at["when"] is None:
                all_done_at["when"] = self.clock()
            if all_done_at["when"] is not None:
                return self.clock() >= all_done_at["when"] + timedelta(seconds=30)
            return self.clock() >= MONDAY + timedelta(hours=2)

        commands.run_cycles(agent, session, _run_args(limit=10, interval=2),
                            listen=fake_listen, out=lambda line: None, stopped=should_stop)

        # 1. Every clinic processed in strict CSV order (#6 skipped as invalid-number).
        cold_ids = [lead["id"] for lead in clinics if lead["id"] != invalid_id]
        cold_openings = [entry for entry in channel.opening_windows if entry[0] in cold_ids]
        self.assertEqual([entry[0] for entry in cold_openings], cold_ids)
        self.assertEqual(self.store.lead(invalid_id)["state"], "invalid-number")

        # 2. Every consecutive pair of cold openings waited strictly 2-3 minutes (120-180s).
        for prev, nxt in zip(cold_openings, cold_openings[1:]):
            gap = (nxt[1] - prev[2]).total_seconds()
            self.assertGreaterEqual(gap, 120.0, f"gap {gap:.1f}s < 120s between {prev[0]} and {nxt[0]}")
            self.assertLessEqual(gap, 340.0, f"gap {gap:.1f}s > 340s between {prev[0]} and {nxt[0]}")

        # 3. Non-blocking interleaving proven: Clinic #1 was answered BEFORE Clinic #2 opened!
        self.assertTrue(first_reply_before_second_opening["ok"],
                        "Clinic #1 should be answered during the 2-3 min wait before Clinic #2")

        # 4. Strict scope isolation: pre-existing test leads & personal chats NEVER touched.
        opened_ids = {lid for lid, _ in channel.opened_log}
        sent_ids = {item["lead"] for item in channel.sent}
        for old_id in old_ids:
            self.assertNotIn(old_id, opened_ids)
            self.assertNotIn(old_id, sent_ids)
        self.assertEqual(self.store.lead(old_ids[0])["state"], "owner")
        self.assertEqual(self.store.lead(old_ids[1])["state"], "quote-requested")
        self.assertFalse(any(note["lead"] in old_ids for note in self.notes))

        # 5. All clinic outcomes verified end-to-end.
        # Clinic #1: completed site quote + ficha
        c1 = self.store.lead(clinics[0]["id"])
        self.assertEqual(c1["state"], "quote-requested")
        self.assertTrue(c1.get("ficha") and Path(c1["ficha"]).is_file())
        # Clinic #2: long auto-reply ignored completely (only 4 opening bubbles sent)
        self.assertEqual(len([s for s in channel.sent if s["lead"] == clinics[1]["id"]]), 4)
        # Clinic #3: receptionist referred Dra Carla -> referral lead opened automatically
        c3 = self.store.lead(clinics[2]["id"])
        self.assertEqual(c3["state"], "referred")
        ref_id = c3["referred_to"]
        self.assertEqual(self.store.lead(ref_id)["state"], "opened")
        self.assertIn(ref_id, agent.allowed_leads)
        # Clinic #4: refused -> indication ask, then the owner takes over
        self.assertEqual(self.store.lead(clinics[3]["id"])["state"], "needs-owner")
        self.assertFalse(self.store.is_dnc(clinics[3]["phone"]))
        # Clinic #5: links_not_opening + domain (registro.br)
        c5_texts = [s["text"] for s in channel.sent if s["lead"] == clinics[4]["id"]]
        self.assertTrue(any("salvar meu contato" in t for t in c5_texts))
        self.assertIn("https://registro.br/", c5_texts)
        # Clinic #7 ("Vem Sorrir em Sinop." -> trailing dot stripped): system interview + ficha
        c7_open = [s["text"] for s in channel.sent
                   if s["lead"] == clinics[6]["id"] and s["kind"] == "sales-opening"]
        self.assertIn("a empresa Vem Sorrir em Sinop ainda não tem site.", c7_open[2])
        c7 = self.store.lead(clinics[6]["id"])
        self.assertEqual(c7["state"], "quote-requested")
        self.assertTrue(c7.get("ficha") and Path(c7["ficha"]).is_file())
        # Clinic #8: callback_later -> needs-owner (hot)
        self.assertEqual(self.store.lead(clinics[7]["id"])["state"], "needs-owner")
        # Clinic #9: multi-bubble burst -> close_site -> Pix keys sent + state won
        c9_texts = [s["text"] for s in channel.sent if s["lead"] == clinics[8]["id"]]
        self.assertEqual(self.store.lead(clinics[8]["id"])["state"], "won")
        self.assertIn("financeiro@zaflas.com.br", c9_texts)
        # Clinic #10: opened cleanly
        self.assertEqual(self.store.lead(clinics[9]["id"])["state"], "opened")

        # 6. Zero duplicate or unconfirmed journal entries; central.json valid.
        journal = sender.read_journal(self.store.journal_path)
        self.assertTrue(all(entry["state"] in ("started", "sent") for entry in journal))
        self.assertTrue(self.store.central_path.is_file())
        central_data = json.loads(self.store.central_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(central_data["fichas"]), 2)

    def test_simultaneous_multi_company_burst_answered_without_cross_contamination(self):
        _, clinics = self._import_clinics()
        five = clinics[:5]
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        # Simulate LLM failure on #1 and forbidden R$ 300 price hallucination on #2.
        llm = ScriptedLLM(fail_chats={five[0]["id"]}, bad_price_chats={five[1]["id"]})
        pauses: list[float] = []

        def record_sleep(seconds: float) -> None:
            pauses.append(seconds)
            self._sleep(seconds)

        agent = SalesAgent(self.rules, self.store, channel, llm, live=True,
                           clock=self.clock, sleep=record_sleep, rng=random.Random(9),
                           notify=self.notes.append, log=self.logs.append, paced_openings=True)
        for lead in five:
            self.store.update_lead(lead["id"], state="opened",
                                   opened_at=(self.clock() - timedelta(hours=1)).isoformat())
            listener.allow_contact(self.store.contact_rules_path, "+" + lead["phone"])

        prompts = [
            (five[0], "Quanto custa?"),              # LLM fails -> safe local fixed fallback
            (five[1], "Qual o valor de um site?"),   # LLM invents R$ 300 -> guard blocks -> template
            (five[2], "Isso é robô?"),               # Honest fixed answer
            (five[3], "Não tenho interesse"),        # Refusal -> do-not-contact
            (five[4], "Me liga às 15h"),             # Call request -> hot handoff
        ]
        events = []
        for idx, (lead, text) in enumerate(prompts, start=1):
            channel.push_incoming(lead["id"], [text])
            digits = lead["phone"]
            chat = f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"
            events.append({"id": f"burst-{idx}", "at": self.clock().isoformat(timespec="seconds"),
                           "message_at": "09:30", "chat": chat, "text": text,
                           "unread": True, "allowed": True})

        summary = agent.cycle(events, prospect=False)
        self.assertEqual(len(summary["ingested"]), 5)
        self.assertEqual(len(summary["replies"]), 5)
        # Switching between replies uses fast between_chats (10-30s), NOT 120-180s!
        self.assertEqual(len(pauses), 4)
        self.assertTrue(all(10.0 <= p <= 30.0 for p in pauses), pauses)
        # Guard blocked the hallucinated R$ 300 completely.
        all_texts = [item["text"] for item in channel.sent]
        self.assertFalse(any("300" in text for text in all_texts))
        # Each company got the right independent state.
        self.assertEqual(self.store.lead(five[0]["id"])["state"], "engaged")
        self.assertEqual(self.store.lead(five[1]["id"])["state"], "engaged")
        self.assertEqual(self.store.lead(five[2]["id"])["state"], "engaged")
        self.assertEqual(self.store.lead(five[3]["id"])["state"], "needs-owner")
        self.assertEqual(self.store.lead(five[4]["id"])["state"], "needs-owner")

    def test_transient_browser_close_during_opening_and_reply_reconnects_without_duplicate(self):
        _, clinics = self._import_clinics()
        first, second = clinics[0], clinics[1]
        channel = SimulatedWhatsApp(
            self.store.journal_path, self.clock,
            fail_open_once={second["id"]: TargetClosedError("Target page has been closed")},
        )
        agent = SalesAgent(self.rules, self.store, channel, None, live=True,
                           clock=self.clock, sleep=self._sleep, rng=random.Random(1),
                           notify=self.notes.append, log=self.logs.append, paced_openings=True)
        session = ScriptedSession(self.clock, channel)

        reply_injected = {"done": False}
        reply_close_armed = {"done": False}

        def fake_listen(page, base, once=True, limit=30):
            if (not reply_injected["done"]
                    and self.store.lead(second["id"])["state"] == "opened"):
                reply_injected["done"] = True
                # Arm a second transient browser closure right before opening Clinic #1 to reply!
                if not reply_close_armed["done"]:
                    reply_close_armed["done"] = True
                    channel.fail_open_once[first["id"]] = TargetClosedError("Connection closed")
                channel.push_incoming(first["id"], ["Quanto custa?"])
                digits = first["phone"]
                chat = f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"
                return [{"id": "rep-1", "at": self.clock().isoformat(timespec="seconds"),
                         "message_at": "09:10", "chat": chat, "text": "Quanto custa?",
                         "unread": True, "allowed": True}]
            return []

        def should_stop() -> bool:
            return (self.store.lead(first["id"])["state"] == "engaged"
                    and self.store.lead(first["id"])["awaiting"] is None
                    and self.store.lead(second["id"])["state"] == "opened")

        commands.run_cycles(agent, session, _run_args(limit=2, interval=2),
                            listen=fake_listen, out=lambda line: None, stopped=should_stop)

        self.assertEqual(session.reopened, 2, "both closed-page errors reconnected cleanly")
        self.assertEqual(len([s for s in channel.sent
                              if s["lead"] == second["id"] and s["kind"] == "sales-opening"]), 4)
        self.assertGreater(len([s for s in channel.sent
                                if s["lead"] == first["id"] and s["kind"] == "sales-reply"]), 0)

    def test_restart_mid_campaign_preserves_progress_and_opening_cooldown(self):
        _, clinics = self._import_clinics()
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        agent1 = SalesAgent(self.rules, self.store, channel, None, live=True,
                            clock=self.clock, sleep=self._sleep, rng=random.Random(5),
                            notify=self.notes.append, log=self.logs.append, paced_openings=True)
        # Open Clinic #1 and #2 before simulated restart (5-minute spacing).
        agent1.cycle([], prospect=True, limit=10)
        self.clock.now += timedelta(seconds=340)
        agent1.cycle([], prospect=True, limit=10)
        self.assertEqual(len(channel.opening_windows), 2)
        second_finished = channel.opening_windows[1][2]

        # Simulate SIGTERM + restart 40 seconds later with a fresh SalesAgent instance.
        self.clock.now = second_finished + timedelta(seconds=40)
        agent2 = SalesAgent(self.rules, self.store, channel, None, live=True,
                            clock=self.clock, sleep=self._sleep, rng=random.Random(6),
                            notify=self.notes.append, log=self.logs.append, paced_openings=True)
        # Must NOT open Clinic #3 yet (only 40s elapsed < 300s), MUST still answer Clinic #1!
        channel.push_incoming(clinics[0]["id"], ["Isso é robô?"])
        digits = clinics[0]["phone"]
        chat = f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"
        ev = [{"id": "after-restart", "at": self.clock().isoformat(timespec="seconds"),
               "message_at": "09:05", "chat": chat, "text": "Isso é robô?",
               "unread": True, "allowed": True}]
        summary = agent2.cycle(ev, prospect=True, limit=10)
        self.assertEqual(summary["openings"], [], "cooldown from persisted opened_at holds")
        self.assertEqual(len(summary["replies"]), 1, "replies still work during opening cooldown")
        # Once past the 5-minute cooldown, Clinic #3 opens cleanly and #1/#2 are never repeated.
        self.clock.now = second_finished + timedelta(seconds=340)
        summary2 = agent2.cycle([], prospect=True, limit=10)
        self.assertEqual([item["lead"] for item in summary2["openings"]], [clinics[2]["id"]])
        self.assertEqual(len([s for s in channel.sent
                              if s["lead"] == clinics[0]["id"] and s["kind"] == "sales-opening"]), 4)

    def test_run_limit_caps_total_openings_across_cycles_while_keeping_listener_alive(self):
        _, clinics = self._import_clinics()
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        agent = SalesAgent(self.rules, self.store, channel, None, live=True,
                           clock=self.clock, sleep=self._sleep, rng=random.Random(3),
                           notify=self.notes.append, log=self.logs.append, paced_openings=True)
        session = ScriptedSession(self.clock, channel)
        sent_late_reply = {"done": False}

        def fake_listen(page, base, once=True, limit=30):
            if not sent_late_reply["done"] and len(channel.opening_windows) == 3:
                sent_late_reply["done"] = True
                channel.push_incoming(clinics[0]["id"], ["Isso é robô?"])
                digits = clinics[0]["phone"]
                chat = f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"
                return [{"id": "late-1", "at": self.clock().isoformat(timespec="seconds"),
                         "message_at": "09:20", "chat": chat, "text": "Isso é robô?",
                         "unread": True, "allowed": True}]
            return []

        # Run 20 simulated minutes with limit=3 (5-minute spacing needs ~15 min for 3).
        commands.run_cycles(
            agent, session, _run_args(limit=3, interval=5),
            listen=fake_listen, out=lambda line: None,
            stopped=lambda: self.clock() >= MONDAY + timedelta(minutes=20),
        )
        self.assertEqual(len(channel.opening_windows), 3)
        self.assertEqual(self.store.lead(clinics[3]["id"])["state"], "new")
        self.assertEqual(self.store.lead(clinics[0]["id"])["state"], "engaged")

    def test_unconfirmed_reply_aborts_cycle_and_never_opens_next_company(self):
        _, clinics = self._import_clinics()
        first, second, third = clinics[0], clinics[1], clinics[2]
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock,
                                    send_states={first["id"]: ["unconfirmed"]})
        agent = SalesAgent(self.rules, self.store, channel, None, live=True,
                           clock=self.clock, sleep=self._sleep, rng=random.Random(2),
                           notify=self.notes.append, log=self.logs.append, paced_openings=True)
        for lead in (first, second):
            self.store.update_lead(lead["id"], state="opened",
                                   opened_at=(self.clock() - timedelta(hours=1)).isoformat())
            listener.allow_contact(self.store.contact_rules_path, "+" + lead["phone"])
            channel.push_incoming(lead["id"], ["Quanto custa?"])

        events = []
        for idx, lead in enumerate((first, second), start=1):
            digits = lead["phone"]
            chat = f"+{digits[:2]} {digits[2:4]} {digits[4:9]}-{digits[9:]}"
            events.append({"id": f"u-{idx}", "at": self.clock().isoformat(timespec="seconds"),
                           "message_at": "09:15", "chat": chat, "text": "Quanto custa?",
                           "unread": True, "allowed": True})

        session = ScriptedSession(self.clock, channel)
        with self.assertRaises(SystemExit):
            commands.run_cycles(agent, session, _run_args(limit=10, interval=2),
                                listen=lambda *a, **k: events, out=lambda line: None)
        self.assertEqual(self.store.lead(first["id"])["state"], "unconfirmed")
        self.assertEqual(self.store.lead(third["id"])["state"], "new", "must not open after failure")
        self.assertEqual([s for s in channel.sent if s["lead"] == second["id"]], [],
                         "must not send to second chat after unconfirmed first")

    def test_error_opening_skips_to_next_and_never_pauses_prospecting(self):
        _, clinics = self._import_clinics()
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock,
                                    fail_open_once={clinics[0]["id"]: RuntimeError(
                                        "WhatsApp chat did not open for the number")})
        agent = SalesAgent(self.rules, self.store, channel, None, live=True,
                           clock=self.clock, sleep=self._sleep, rng=random.Random(2),
                           notify=self.notes.append, log=self.logs.append, paced_openings=True)
        session = ScriptedSession(self.clock, channel)
        commands.run_cycles(agent, session, _run_args(limit=10, interval=2),
                            listen=lambda *a, **k: [], out=lambda line: None,
                            stopped=lambda: len(channel.opening_windows) >= 2)
        self.assertEqual(self.store.lead(clinics[0]["id"])["state"], "new")
        self.assertIn("did not open", self.store.lead(clinics[0]["id"])["open_error"])
        opened = [window[0] for window in channel.opening_windows]
        self.assertEqual(opened, [clinics[1]["id"], clinics[2]["id"]],
                         "the failed chat is skipped, the next ones open on schedule")

    def test_blocking_prospect_uses_five_minute_opening_interval(self):
        _, clinics = self._import_clinics()
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        pauses: list[float] = []
        agent = SalesAgent(self.rules, self.store, channel, None, live=True,
                           clock=self.clock, sleep=pauses.append, rng=random.Random(7),
                           notify=self.notes.append, log=self.logs.append, paced_openings=False)
        results = agent.prospect(3)
        self.assertEqual([item["state"] for item in results], ["opened", "opened", "opened"])
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(300.0 <= p <= 330.0 for p in pauses), pauses)

    def test_long_clinic_auto_reply_and_doctor_gatekeeper_patterns(self):
        long_auto = ("Olá! Seja bem-vindo à Clínica Odontológica! Agradecemos o seu contato. "
                     "Nosso horário de atendimento é de segunda a sexta, das 08h às 18h. "
                     "Em breve nossa equipe responderá você.")
        self.assertGreater(len(long_auto), 120)
        self.assertEqual(classifier.classify(self.rules, long_auto), "auto_reply")
        self.assertTrue(classifier.decisive("auto_reply", long_auto))
        for msg in ("Aqui é da recepção, a Dra. está em atendimento",
                    "Vou passar pra doutora ver",
                    "Vou falar com o Dr. quando ele sair da consulta"):
            self.assertEqual(classifier.classify(self.rules, msg), "gatekeeper", msg)

    def test_pacing_between_openings_stays_inside_five_minutes(self):
        pacing = SalesPacing.from_rules(self.rules)
        rng = random.Random(11)
        self.assertEqual((pacing.between_openings_min, pacing.between_openings_max),
                         (300.0, 330.0))
        for _ in range(50):
            value = pacing.between_openings(rng)
            self.assertTrue(300.0 <= value <= 330.0, value)


class TypingStateTests(unittest.TestCase):
    rules = load()
    rules.limits["auto_conversation"] = True  # automated mode under test

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = SalesStore(self.root / "whatsapp")
        self.clock = Clock(MONDAY)
        self.notes: list[dict] = []
        self.logs: list[str] = []
        csv_path = write_csv(self.root / "clinic.csv", CLINIC_ROWS[:1])
        self.store.import_csv(csv_path, self.clock(), source="google-maps-manual")
        self.lead = next(iter(self.store.leads().values()))
        self.store.update_lead(self.lead["id"], state="opened",
                               opened_at=(self.clock() - timedelta(minutes=10)).isoformat(),
                               chat="Vitalli Odontologia")
        listener.allow_contact(self.store.contact_rules_path, "+" + self.lead["phone"])

    def tearDown(self):
        self.directory.cleanup()

    def _sleep(self, seconds: float) -> None:
        self.clock.now += timedelta(seconds=float(seconds))

    def _ev(self, text: str, eid: str) -> dict:
        return {"id": eid, "at": self.clock().isoformat(timespec="seconds"),
                "message_at": self.clock().strftime("%H:%M"),
                "chat": "Vitalli Odontologia", "text": text, "unread": True, "allowed": True}

    def _typing_ev(self) -> dict:
        return {"id": "typing:Vitalli Odontologia", "kind": "typing", "typing": True,
                "at": self.clock().isoformat(timespec="seconds"),
                "message_at": self.clock().strftime("%H:%M"),
                "chat": "Vitalli Odontologia", "text": "", "unread": True, "allowed": True}

    def test_chat_list_typing_waits_then_answers_all_messages_together(self):
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        channel.is_typing = lambda: False
        llm = ScriptedLLM()
        agent = SalesAgent(self.rules, self.store, channel, llm, live=True,
                           clock=self.clock, sleep=self._sleep, notify=self.notes.append,
                           log=self.logs.append)
        # Contact sends "Bom dia!" and immediately starts typing the real question.
        channel.push_incoming(self.lead["id"], ["Bom dia!"])
        summary1 = agent.cycle([self._ev("Bom dia!", "e1"), self._typing_ev()])
        self.assertEqual(summary1["typing"], [self.lead["id"]])
        self.assertEqual(summary1["replies"][0]["state"], "typing")
        self.assertEqual(channel.sent, [], "must not send while contact is typing")
        self.assertEqual(llm.calls, [], "must not call model while waiting on typing")
        self.assertTrue(self.store.lead(self.lead["id"]).get("typing"))

        # Still typing 4 seconds later -> keeps waiting, never records "digitando..." in history.
        self.clock.now += timedelta(seconds=4)
        summary2 = agent.cycle([self._typing_ev()])
        self.assertEqual(summary2["replies"][0]["state"], "typing")
        self.assertEqual(channel.sent, [])
        self.assertFalse(any("digitando" in entry.get("text", "").lower()
                             for entry in self.store.history(self.lead["id"])))

        # Contact finishes typing and sends the full question -> bot answers both in one turn.
        self.clock.now += timedelta(seconds=6)
        channel.push_incoming(self.lead["id"], ["Quanto custa um site?"])
        summary3 = agent.cycle([self._ev("Quanto custa um site?", "e2")])
        self.assertEqual(summary3["typing"], [])
        self.assertEqual(summary3["replies"][0]["intent"], "price")
        self.assertFalse(self.store.lead(self.lead["id"]).get("typing"))
        self.assertTrue(any("R$ 500" in item["text"] for item in channel.sent))

    def test_header_typing_during_llm_aborts_send_until_contact_finishes(self):
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        header_typing = {"active": False}
        channel.is_typing = lambda: header_typing["active"]

        class SlowLLM(ScriptedLLM):
            def complete(self, messages, session_id, quick=False, long=False):
                # Contact starts typing their second message while the model is thinking!
                header_typing["active"] = True
                return super().complete(messages, session_id, quick=quick, long=long)

        agent = SalesAgent(self.rules, self.store, channel, SlowLLM(), live=True,
                           clock=self.clock, sleep=self._sleep, notify=self.notes.append,
                           log=self.logs.append)
        channel.push_incoming(self.lead["id"], ["Bom dia!"])
        summary1 = agent.cycle([self._ev("Bom dia!", "e1")])
        self.assertEqual(summary1["replies"][0]["state"], "typing")
        self.assertEqual(channel.sent, [], "pre-send typing check must cancel send")
        self.assertFalse(self.store.journal_path.exists(), "no journal key written when deferred")

        # Contact finishes typing and sends refusal -> bot handles refusal cleanly, never sent greeting!
        self.clock.now += timedelta(seconds=5)
        header_typing["active"] = False
        channel.push_incoming(self.lead["id"], ["No momento não temos interesse"])
        summary2 = agent.cycle([self._ev("No momento não temos interesse", "e2")])
        self.assertEqual(summary2["replies"][0]["intent"], "refusal")
        self.assertEqual(self.store.lead(self.lead["id"])["state"], "needs-owner")
        self.assertEqual([item["text"] for item in channel.sent],
                         list(self.rules.raw["referral_ask"]["messages"]))

    def test_contact_stops_typing_without_sending_second_message_still_gets_answered(self):
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        header_typing = {"active": True}
        channel.is_typing = lambda: header_typing["active"]
        agent = SalesAgent(self.rules, self.store, channel, ScriptedLLM(), live=True,
                           clock=self.clock, sleep=self._sleep, notify=self.notes.append,
                           log=self.logs.append)
        channel.push_incoming(self.lead["id"], ["Quanto custa um site?"])
        summary1 = agent.cycle([self._ev("Quanto custa um site?", "e1")])
        self.assertEqual(summary1["replies"][0]["state"], "typing")
        self.assertEqual(channel.sent, [])

        # Contact clears draft without sending anything else -> answered on next cycle.
        self.clock.now += timedelta(seconds=4)
        header_typing["active"] = False
        summary2 = agent.cycle([])
        self.assertEqual(summary2["typing"], [])
        self.assertEqual(summary2["replies"][0]["intent"], "price")
        self.assertTrue(channel.sent)

    def test_stuck_typing_indicator_respects_max_typing_wait_cap(self):
        channel = SimulatedWhatsApp(self.store.journal_path, self.clock)
        channel.is_typing = lambda: True
        agent = SalesAgent(self.rules, self.store, channel, ScriptedLLM(), live=True,
                           clock=self.clock, sleep=self._sleep, notify=self.notes.append,
                           log=self.logs.append)
        channel.push_incoming(self.lead["id"], ["Quanto custa um site?"])
        summary1 = agent.cycle([self._ev("Quanto custa um site?", "e1"), self._typing_ev()])
        self.assertEqual(summary1["replies"][0]["state"], "typing")
        self.assertEqual(channel.sent, [])

        # After max_typing_wait_seconds (60s), bot stops waiting so a stuck DOM never freezes chat.
        self.clock.now += timedelta(seconds=61)
        summary2 = agent.cycle([self._typing_ev()])
        self.assertEqual(summary2["replies"][0]["intent"], "price")
        self.assertTrue(channel.sent)


if __name__ == "__main__":
    unittest.main()
