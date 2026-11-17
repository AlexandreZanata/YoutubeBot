"""Snapshot for the desktop Central: interventions, every state and recent messages.

Written to `.local/commercial/whatsapp/sales/central.json` after each agent cycle and after
owner commands, so the desktop manager reads one small file instead of the whole state.
"""

from __future__ import annotations

from datetime import datetime

from .context import effective
from .notify import format_phone, wa_link
from .store import SalesStore, _write_json

# (state, label, group, needs the owner); the order is the order shown in the Central.
STATES = (
    ("won", "Venda fechada (site)", "Com você", True),
    ("buying", "Quer comprar (sistema)", "Com você", True),
    ("needs-owner", "Precisa de você", "Com você", True),
    ("quote-requested", "Orçamento a fazer", "Com você", True),
    ("unconfirmed", "Envio não confirmado", "Com você", True),
    ("owner", "Você está atendendo", "Com você", True),
    ("lost", "Desistiu", "Com você", True),
    ("qualifying", "Coletando dados", "Em conversa", False),
    ("engaged", "Em conversa", "Em conversa", False),
    ("gatekeeper", "Falando com funcionário", "Em conversa", False),
    ("new", "Novo", "Prospecção", False),
    ("opening", "Abrindo conversa", "Prospecção", False),
    ("opened", "Abordado", "Prospecção", False),
    ("followed-up", "Follow-up enviado", "Prospecção", False),
    ("referred", "Indicou o responsável", "Encerrados", False),
    ("closed", "Encerrado", "Encerrados", False),
    ("no-response", "Sem resposta", "Encerrados", False),
    ("do-not-contact", "Não contatar", "Encerrados", False),
    ("invalid-number", "Número sem WhatsApp", "Encerrados", False),
)
LABELS = {state: label for state, label, _, _ in STATES}
OWNER = {state for state, _, _, owner in STATES if owner}
RANK = {"hot": 0, "alert": 1, "needed": 2}


def snapshot(store: SalesStore, now: datetime, messages: int = 100) -> dict:
    leads = store.ensure_labels()
    handoffs: dict[str, dict] = {}
    for entry in store.handoffs():
        handoffs[entry.get("lead", "")] = entry
    counts = {state: 0 for state, *_ in STATES}
    interventions, recent, rows = [], [], []
    for lead in leads.values():
        state = lead.get("state", "new")
        counts[state] = counts.get(state, 0) + 1
        contact = {"lead": lead["id"], "label": lead.get("label", ""), "name": lead["name"],
                   "contact_name": lead.get("contact_name", ""),
                   "phone": format_phone(lead["phone"]), "wa_link": wa_link(lead["phone"])}
        rows.append({**contact, "state": state, "state_label": LABELS.get(state, state),
                     "category": lead.get("category", ""), "city": lead.get("city", ""),
                     "last_in_at": lead.get("last_in_at"), "last_out_at": lead.get("last_out_at"),
                     "ficha": lead.get("ficha")})
        if state in OWNER:
            last = handoffs.get(lead["id"], {})
            interventions.append({
                **contact, "state": state, "state_label": LABELS[state],
                "priority": last.get("priority", "needed"),
                "priority_label": last.get("priority_label") or last.get("label"),
                "reason": last.get("reason") or lead.get("handoff_reason") or LABELS[state],
                "last_message": last.get("last_message", ""), "at": last.get("at"),
                "ficha": lead.get("ficha") or last.get("ficha") or ""})
        for order, entry in enumerate(effective(store.history(lead["id"]))[-20:]):
            if entry.get("dir") in ("in", "out") and entry.get("state", "sent") == "sent":
                recent.append({"at": entry.get("at", ""), "order": order, "lead": lead["id"],
                               "label": lead.get("label", ""), "name": lead["name"],
                               "dir": entry["dir"], "text": entry.get("text", ""),
                               "media": entry.get("media", ""),
                               "needs_owner": state in OWNER})
    interventions.sort(key=lambda item: (RANK.get(item["priority"], 3), item.get("at") or ""))
    recent.sort(key=lambda item: (item["at"], item["order"]), reverse=True)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "states": [{"state": state, "label": label, "group": group, "owner": owner,
                    "count": counts.get(state, 0)} for state, label, group, owner in STATES],
        "interventions": interventions,
        "messages": recent[:messages],
        "leads": sorted(rows, key=lambda item: item["label"]),
    }


def write(store: SalesStore, now: datetime) -> dict:
    data = snapshot(store, now)
    _write_json(store.central_path, data)
    return data

