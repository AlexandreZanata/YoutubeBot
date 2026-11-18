"""Typed CLI: `commercial lanchonete <action> --network whatsapp`."""

from __future__ import annotations

import json
import signal
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import listener as whatsapp_listener
from .. import sender
from ..sales import llm as sales_llm
from ..sales.commands import is_closed
from ..sales.pacing import SalesPacing
from ..sales.store import canonical_phone as whatsapp_phone, phone_key
from .agent import LanchoneteAgent, LanchoneteChannel, owner_block, owner_resolve
from .rules import RULES_PATH, RulesError, load
from .store import LanchoneteStore


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _context(args, store_factory):
    try:
        rules = load(Path(args.rules) if getattr(args, "rules", None) else None)
    except RulesError as error:
        raise SystemExit(f"[lanchonete] invalid rules: {error}")
    store = LanchoneteStore(store_factory().network("whatsapp"))
    return rules, store, datetime.now(ZoneInfo(rules.raw["timezone"]))


def _model(rules, store, enabled: bool):
    if not enabled:
        return None
    key = sales_llm.load_api_key(rules.llm["api_key_env"], store.key_path)
    if not key:
        print(f"[lanchonete] {rules.llm['api_key_env']} not found; the local parser and the "
              f"fixed replies handle every order", flush=True)
        return None
    return sales_llm.ModelRouter(rules.llm, key, cache_path=store.root / "models.json",
                                 log=lambda message: print(f"[lanchonete] {message}",
                                                           flush=True))


def _public(customer: dict) -> dict:
    return {"id": customer.get("id"), "label": customer.get("label"),
            "name": customer.get("name"), "chat": customer.get("chat"),
            "phone": customer.get("phone"), "state": customer.get("state"),
            "awaiting_field": customer.get("awaiting_field"),
            "order_number": customer.get("order_number"),
            "cart_lines": len(customer.get("cart") or []),
            "last_in_at": customer.get("last_in_at"),
            "last_out_at": customer.get("last_out_at"),
            "handoff_reason": customer.get("handoff_reason")}


def command_check(args, store_factory) -> None:
    rules, store, now = _context(args, store_factory)
    key = sales_llm.load_api_key(rules.llm["api_key_env"], store.key_path)
    report = {"rules_version": rules.raw["version"], "company": rules.company,
              "menu_items": len(rules.items), "extras": len(rules.extras),
              "payments": [payment.name for payment in rules.payments],
              "intents": len(rules.intents),
              "model_key_present": bool(key),
              "open_now": rules.in_window(now),
              "hours": f"{rules.raw['hours']['ordering_start']}–"
                       f"{rules.raw['hours']['ordering_end']}",
              "customers": len(store.leads()),
              "orders_today": len(store.orders_today(rules, now)),
              "orders_total": len(store.orders())}
    if args.ping:
        if not key:
            raise SystemExit("[lanchonete] no OpenCode Go key to ping with")
        router = _model(rules, store, True)
        try:
            reply = router.complete(sales_llm.PROBE,
                                    session_id=f"brasa-pao-ping-{int(now.timestamp())}")
        except sales_llm.LlmError as error:
            raise SystemExit(f"[lanchonete] ping failed: {error}")
        report["ping"] = {"model": reply.model, "content": reply.content[:80],
                          "cost_usd": reply.cost_usd, "duration_ms": reply.duration_ms}
    _print(report)


def command_menu(args, store_factory) -> None:
    rules, _, _ = _context(args, store_factory)
    if args.json:
        _print({"categories": rules.menu_category_names,
                "items": [{"id": item.id, "name": item.name, "category": item.category,
                           "price_cents": item.price_cents, "price": item.price,
                           "description": item.description} for item in rules.items],
                "extras": [{"id": extra.id, "name": extra.name,
                            "price_cents": extra.price_cents, "price": extra.price,
                            "categories": list(extra.categories)} for extra in rules.extras],
                "payments": [{"id": payment.id, "name": payment.name, "note": payment.note}
                             for payment in rules.payments]})
        return
    print("\n\n".join(rules.menu_messages()))
    print("\nAdicionais:")
    for extra in rules.extras:
        print(f"- {extra.name}: {extra.price} ({', '.join(extra.categories)})")
    print("\nPagamento:")
    print(rules.payment_text())


