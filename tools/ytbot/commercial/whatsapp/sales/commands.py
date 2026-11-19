"""Typed CLI for the WhatsApp sales agent: `commercial sales <action> --network whatsapp`."""

from __future__ import annotations

import csv
import json
import signal
from datetime import datetime
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import listener as whatsapp_listener
from . import central
from . import llm as sales_llm
from . import queue as sales_queue
from . import rehearsal
from .agent import (SalesAgent, WhatsAppChannel, _failed_outcome, is_closed_error, owner_block,
                    owner_reset, owner_resolve, split_pending)
from .decide import decide
from .pacing import SalesPacing
from .rules import RULES_PATH, RulesError, load
from .store import (AUTOMATED_STATES, SOURCES, SalesStore, canonical_phone, lead_id, mask,
                    reply_is_active, stamp)

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
    """The free-first model router, or None (fixed texts, unknown cases to the owner)."""
    if not enabled:
        return None
    key = sales_llm.load_api_key(rules.llm["api_key_env"], store.key_path)
    if not key:
        print(f"[sales] {rules.llm['api_key_env']} not found in the environment or "
              f"{store.key_path.name}; fixed texts only, unknown cases go to the owner",
              flush=True)
        return None
    return sales_llm.ModelRouter(rules.llm, key, cache_path=store.root / "models.json",
                                 log=lambda message: print(f"[sales] {message}", flush=True))


def _public(lead: dict, show_phone: bool = False) -> dict:
    view = {key: lead.get(key) for key in ("id", "label", "name", "city", "category", "state",
                                           "opened_at", "followups", "last_in_at",
                                           "last_out_at", "handoff_reason")}
    view["phone"] = lead["phone"] if show_phone else mask(lead["phone"])
    view["reply"] = "ativo" if reply_is_active(lead) else "pausado"
    return view


def command_import(args, store_factory) -> None:
    rules, store, now = _context(args, store_factory)
    path = Path(args.csv)
    if not path.is_file():
        raise SystemExit(f"[sales] CSV not found: {path}")
    try:
        report = store.import_csv(path, now, source=args.source)
    except ValueError as error:
        raise SystemExit(f"[sales] {error}")
    report["daily_openings"] = rules.limits["daily_openings"]
    central.write(store, now)
    _print(report)


def _set_reply_active(args, store_factory, active: bool) -> None:
    _, store, now = _context(args, store_factory)
    leads = store.ensure_labels()
    if args.lead and args.all:
        raise SystemExit("[sales] use --lead <id> or --all, not both")
    if args.lead:
        lead = leads.get(args.lead)
        if lead is None:
            raise SystemExit(f"[sales] unknown lead {args.lead}")
        selected = [lead]
    elif args.all:
        selected = list(leads.values())
    else:
        raise SystemExit("[sales] use --lead <id> or --all")
    for lead in selected:
        store.set_reply_active(lead["id"], active)
    central.write(store, now)
    _print({("activated" if active else "paused"): len(selected),
            "leads": [{"id": lead["id"], "label": lead.get("label", ""),
                       "name": lead.get("name", ""),
                       "reply": "ativo" if active else "pausado"} for lead in selected]})


def command_activate(args, store_factory) -> None:
    """Keep answering every selected imported number when it writes first."""
    _set_reply_active(args, store_factory, True)


def command_pause(args, store_factory) -> None:
    """Stop automatic replies for one number or all of them."""
    _set_reply_active(args, store_factory, False)


