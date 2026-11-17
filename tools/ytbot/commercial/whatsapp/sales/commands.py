"""Typed CLI for the WhatsApp sales agent: `commercial sales <action> --network whatsapp`."""

from __future__ import annotations

import json
from datetime import datetime
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import listener as whatsapp_listener
from . import llm as sales_llm
from . import rehearsal
from .agent import (SalesAgent, WhatsAppChannel, owner_block, owner_reset, owner_resolve,
                    split_pending)
from .decide import decide
from .pacing import SalesPacing
from .rules import RULES_PATH, RulesError, load
from .store import AUTOMATED_STATES, SalesStore, mask, stamp

OWNER_STATES = ("needs-owner", "quote-requested", "owner", "unconfirmed")


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _context(args, store_factory):
    try:
        rules = load(Path(args.rules) if getattr(args, "rules", None) else None)
    except RulesError as error:
        raise SystemExit(f"[sales] invalid rules: {error}")
    store = SalesStore(store_factory().network("whatsapp"))
    return rules, store, datetime.now(ZoneInfo(rules.raw["timezone"]))


def _model(rules, store, enabled: bool):
    if not enabled:
        return None
    key = sales_llm.load_api_key(rules.llm["api_key_env"], store.key_path)
    if not key:
        print(f"[sales] {rules.llm['api_key_env']} not found in the environment or "
              f"{store.key_path.name}; fixed texts only, unknown cases go to the owner",
              flush=True)
        return None
    return sales_llm.OpenCodeGo(rules.llm, key)


def _public(lead: dict, show_phone: bool = False) -> dict:
    view = {key: lead.get(key) for key in ("id", "name", "city", "category", "state",
                                           "opened_at", "followups", "last_in_at",
                                           "last_out_at", "handoff_reason")}
    view["phone"] = lead["phone"] if show_phone else mask(lead["phone"])
    return view


def command_import(args, store_factory) -> None:
    rules, store, now = _context(args, store_factory)
    path = Path(args.csv)
    if not path.is_file():
        raise SystemExit(f"[sales] CSV not found: {path}")
    try:
        report = store.import_csv(path, now)
    except ValueError as error:
        raise SystemExit(f"[sales] {error}")
    report["daily_openings"] = rules.limits["daily_openings"]
    _print(report)