class RecordingChannel:
    """Offline stand-in for the browser: real journal, no network."""

    def __init__(self, journal_path: Path):
        self.journal_path = journal_path
        self.sent: list[str] = []

    def open(self, lead):
        return "ready"

    def chat_title(self):
        return ""

    def read_recent(self):
        return []

    def fetch_media(self, bubble):
        return []

    def send(self, lead, items, extra):
        captured = self

        def deliver(page, text, pacing, delay=None, link_wait=0.0, **kwargs):
            captured.sent.append(text)
            return "sent"

        return sender.send_sequence(None, lead["name"], items, sender.Pacing(),
                                    self.journal_path, extra=extra, deliver_fn=deliver)


def command_simulate(args, store_factory) -> None:
    """Play a customer conversation offline; nothing leaves the PC."""
    rules, _, now = _context(args, store_factory)
    if not args.text:
        raise SystemExit("[lanchonete] simulate needs at least one --text")
    try:
        hour, minute = args.at.split(":")
        now = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    except (AttributeError, ValueError):
        raise SystemExit("[lanchonete] --at must be HH:MM")
    with tempfile.TemporaryDirectory() as directory:
        store = LanchoneteStore(Path(directory) / "whatsapp")
        channel = RecordingChannel(store.journal_path)
        clock = lambda: now
        agent = LanchoneteAgent(rules, store, channel, None, live=True, clock=clock,
                                sleep=lambda seconds: None, notify=lambda entry: None,
                                log=lambda message: None)
        chat = args.chat
        steps = []
        for index, text in enumerate(args.text, start=1):
            channel.sent.clear()
            agent.ingest([{"id": f"sim-{index}", "chat": chat, "text": text}])
            result = agent.reply_pending()
            customer = store.find_lead(chat)
            steps.append({"in": text, "out": list(channel.sent),
                          "state": result[0].get("state") if result else "",
                          "order": result[0].get("order") if result else "",
                          "awaiting_field": customer.get("awaiting_field") if customer else ""})
        _print({"company": rules.company, "chat": chat, "steps": steps,
                "orders": store.orders()})


def command_allow(args, store_factory) -> None:
    """Owner: register a number and its WhatsApp title so the bot may answer it."""
    _, store, now = _context(args, store_factory)
    phone = whatsapp_phone(args.phone)
    if phone is None:
        raise SystemExit("[lanchonete] --phone is not a valid Brazilian number")
    chat = (args.chat or args.name).strip()
    found = next((customer for customer in store.leads().values()
                  if customer.get("phone") and phone_key(customer["phone"]) == phone_key(phone)),
                 None)
    if found is None:
        found = store.ensure_customer(chat, now)
    if store.is_blocked(found):
        raise SystemExit("[lanchonete] this number is on the do-not-contact list")
    updated = store.update_lead(found["id"], phone=phone, name=args.name.strip(),
                                chat=chat, contact_name=chat, source="owner-allow")
    _print(_public(updated))


def command_opening(args, store_factory, page_factory) -> None:
    """Owner: send the greeting and menu to a registered customer without replaying history."""
    rules, store, _ = _context(args, store_factory)
    customer = store.lead(args.customer)
    if customer is None:
        raise SystemExit(f"[lanchonete] unknown customer {args.customer}")
    if store.is_blocked(customer):
        raise SystemExit("[lanchonete] this customer is blocked")
    if not store.acquire():
        raise SystemExit("[lanchonete] another lanchonete run is active; stop it first")
    try:
        session = Session(args, page_factory, rules, store)
        try:
            agent = LanchoneteAgent(rules, store, session.channel, None, live=True)
            _print(agent.opening(customer))
        finally:
            session.close()
    finally:
        store.release()