def command_leads(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    leads = [lead for lead in store.ensure_labels().values()
             if not args.state or lead["state"] == args.state]
    _print([_public(lead, args.show_phone) for lead in sorted(leads, key=lambda l: l["label"])])


def command_contacts(args, store_factory) -> None:
    """Write the vCard with every lead that may be contacted, to import into the phone."""
    _, store, now = _context(args, store_factory)
    path = store.export_contacts(None, now, "todos")
    count = path.read_text(encoding="utf-8").count("BEGIN:VCARD")
    _print({"contacts": count, "file": str(path)})


def command_central(args, store_factory) -> None:
    """Refresh central.json and print what needs the owner."""
    _, store, now = _context(args, store_factory)
    data = central.write(store, now)
    if args.json:
        _print(data)
        return
    print(f"central.json: {store.central_path}")
    print("Estados: " + ", ".join(f"{item['label']} {item['count']}" for item in data["states"]
                                  if item["count"]))
    for item in data["interventions"]:
        print(f"- {item.get('priority_label') or item['priority']} {item['label']} {item['name']} "
              f"{item['phone']} · {item['reason']} · {item['wa_link']}")


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
    central.write(store, now)


def command_resolve(args, store_factory) -> None:
    _, store, now = _context(args, store_factory)
    try:
        _print(_public(owner_resolve(store, args.lead, args.state)))
        central.write(store, now)
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
        central.write(store, datetime.now())
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
        "models": "free first, then " + " → ".join(rules.llm["fallback"]),
        "model_key_present": bool(key),
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
        router = _model(rules, store, True)
        try:
            reply = router.complete(sales_llm.PROBE,
                                    session_id=f"zaflas-sales-ping-{int(now.timestamp())}")
        except sales_llm.LlmError as error:
            raise SystemExit(f"[sales] ping failed: {error}")
        report["ping"] = {"model": reply.model, "content": reply.content[:80],
                          "cost_usd": reply.cost_usd, "duration_ms": reply.duration_ms}
    _print(report)


def command_models(args, store_factory) -> None:
    """The live catalog's free models, their privacy flags and health (parallel probe)."""
    rules, store, _ = _context(args, store_factory)
    router = _model(rules, store, True)
    if router is None:
        raise SystemExit("[sales] no OpenCode Go key")
    started = __import__("time").monotonic()
    router.refresh(force=True)
    _print({"free_models": router.free_models(), "fallback": rules.llm["fallback"],
            "probe_seconds": round(__import__("time").monotonic() - started, 1),
            "models": router.status()})


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
                   for text in rules.opening_messages(now, lead["name"])]
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


MAX_RECONNECTS = 3


def is_closed(error: BaseException) -> bool:
    """The browser page or the CDP connection went away (suspend/resume, Chrome restart)."""
    return is_closed_error(error)


