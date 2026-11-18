"""Snapshot for the desktop Central: interventions, every state and recent messages.

Written to `.local/commercial/whatsapp/sales/central.json` after each agent cycle and after
owner commands, so the desktop manager reads one small file instead of the whole state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import dossier
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
MEDIA_KINDS = ("image", "audio", "video", "document")


def ficha_entry(folder: Path, lead: dict, contact: dict) -> dict | None:
    """The client ficha as the Central shows it: filled fields, open items and media files."""
    try:
        record = json.loads((folder / "ficha.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    brief = record.get("ficha") or {}
    sections = []
    for title, rows in dossier.sections(lead, brief):
        items = [{"label": label, "value": dossier._value(value)} for label, value in rows
                 if value not in (None, "", [])]
        if items:
            sections.append({"title": title, "items": items})
    media, root = [], folder.resolve()
    for item in record.get("arquivos") or []:
        file = (folder / str(item.get("arquivo") or "")).resolve()
        if root not in file.parents or not file.is_file():
            continue
        kind = item.get("tipo") if item.get("tipo") in MEDIA_KINDS else "document"
        media.append({"kind": kind, "path": str(file), "name": file.name,
                      "caption": item.get("legenda") or "", "at": item.get("em") or ""})
    system = record.get("tipo") == "sistema" or brief.get("kind") == "sistema"
    state = lead.get("state") or ""
    return {"lead": lead["id"], "label": contact["label"], "name": contact["name"],
            "state": state, "state_label": LABELS.get(state, state),
            "kind": "sistema" if system else "site", "status": record.get("status") or "",
            "updated_at": record.get("gerada_em") or "", "resumo": brief.get("resumo") or "",
            "sections": sections, "pendencias": [str(item) for item in brief.get("faltando") or []],
            "duvidas": [str(item) for item in brief.get("duvidas_do_cliente") or []],
            "media": media, "ficha_md": str(folder / "ficha.md"), "folder": str(folder),
            "phone": contact["phone"], "wa_link": contact["wa_link"]}


def snapshot(store: SalesStore, now: datetime, messages: int = 100) -> dict:
    leads = store.ensure_labels()
    handoffs: dict[str, dict] = {}
    for entry in store.handoffs():
        handoffs[entry.get("lead", "")] = entry
    counts = {state: 0 for state, *_ in STATES}
    interventions, recent, rows, fichas = [], [], [], []
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
    # Every client folder, also one from an earlier test cycle whose lead link was reset.
    for folder in sorted((store.root / "clientes").glob("*/ficha.json")):
        try:
            record = json.loads(folder.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        saved = record.get("lead") or {}
        lead = leads.get(saved.get("id") or "") or {**saved, "state": "", "phone": ""}
        if not lead.get("id"):
            continue
        contact = {"label": lead.get("label", ""), "name": lead.get("name") or "",
                   "phone": format_phone(lead["phone"]) if lead.get("phone") else
                   record.get("whatsapp", ""),
                   "wa_link": wa_link(lead["phone"]) if lead.get("phone") else ""}
        entry = ficha_entry(folder.parent, lead, contact)
        if entry:
            fichas.append(entry)
    interventions.sort(key=lambda item: (RANK.get(item["priority"], 3), item.get("at") or ""))
    recent.sort(key=lambda item: (item["at"], item["order"]), reverse=True)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "states": [{"state": state, "label": label, "group": group, "owner": owner,
                    "count": counts.get(state, 0)} for state, label, group, owner in STATES],
        "interventions": interventions,
        "messages": recent[:messages],
        "leads": sorted(rows, key=lambda item: item["label"]),
        "fichas": sorted(fichas, key=lambda item: item["updated_at"], reverse=True),
    }


def write(store: SalesStore, now: datetime) -> dict:
    data = snapshot(store, now)
    _write_json(store.central_path, data)
    return data