def command_customers(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    customers = [customer for customer in store.leads().values()
                 if not args.state or customer.get("state") == args.state]
    _print([_public(customer) for customer in sorted(
        customers, key=lambda customer: customer.get("last_in_at") or "")])


def command_pedidos(args, store_factory) -> None:
    rules, store, now = _context(args, store_factory)
    orders = store.orders_today(rules, now) if args.today else store.orders()
    _print(orders[-args.limit:][::-1])


def command_ficha(args, store_factory) -> None:
    rules, store, now = _context(args, store_factory)
    wanted = args.order.strip().upper()
    found = next((entry for entry in store.orders()
                  if str(entry.get("number", "")).upper() == wanted), None)
    if found is None:
        found = next((entry for entry in store.orders_today(rules, now)
                      if str(entry.get("number", "")).upper().endswith("-" + wanted)), None)
    if found is None:
        raise SystemExit(f"[lanchonete] unknown order {args.order}")
    if args.path:
        print(found["ficha"])
        return
    print(Path(found["ficha"]).read_text(encoding="utf-8"))


def command_resolve(args, store_factory) -> None:
    _, store, _ = _context(args, store_factory)
    try:
        _print(_public(owner_resolve(store, args.customer, args.state)))
    except KeyError:
        raise SystemExit(f"[lanchonete] unknown customer {args.customer}")
    except ValueError as error:
        raise SystemExit(f"[lanchonete] {error}")


def command_recover(args, store_factory) -> None:
    """Clear a transient unconfirmed state without retrying the uncertain message."""
    rules, store, now = _context(args, store_factory)
    if not args.all and not args.customer:
        raise SystemExit("[lanchonete] recover needs --customer or --all")
    recovered = store.recover_unconfirmed(now)
    if args.customer:
        recovered = [lead for lead in recovered if lead["id"] == args.customer]
        if not recovered and store.lead(args.customer) is None:
            raise SystemExit(f"[lanchonete] unknown customer {args.customer}")
    _print([_public(lead) for lead in recovered])


def command_block(args, store_factory) -> None:
    _, store, now = _context(args, store_factory)
    try:
        _print(_public(owner_block(store, args.customer, now)))
    except KeyError:
        raise SystemExit(f"[lanchonete] unknown customer {args.customer}")


class Session:
    def __init__(self, args, page_factory, rules, store):
        self.args = args
        self.page_factory = page_factory
        self.rules = rules
        self.store = store
        self.playwright = self.client = self.page = None
        self.channel = None
        self.open()

    def open(self) -> None:
        _, _, self.playwright, self.client, self.page = self.page_factory(self.args)
        self.channel = LanchoneteChannel(self.page, SalesPacing.from_rules(self.rules),
                                         self.store.journal_path)

    def close(self) -> None:
        for step in (lambda: self.page.close(), lambda: self.client.close(),
                     lambda: self.playwright.stop()):
            try:
                step()
            except Exception:
                pass


def _reload(agent, path: Path, seen: float) -> float:
    try:
        changed = path.stat().st_mtime
    except OSError:
        return seen
    if changed == seen:
        return seen
    try:
        agent.use_rules(load(path))
        print(f"[lanchonete] rules reloaded from {path.name}", flush=True)
    except RulesError as error:
        print(f"[lanchonete] edited rules are invalid, keeping the previous ones: {error}",
              flush=True)
    return changed


def command_run(args, store_factory, page_factory) -> None:
    rules, store, now = _context(args, store_factory)
    model = _model(rules, store, not args.no_llm)
    if not args.live:
        print("[lanchonete] dry run: decisions are printed, nothing is sent "
              "(use --live to send)", flush=True)
    if not store.acquire():
        raise SystemExit("[lanchonete] another lanchonete run is active; one conversation at a "
                         "time")
    if args.recover:
        recovered = store.recover_unconfirmed(now)
        print(f"[lanchonete] recovered {len(recovered)} unconfirmed conversation(s)", flush=True)
    try:
        session = Session(args, page_factory, rules, store)
    except RuntimeError as error:
        store.release()
        raise SystemExit(f"[lanchonete] {error}")
    rules_path = Path(args.rules) if args.rules else RULES_PATH
    seen = rules_path.stat().st_mtime
    requested = []

    def stop(signum, frame):
        if requested:
            raise SystemExit(f"[lanchonete] stopped by signal {signum}")
        requested.append(signum)

    previous = signal.signal(signal.SIGTERM, stop)
    failures = cycles = 0
    try:
        agent = LanchoneteAgent(rules, store, session.channel if args.live else None, model,
                                live=args.live, only=tuple(args.only or ()))
        while True:
            if requested:
                break
            seen = _reload(agent, rules_path, seen)
            try:
                events = whatsapp_listener.listen(session.page, store.base, once=True,
                                                  limit=args.max_chats)
                summary = agent.cycle(events)
            except Exception as error:
                if not is_closed(error) or failures >= 3:
                    raise
                failures += 1
                print(f"[lanchonete] browser page closed ({type(error).__name__}); reconnecting",
                      flush=True)
                session.close()
                session.open()
                if agent.live:
                    agent.channel = session.channel
                continue
            failures = 0
            for item in summary["replies"]:
                if item.get("state") in ("unconfirmed", "error"):
                    print(f"[lanchonete] send fenced for {item.get('name')}; that customer is "
                          f"waiting for the owner, the other chats continue", flush=True)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            cycles += 1
            if args.once or (args.max_cycles and cycles >= args.max_cycles):
                break
            for _ in range(max(1, int(args.interval))):
                if requested:
                    break
                session.page.wait_for_timeout(1000)
    finally:
        signal.signal(signal.SIGTERM, previous)
        session.close()
        store.release()


def add_parser(actions, store_factory, page_factory) -> None:
    lanchonete = actions.add_parser(
        "lanchonete", help="Brasa & Pão WhatsApp ordering agent (dry-run by default)")
    sub = lanchonete.add_subparsers(dest="lanchonete_action", required=True)

    def action(name: str, help_text: str, handler):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--network", choices=("whatsapp",), required=True)
        parser.add_argument("--rules", default=None,
                            help="alternative rules file (owner review and tests)")
        parser.set_defaults(func=handler)
        return parser

    check = action("check", "validate the rules and show the counters",
                   lambda args: command_check(args, store_factory))
    check.add_argument("--ping", action="store_true")
    menu = action("menu", "print the menu, the extras and the payment methods",
                  lambda args: command_menu(args, store_factory))
    menu.add_argument("--json", action="store_true")
    simulate = action("simulate", "play a customer conversation offline",
                      lambda args: command_simulate(args, store_factory))
    simulate.add_argument("--text", action="append", default=[],
                          help="customer message; repeat it for a sequence")
    simulate.add_argument("--chat", default="(65) 90000-0001")
    simulate.add_argument("--at", default="19:00", help="local time for the simulation")
    allow = action("allow", "owner: register a number the bot may answer",
                   lambda args: command_allow(args, store_factory))
    allow.add_argument("--phone", required=True)
    allow.add_argument("--name", required=True)
    allow.add_argument("--chat", default=None, help="WhatsApp chat title, when different")
    opening = action("opening", "owner: send the greeting and menu to a registered customer",
                     lambda args: command_opening(args, store_factory, page_factory))
    opening.add_argument("--customer", required=True)
    customers = action("customers", "list customers and their state",
                       lambda args: command_customers(args, store_factory))
    customers.add_argument("--state", default=None)
    orders = action("pedidos", "list confirmed orders",
                    lambda args: command_pedidos(args, store_factory))
    orders.add_argument("--today", action="store_true")
    orders.add_argument("--limit", type=int, default=20)
    ficha = action("ficha", "print one order ficha",
                   lambda args: command_ficha(args, store_factory))
    ficha.add_argument("--order", required=True)
    ficha.add_argument("--path", action="store_true")
    resolve = action("resolve", "owner: hand a chat back after handling it",
                     lambda args: command_resolve(args, store_factory))
    resolve.add_argument("--customer", required=True)
    resolve.add_argument("--state", required=True,
                         choices=("ordering", "confirming", "confirmed", "closed", "cancelled",
                                  "human"))
    recover = action("recover", "clear a transient unconfirmed state without retrying it",
                     lambda args: command_recover(args, store_factory))
    recover.add_argument("--customer", default=None)
    recover.add_argument("--all", action="store_true")
    block = action("block", "owner: never reply to this number again",
                   lambda args: command_block(args, store_factory))
    block.add_argument("--customer", required=True)
    run = action("run", "listen, answer and confirm orders (dry-run unless --live)",
                 lambda args: command_run(args, store_factory, page_factory))
    run.add_argument("--live", action="store_true", help="actually send")
    run.add_argument("--once", action="store_true")
    run.add_argument("--interval", type=int, default=10)
    run.add_argument("--max-cycles", type=int, default=0)
    run.add_argument("--max-chats", type=int, default=30)
    run.add_argument("--no-llm", action="store_true",
                     help="local parser and fixed replies only")
    run.add_argument("--only", action="append", default=[],
                     help="answer only this phone (repeat for more than one)")
    run.add_argument("--recover", action="store_true",
                     help="clear transient unconfirmed states at startup")
