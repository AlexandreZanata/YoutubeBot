"""Typed CLI for Google Maps research: `commercial maps <action>`."""

from __future__ import annotations

import json
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

from ...social import browser
from ..whatsapp.sales.store import SalesStore, phone_key
from . import driver, render
from .record import RunStore, validate_city, validate_state
from .rules import MapsRules, RulesError, load


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _rules() -> MapsRules:
    try:
        return load()
    except RulesError as error:
        raise SystemExit(f"[maps] invalid data file: {error}")


def _run_store(store) -> RunStore:
    return RunStore(store.network("maps"))


def _now(rules: MapsRules) -> datetime:
    return datetime.now(ZoneInfo(rules.timezone))


def _connect(store, rules: MapsRules):
    from playwright.sync_api import sync_playwright

    port = int(rules.browser["cdp_port"])
    browser.ensure_background(store, "maps", rules.browser["login_url"], port,
                              rules.browser["background_display"])
    playwright = sync_playwright().start()
    try:
        client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page = client.contexts[0].new_page()
    except Exception:
        playwright.stop()
        raise
    return playwright, client, page


def _close(playwright, client, page) -> None:
    try:
        page.close()
    finally:
        try:
            client.close()
        finally:
            playwright.stop()


def command_login(args, store_factory) -> None:
    rules = _rules()
    store = store_factory()
    browser.open_visible(store, "maps", rules.browser["login_url"],
                         int(rules.browser["cdp_port"]))
    print("[maps] janela visível aberta. Entre na conta Google do dono por conta própria; "
          "a sessão fica no perfil privado e nunca vai para o Git.")
    print("[maps] quando terminar rode: python3 -m tools.ytbot commercial maps status")


def command_status(args, store_factory) -> None:
    rules = _rules()
    store = store_factory()
    playwright, client, page = _connect(store, rules)
    try:
        state = driver.inspect(page, rules)
    finally:
        _close(playwright, client, page)
    if state["state"] == "logged-in":
        store.save_account("maps", handle="google-maps", display_name="Google Maps")
        _run_store(store).clear_attention()
    _print({"network": "maps", "browser": store.public_status("maps"), "page": state})


def command_research(args, store_factory) -> None:
    rules = _rules()
    store = store_factory()
    try:
        city = validate_city(args.city)
        uf = validate_state(args.state)
    except ValueError as error:
        raise SystemExit(f"[maps] {error}")
    groups = [item for item in (args.group or []) if item]
    unknown = [item for item in groups if item not in rules.groups]
    if unknown:
        raise SystemExit("[maps] unknown group(s): " + ", ".join(unknown) + "; use "
                         + ", ".join(sorted(rules.groups)))
    searches = [search for search in rules.searches if not groups or search.group in groups]
    now = _now(rules)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("[maps] --limit must be at least 1")
    runs = _run_store(store)
    run = runs.create(city, uf, now)
    already = runs.daily_businesses(run.day)
    allowance = rules.daily_businesses() - already
    requested = args.limit if args.limit is not None else rules.daily_businesses()
    limit = min(int(requested), allowance)
    if limit <= 0:
        print(f"[maps] limite diário de {rules.daily_businesses()} empresas já foi usado em "
              f"{run.day}; rode amanhã ou ajuste limits.daily_businesses")
        return

    playwright, client, page = _connect(store, rules)
    try:
        state = driver.inspect(page, rules)
        if state["state"] != "logged-in":
            raise driver.LoginRequired(
                f"Google Maps não está conectado ({state['state']}); rode "
                "commercial maps login", state)
        result = driver.research(page, run, rules, searches, limit, now,
                                 log=lambda message: print(message, flush=True))
    except driver.ResearchError as error:
        entry = runs.record_attention(run, error.stage, error.reason, error.evidence, _now(rules))
        print(f"[maps] parado: {error.reason}. Registro em {runs.attention_path}")
        _print(entry)
        raise SystemExit(2)
    except Exception as error:  # a broken page or network is a stop, never a retry loop
        entry = runs.record_attention(run, "error", str(error), {"url": page.url},
                                      _now(rules))
        print(f"[maps] parado por erro: {error}. Registro em {runs.attention_path}")
        _print(entry)
        raise SystemExit(2)
    finally:
        _close(playwright, client, page)
    _print({"run": run.id, "directory": str(run.path), **result,
            "next": f"python3 -m tools.ytbot commercial maps verify --run {run.id}"})