def _allowed_leads(args) -> set[str] | None:
    """Optional lead allowlist for `run` (`--only-leads` and/or `--only-csv`)."""
    raw_ids = getattr(args, "only_leads", None)
    csv_path = getattr(args, "only_csv", None)
    if not raw_ids and not csv_path:
        return None
    allowed: set[str] = set()
    if raw_ids:
        for item in raw_ids.split(","):
            item = item.strip()
            if item:
                allowed.add(item)
    if csv_path:
        path = Path(csv_path)
        if not path.is_file():
            raise SystemExit(f"[sales] --only-csv file not found: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                phone = canonical_phone((row.get("phone") or "").strip())
                if phone:
                    allowed.add(lead_id(phone))
    if not allowed:
        raise SystemExit("[sales] --only-leads/--only-csv resolved to zero leads")
    return allowed


class Session:
    """The page the bot works on; reopened when the computer wakes up or Chrome restarts."""

    def __init__(self, args, page_factory, rules, store, log=print):
        self.args = args
        self.page_factory = page_factory
        self.rules = rules
        self.store = store
        self.log = log
        self.playwright = self.client = self.page = None
        self.channel = None
        self.open()

    def open(self) -> None:
        _, _, self.playwright, self.client, self.page = self.page_factory(self.args)
        self.channel = WhatsAppChannel(self.page, SalesPacing.from_rules(self.rules),
                                       self.store.journal_path)

    def close(self) -> None:
        for step in (lambda: self.page.close(), lambda: self.client.close(),
                     lambda: self.playwright.stop()):
            try:
                step()
            except Exception:
                pass

    def reopen(self, agent, error: BaseException) -> None:
        self.log(f"[sales] browser page closed ({type(error).__name__}); reconnecting")
        self.close()
        self.open()
        if agent.live:
            agent.channel = self.channel


def run_cycles(agent, session, args, listen=None, out=None, stopped=None) -> None:
    """Listen, answer, follow up and open leads until told to stop.

    A closed page outside a send (the computer slept, Chrome restarted) reconnects up to
    MAX_RECONNECTS times in a row. A send that failed is never retried: the journal fences it
    and the run stops.
    """
    listen = listen or whatsapp_listener.listen
    out = out or (lambda line: print(line, flush=True))
    stopped = stopped or (lambda: False)
    rules_path = Path(args.rules) if args.rules else RULES_PATH
    rules_seen = rules_path.stat().st_mtime
    cycles = failures = 0
    remaining = args.limit

    def recover(error: BaseException) -> None:
        nonlocal failures
        if not is_closed(error) or failures >= MAX_RECONNECTS:
            raise error
        failures += 1
        session.reopen(agent, error)

    while True:
        if stopped():
            out("[sales] stop requested; the run ends between two steps, never inside a send")
            return
        rules_seen = reload_if_changed(agent, rules_path, rules_seen)
        try:
            events = listen(session.page, agent.store.base, once=True, limit=args.max_chats)
            prospect_now = bool(args.prospect) and (remaining is None or remaining > 0)
            summary = agent.cycle(events, prospect=prospect_now, limit=remaining)
        except Exception as error:
            recover(error)
            continue
        failures = 0
        out(json.dumps(summary, ensure_ascii=False))
        cycles += 1
        if remaining is not None:
            remaining -= sum(1 for item in summary["openings"]
                             if item.get("state") in ("opened", "unconfirmed", "planned"))
        if any(_failed_outcome(item) for group in ("replies", "followups")
               for item in summary[group]):
            raise SystemExit("[sales] a send was not confirmed; stopping. Check the chat, "
                             "then `commercial sales resolve`.")
        unconfirmed_opening = any(
            item.get("state") == "unconfirmed"
            or (isinstance(item.get("referral_opening"), dict)
                and item["referral_opening"].get("state") == "unconfirmed")
            for item in summary["openings"])
        if unconfirmed_opening and args.once:
            raise SystemExit("[sales] an opening was not confirmed; stopping. Check the chat, "
                             "then `commercial sales resolve`.")
        if args.once or (args.max_cycles and cycles >= args.max_cycles):
            return
        try:
            # One second at a time, so a stop request ends the wait at once.
            for _ in range(max(1, int(args.interval))):
                if stopped():
                    break
                session.page.wait_for_timeout(1000)
        except Exception as error:
            recover(error)


def command_run(args, store_factory, page_factory) -> None:
    rules, store, _ = _context(args, store_factory)
    allowed = _allowed_leads(args)
    model = _model(rules, store, not args.no_llm)
    if not args.live:
        print("[sales] dry run: decisions are printed, nothing is sent (use --live to send)",
              flush=True)
    if not store.acquire():
        raise SystemExit("[sales] another sales run is active; one conversation at a time")
    try:
        session = Session(args, page_factory, rules, store)
    except RuntimeError as error:
        store.release()
        raise SystemExit(f"[sales] {error}")
    requested = []

    def stop(signum, frame):
        # Playwright swallows an exception raised here, and a default SIGTERM skips `finally`
        # (the tab stayed open). The first signal asks the loop to end after the current step;
        # a second one stops at once.
        if requested:
            raise SystemExit(f"[sales] stopped by signal {signum}")
        requested.append(signum)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        agent = SalesAgent(rules, store, session.channel if args.live else None, model,
                           live=args.live, paced_openings=not args.once,
                           allowed_leads=allowed)
        if args.live:
            for item in agent.reconcile_openings():
                print(json.dumps({"reconciled": item}, ensure_ascii=False), flush=True)
        run_cycles(agent, session, args, stopped=lambda: bool(requested))
    finally:
        signal.signal(signal.SIGTERM, previous)
        session.close()
        store.release()


def _queue_preview(rules, store, now, limit: int) -> list[dict]:
    rows = [row for row in sales_queue.items(store) if row["status"] in sales_queue.SENDABLE]
    return [{**row, "messages": rules.opening_messages(now, store.lead(row["lead"])["name"])}
            for row in rows[:limit]]


def command_queue(args, store_factory, page_factory) -> None:
    """The opening queue: `list` it, or `send` the next number(s), one conversation at a time.

    The queue is `leads.json` itself (Maps leads in CSV order). `send` is a dry run unless
    `--live`; live, it holds the same run lock as `run`, reconciles an interrupted opening
    first, and sends through the same `prospect` -> `open_lead` -> `send_sequence` path.
    """
    rules, store, now = _context(args, store_factory)
    quiet = SalesAgent(rules, store, None, None, live=False, log=lambda message: None)
    limit = max(1, int(args.limit))
    if args.operation == "list":
        rows = sales_queue.items(store)
        sendable = [row for row in rows if row["status"] in sales_queue.SENDABLE]
        _print({"items": rows, "next": sendable[0] if sendable else None,
                "blocked": quiet.opening_blocker(queue_only=True),
                "openings_today": quiet.openings_today("cold"),
                "daily_limit": int(rules.limits["daily_openings"])})
        return
    if args.live and args.dry_run:
        raise SystemExit("[sales] use --live or --dry-run, not both")
    if not args.live:
        _print({"dry_run": True, "blocked": quiet.opening_blocker(queue_only=True),
                "would_send": _queue_preview(rules, store, now, limit)})
        return
    if not store.acquire():
        raise SystemExit("[sales] another sales process is sending (run or queue send); "
                         "only one process sends at a time")
    session = None
    try:
        reconciled = SalesAgent(rules, store, None, None, live=False).reconcile_openings()
        if reconciled:
            central.write(store, now)
            _print({"sent": [], "stopped": "abertura interrompida encontrada: confira a "
                    "conversa antes de continuar; nada foi reenviado", "reconciled": reconciled})
            raise SystemExit(1)
        blocked = quiet.opening_blocker(queue_only=True)
        if blocked or not _queue_preview(rules, store, now, 1):
            _print({"sent": [], "blocked": blocked or "nenhum número pendente na fila"})
            return
        try:
            session = Session(args, page_factory, rules, store)
        except RuntimeError as error:
            raise SystemExit(f"[sales] {error}")
        agent = SalesAgent(rules, store, session.channel, None, live=True)
        results = agent.prospect(limit, queue_only=True)
        central.write(store, agent.now())
        _print({"sent": results, "queue": [row for row in sales_queue.items(store)
                                           if row["lead"] in {item["lead"] for item in results}]})
        if any(item["state"] == "unconfirmed" for item in results):
            raise SystemExit("[sales] the queue stopped: a send was not confirmed. "
                             "Check the chat; nothing is retried automatically.")
    finally:
        if session is not None:
            session.close()
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
    importer.add_argument("--source", choices=SOURCES, default="google-maps-reviewed",
                          help="where the reviewed rows came from (default: google-maps-reviewed)")
    activate = action("activate", "answer replies from every selected imported number",
                      partial(command_activate, store_factory=store_factory))
    activate.add_argument("--lead", default=None)
    activate.add_argument("--all", action="store_true")
    pause = action("pause", "pause automatic replies for one number or all",
                   partial(command_pause, store_factory=store_factory))
    pause.add_argument("--lead", default=None)
    pause.add_argument("--all", action="store_true")
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
    action("models", "list the free models, privacy flags and health (parallel probe)",
           partial(command_models, store_factory=store_factory))
    contacts = action("contacts", "write the vCard of every lead to save on the phone",
                      partial(command_contacts, store_factory=store_factory))
    contacts.set_defaults()
    central_parser = action("central", "refresh central.json and list what needs the owner",
                            partial(command_central, store_factory=store_factory))
    central_parser.add_argument("--json", action="store_true")
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
    queue = action("queue", "the opening queue: list it or send the next number(s)",
                   partial(command_queue, store_factory=store_factory,
                           page_factory=page_factory))
    queue.add_argument("operation", choices=("list", "send"))
    queue.add_argument("--live", action="store_true", help="actually send (send only)")
    queue.add_argument("--dry-run", action="store_true",
                       help="show what would be sent (the default for send)")
    queue.add_argument("--limit", type=int, default=1,
                       help="numbers to open in this run, one conversation at a time (default 1)")
    run = action("run", "listen, answer, follow up and (with --prospect) open new leads",
                 partial(command_run, store_factory=store_factory, page_factory=page_factory))
    run.add_argument("--live", action="store_true", help="actually send")
    run.add_argument("--prospect", action="store_true",
                     help="also send openings to new leads (daily limit applies)")
    run.add_argument("--limit", type=int, default=None, help="max openings in this run")
    run.add_argument("--once", action="store_true")
    run.add_argument("--interval", type=int, default=2,
                     help="seconds between two scans of the chat list (default 2)")
    run.add_argument("--max-cycles", type=int, default=0)
    run.add_argument("--max-chats", type=int, default=30)
    run.add_argument("--only-leads", default=None,
                     help="comma-separated lead ids; ignore all other contacts during this run")
    run.add_argument("--only-csv", default=None,
                     help="path to a reviewed CSV; only attend leads in this CSV (plus their referrals)")
    run.add_argument("--no-llm", action="store_true")
