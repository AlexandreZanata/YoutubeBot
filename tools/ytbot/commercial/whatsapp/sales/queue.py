"""The opening queue: Maps leads in the owner's CSV order, one number at a time.

There is no second store. The queue is a view of `leads.json`: a lead's place is its
`queue_position` (set by `import`, in CSV row order), its status comes from the lead state,
and sending goes through `SalesAgent.prospect` -> `open_lead` -> `sender.send_sequence`, the
same path, journal and repeat fences as `run --prospect` (owner, 2026-11-18).
"""

from __future__ import annotations

from .store import QUEUE_SOURCES, SalesStore, mask

STATUSES = ("pending", "sending", "sent", "unconfirmed", "skipped", "error")
SENDABLE = ("pending", "error")


def in_queue(lead: dict) -> bool:
    """New Maps leads only: never a referral (it has its own opening and limit)."""
    return lead.get("source") in QUEUE_SOURCES and not lead.get("referral")


def order_key(lead: dict) -> tuple:
    """The queue position alone: import order, or the order an explicit reorder set.

    `queue_position` is unique and monotonic across imports, so it already encodes the
    batch order; keeping the batch date first would make `reorder` impossible across days.
    """
    return (int(lead.get("queue_position") or 0), lead.get("imported_at") or "",
            lead.get("id", ""))


def status(lead: dict, do_not_contact: bool = False) -> tuple[str, str]:
    """(status, reason) of one lead in the queue, from its state; never stored separately."""
    state = lead.get("state", "new")
    if state == "new" and not lead.get("opened_at"):
        if do_not_contact:
            return "skipped", "na lista de não contatar"
        if lead.get("open_error"):
            return "error", f"a última tentativa falhou antes de enviar: {lead['open_error']}"
        return "pending", ""
    if state == "opening":
        return "sending", "a abertura começou e não foi concluída"
    if state == "unconfirmed":
        return "unconfirmed", lead.get("handoff_reason") or "envio não confirmado"
    if state == "do-not-contact":
        return "skipped", "não contatar"
    if state == "invalid-number":
        return "skipped", "número sem WhatsApp"
    if lead.get("opened_at"):
        return "sent", ""
    return "skipped", "escreveu antes da abertura; o bot já está respondendo"


def items(store: SalesStore) -> list[dict]:
    """The queue in sending order, phones masked."""
    leads = sorted((lead for lead in store.leads().values() if in_queue(lead)), key=order_key)
    rows = []
    for position, lead in enumerate(leads, start=1):
        state, reason = status(lead, store.is_dnc(lead["phone"]))
        rows.append({"position": position, "lead": lead["id"], "label": lead.get("label", ""),
                     "name": lead.get("name", ""), "phone": mask(lead["phone"]),
                     "status": state, "reason": reason, "opened_at": lead.get("opened_at")})
    return rows


def reorder(store: SalesStore, phones: list[str]) -> dict:
    """Put the given numbers first, in CSV order; everyone else keeps their order after.

    The owner's decision (2026-11-23): a new batch can jump ahead of an older one. Only
    `queue_position` changes; states, history and fences stay untouched.
    """
    from .store import canonical_phone

    wanted = [canonical_phone(phone) for phone in phones]
    wanted = [phone for phone in wanted if phone]
    leads = [lead for lead in store.leads().values() if in_queue(lead)]
    by_phone = {canonical_phone(lead.get("phone", "") or ""): lead for lead in leads}
    ordered, seen = [], set()
    for phone in wanted:
        lead = by_phone.get(phone)
        if lead is not None and lead["id"] not in seen:
            ordered.append(lead)
            seen.add(lead["id"])
    rest = [lead for lead in sorted(leads, key=order_key) if lead["id"] not in seen]
    moved = 0
    for position, lead in enumerate(ordered + rest, start=1):
        if int(lead.get("queue_position") or 0) != position:
            store.update_lead(lead["id"], queue_position=position)
            moved += 1
    return {"first": len(ordered), "total": len(ordered) + len(rest), "moved": moved}