def command_leads(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    leads = [lead for lead in store.leads().values()
             if not args.state or lead["state"] == args.state]
    _print([_public(lead, args.show_phone) for lead in leads])


def command_history(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    lead = store.lead(args.lead)
    if lead is None:
        raise SystemExit(f"[sales] unknown lead {args.lead}")
    _print({"lead": _public(lead), "history": store.history(lead["id"])})


def command_handoffs(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    waiting = [_public(lead) for lead in store.leads().values() if lead["state"] in OWNER_STATES]
    _print({"waiting": waiting, "recent": store.handoffs()[-args.limit:]})


def command_block(args, store_factory) -> None:
    _, store, now = _context(args, store_factory)
    try:
        _print(_public(owner_block(store, args.lead, now)))
    except KeyError:
        raise SystemExit(f"[sales] unknown lead {args.lead}")


def command_resolve(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    try:
        _print(_public(owner_resolve(store, args.lead, args.state)))
    except KeyError:
        raise SystemExit(f"[sales] unknown lead {args.lead}")
    except ValueError as error:
        raise SystemExit(f"[sales] {error}")


def command_ficha(args, store_factory) -> None:
    """Rebuild a client's folder (ficha.md, ficha.json, conversa.md) from the memory."""
    rules, store, _ = _context(args, store_factory)
    lead = store.lead(args.lead)
    if lead is None:
        raise SystemExit(f"[sales] unknown lead {args.lead}")
    agent = SalesAgent(rules, store, None, _model(rules, store, not args.no_llm))
    status = {"qualifying": "coletando dados"}.get(lead["state"], "orçamento com o dono")
    ficha = agent._write_dossier(lead, None, status)
    store.update_lead(lead["id"], ficha=ficha)
    _print({"lead": lead["id"], "ficha": ficha})


def command_reset(args, store_factory) -> None:
    """Owner test only: archive the conversation and allow the opening again."""
    _, store, _ = _context(args, store_factory)
    if not args.yes:
        raise SystemExit("[sales] reset archives the conversation and allows a new opening; "
                         "confirm with --yes (test numbers only)")
    try:
        _print(_public(owner_reset(store, args.lead)))
    except KeyError:
        raise SystemExit(f"[sales] unknown lead {args.lead}")
    except ValueError as error:
        raise SystemExit(f"[sales] {error}")


def command_check(args, store_factory) -> None:
    rules, store, now = _context(args, store_factory)
    leads = store.leads().values()
    key = sales_llm.load_api_key(rules.llm["api_key_env"], store.key_path)
    report = {
        "rules_version": rules.raw["version"], "intents": len(rules.intents),
        "model": rules.llm["model"], "model_key_present": bool(key),
        "daily_openings": rules.limits["daily_openings"],
        "opening_window_open": rules.in_window(now, "opening"),
        "reply_window_open": rules.in_window(now, "reply"),
        "leads": len(leads), "automated": sum(1 for lead in leads
                                             if lead["state"] in AUTOMATED_STATES),
        "do_not_contact": len(store.dnc()),
    }
    if args.ping:
        if not key:
            raise SystemExit("[sales] no OpenCode Go key to ping with")
        client = sales_llm.OpenCodeGo(rules.llm, key)
        try:
            reply = client.complete([{"role": "system", "content": "Responda somente JSON."},
                                     {"role": "user", "content": 'Responda {"pong": true}'}],
                                    session_id=f"zaflas-sales-ping-{int(now.timestamp())}")
        except sales_llm.LlmError as error:
            raise SystemExit(f"[sales] ping failed: {error}")
        report["ping"] = {"model": reply.model, "content": reply.content[:80],
                          "cost_usd": reply.cost_usd, "duration_ms": reply.duration_ms}
    _print(report)


def command_simulate(args, store_factory) -> None:
    """Show the decision for a hypothetical message; nothing is sent or stored."""
    rules, store, now = _context(args, store_factory)
    if args.lead:
        lead = store.lead(args.lead)
        if lead is None:
            raise SystemExit(f"[sales] unknown lead {args.lead}")
        history, _ = split_pending(store.history(lead["id"]))
    else:
        lead = {"id": "Lsimulacao", "name": args.name, "category": "", "city": "",
                "state": args.state, "phone": ""}
        history = [{"at": stamp(now), "dir": "out", "text": text, "state": "sent"}
                   for text in rules.opening_messages(now)]
    decision = decide(rules, lead, history, args.text, _model(rules, store, not args.no_llm),
                      now)
    pacing = SalesPacing.from_rules(rules)
    _print({**decision.record(),
            "delays_seconds": [round(value, 1) for value in
                               pacing.plan(decision.messages, args.text)]})


def command_rehearse(args, store_factory) -> None:
    """Run scripted customer conversations offline; nothing is sent or stored."""
    rules, store, _ = _context(args, store_factory)
    try:
        scenarios = rehearsal.load_scenarios(Path(args.scenarios) if args.scenarios else None)
    except (OSError, ValueError) as error:
        raise SystemExit(f"[sales] {error}")
    if args.only:
        scenarios = {name: turns for name, turns in scenarios.items()
                     if args.only.casefold() in name.casefold()}
    transcripts = rehearsal.rehearse(rules, scenarios, _model(rules, store, not args.no_llm))
    if args.json:
        _print(transcripts)
    else:
        print(rehearsal.render(transcripts))


def reload_if_changed(agent, path: Path, seen: float) -> float:
    """Reload the rules when the file changed; keep the current ones if the edit is invalid."""
    try:
        changed = path.stat().st_mtime
    except OSError:
        return seen
    if changed == seen:
        return seen
    try:
        agent.use_rules(load(path))
        print(f"[sales] rules reloaded from {path.name}", flush=True)
    except RulesError as error:
        print(f"[sales] edited rules are invalid, keeping the previous ones: {error}",
              flush=True)
    return changed


def command_run(args, store_factory, page_factory) -> None:
    rules, store, _ = _context(args, store_factory)
    model = _model(rules, store, not args.no_llm)
    if not args.live:
        print("[sales] dry run: decisions are printed, nothing is sent (use --live to send)",
              flush=True)
    if not store.acquire():
        raise SystemExit("[sales] another sales run is active; one conversation at a time")
    try:
        _, _, playwright, client, page = page_factory(args)
    except RuntimeError as error:
        store.release()
        raise SystemExit(f"[sales] {error}")
    try:
        channel = WhatsAppChannel(page, SalesPacing.from_rules(rules), store.journal_path)
        agent = SalesAgent(rules, store, channel if args.live else None, model, live=args.live)
        rules_path = Path(args.rules) if args.rules else RULES_PATH
        rules_seen = rules_path.stat().st_mtime
        cycles = 0
        while True:
            rules_seen = reload_if_changed(agent, rules_path, rules_seen)
            events = whatsapp_listener.listen(page, store.base, once=True, limit=args.max_chats)
            summary = agent.cycle(events, prospect=args.prospect, limit=args.limit)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            cycles += 1
            outcomes = [item.get("state") for group in ("replies", "followups", "openings")
                        for item in summary[group]]
            if any(state in ("unconfirmed", "error") for state in outcomes):
                raise SystemExit("[sales] a send was not confirmed; stopping. Check the chat, "
                                 "then `commercial sales resolve`.")
            if args.once or (args.max_cycles and cycles >= args.max_cycles):
                break
            page.wait_for_timeout(args.interval * 1000)
    finally:
        page.close()
        client.close()
        playwright.stop()
        store.release()


def add_parser(actions, store_factory, page_factory) -> None:
    sales = actions.add_parser("sales", help="Zaflas WhatsApp sales agent (dry-run by default)")
    sub = sales.add_subparsers(dest="sales_action", required=True)

    def action(name: str, help_text: str, handler):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--network", choices=("whatsapp",), required=True)
        parser.add_argument("--rules", default=None,
                            help="alternative rules file (owner review and tests)")
        parser.set_defaults(func=handler)
        return parser

    importer = action("import", "import the owner-reviewed Google Maps CSV",
                      partial(command_import, store_factory=store_factory))
    importer.add_argument("--csv", required=True)
    leads = action("leads", "list leads (phones masked)",
                   partial(command_leads, store_factory=store_factory))
    leads.add_argument("--state", default=None)
    leads.add_argument("--show-phone", action="store_true")
    history = action("history", "show a lead's conversation memory",
                     partial(command_history, store_factory=store_factory))
    history.add_argument("--lead", required=True)
    handoffs = action("handoffs", "conversations waiting for the owner",
                      partial(command_handoffs, store_factory=store_factory))
    handoffs.add_argument("--limit", type=int, default=20)
    block = action("block", "owner: never contact this lead again",
                   partial(command_block, store_factory=store_factory))
    block.add_argument("--lead", required=True)
    resolve = action("resolve", "owner: hand a conversation back after handling it",
                     partial(command_resolve, store_factory=store_factory))
    resolve.add_argument("--lead", required=True)
    resolve.add_argument("--state", choices=("engaged", "qualifying", "closed", "opened",
                                              "do-not-contact"), default="engaged")
    ficha = action("ficha", "rebuild a client's folder and brief from the conversation",
                   partial(command_ficha, store_factory=store_factory))
    ficha.add_argument("--lead", required=True)
    ficha.add_argument("--no-llm", action="store_true")
    reset = action("reset", "owner test only: archive a conversation and allow a new opening",
                   partial(command_reset, store_factory=store_factory))
    reset.add_argument("--lead", required=True)
    reset.add_argument("--yes", action="store_true")
    check = action("check", "validate the rules, key presence and counters",
                   partial(command_check, store_factory=store_factory))
    check.add_argument("--ping", action="store_true", help="one tiny paid model call")
    simulate = action("simulate", "show the reply for a hypothetical message (never sends)",
                      partial(command_simulate, store_factory=store_factory))
    simulate.add_argument("--text", required=True)
    simulate.add_argument("--lead", default=None)
    simulate.add_argument("--name", default="Empresa de teste")
    simulate.add_argument("--state", default="opened")
    simulate.add_argument("--no-llm", action="store_true")
    rehearse = action("rehearse", "replay customer scenarios offline (never sends)",
                      partial(command_rehearse, store_factory=store_factory))
    rehearse.add_argument("--scenarios", default=None, help="JSON {name: [messages]}")
    rehearse.add_argument("--only", default=None, help="scenarios whose name contains this")
    rehearse.add_argument("--json", action="store_true")
    rehearse.add_argument("--no-llm", action="store_true")
    run = action("run", "listen, answer, follow up and (with --prospect) open new leads",
                 partial(command_run, store_factory=store_factory, page_factory=page_factory))
    run.add_argument("--live", action="store_true", help="actually send")
    run.add_argument("--prospect", action="store_true",
                     help="also send openings to new leads (daily limit applies)")
    run.add_argument("--limit", type=int, default=None, help="max openings in this run")
    run.add_argument("--once", action="store_true")
    run.add_argument("--interval", type=int, default=30)
    run.add_argument("--max-cycles", type=int, default=0)
    run.add_argument("--max-chats", type=int, default=30)
    run.add_argument("--no-llm", action="store_true")