def command_verify(args, store_factory) -> None:
    rules = _rules()
    store = store_factory()
    runs = _run_store(store)
    try:
        run = runs.resolve(args.run)
    except ValueError as error:
        raise SystemExit(f"[maps] {error}")
    playwright, client, page = _connect(store, rules)
    try:
        state = driver.inspect(page, rules)
        if state["state"] != "logged-in":
            raise driver.LoginRequired(
                f"Google Maps não está conectado ({state['state']}); rode "
                "commercial maps login", state)
        result = driver.verify_run(page, run, rules,
                                   log=lambda message: print(message, flush=True))
    except driver.ResearchError as error:
        entry = runs.record_attention(run, error.stage, error.reason, error.evidence, _now(rules))
        print(f"[maps] parado: {error.reason}. Registro em {runs.attention_path}")
        _print(entry)
        raise SystemExit(2)
    except Exception as error:
        entry = runs.record_attention(run, "error", str(error), {"url": page.url},
                                      _now(rules))
        print(f"[maps] parado por erro: {error}. Registro em {runs.attention_path}")
        _print(entry)
        raise SystemExit(2)
    finally:
        _close(playwright, client, page)
    _print({"run": run.id, **result,
            "next": f"python3 -m tools.ytbot commercial maps export --run {run.id}"})


def command_export(args, store_factory) -> None:
    rules = _rules()
    store = store_factory()
    runs = _run_store(store)
    try:
        run = runs.resolve(args.run)
    except ValueError as error:
        raise SystemExit(f"[maps] {error}")
    sales = SalesStore(store.network("whatsapp"))
    lead_keys = {phone_key(lead.get("phone", "")) for lead in sales.leads().values()}
    lead_keys.discard(None)
    result = render.export_run(run, rules, _now(rules), lead_keys, set(sales.dnc()))
    _print(result)


def add_parser(actions, store_factory) -> None:
    maps = actions.add_parser("maps", help="Google Maps lead research (read-only, one tab)")
    sub = maps.add_subparsers(dest="maps_action", required=True)

    def action(name: str, help_text: str, handler):
        parser = sub.add_parser(name, help=help_text)
        parser.set_defaults(func=handler)
        return parser

    action("login", "open the visible Google window for the owner's manual sign-in",
           partial(command_login, store_factory=store_factory))
    action("status", "detect the private Google Maps session",
           partial(command_status, store_factory=store_factory))
    research = action("research", "read one city's public listings at a human pace",
                      partial(command_research, store_factory=store_factory))
    research.add_argument("--city", required=True)
    research.add_argument("--state", required=True, help="two-letter UF, e.g. MT")
    research.add_argument("--group", action="append", default=None,
                          help="one category group (repeatable)")
    research.add_argument("--limit", type=int, default=None,
                          help="businesses in this run (default: the daily limit)")
    verify_parser = action("verify", "confirmation searches for one run",
                           partial(command_verify, store_factory=store_factory))
    verify_parser.add_argument("--run", required=True,
                               help="<city-slug>/<YYYY-MM-DD> or just the city slug")
    export_parser = action("export", "write candidatos.csv, ajuste-maps.csv and report.md",
                           partial(command_export, store_factory=store_factory))
    export_parser.add_argument("--run", required=True,
                               help="<city-slug>/<YYYY-MM-DD> or just the city slug")
