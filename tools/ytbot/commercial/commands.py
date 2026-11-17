"""CLI for private commercial affiliate sessions."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .. import config
from ..social import browser
from ..social.store import SocialStore
from . import reference
from .mercadolivre import account as mercadolivre
from .mercadolivre import products
from . import whatsapp
from .whatsapp import listener as whatsapp_listener
from .whatsapp import sender as whatsapp_sender
from .whatsapp.sales import commands as sales_commands

NETWORKS = ("mercadolivre", "whatsapp")


def _store() -> SocialStore:
    return SocialStore(config.ROOT / ".local" / "commercial")


def _port_ready(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
        return True
    except Exception:
        return False


def _network(name: str):
    if name == "mercadolivre":
        return mercadolivre
    if name == "whatsapp":
        return whatsapp
    raise ValueError("unsupported commercial network")


def command_open(args) -> None:
    store = _store()
    network = _network(args.network)
    browser.open_visible(store, args.network, getattr(network, "OPEN_URL", network.LOGIN_URL),
                         network.CDP_PORT)
    print(f"[commercial] {args.network} window opened. Log in there; the session stays in the "
          f"private {args.network} profile and is never written to Git.")
    print(f"[commercial] when finished run: python3 -m tools.ytbot commercial status "
          f"--network {args.network}")


def command_status(args) -> None:
    from playwright.sync_api import sync_playwright

    store = _store()
    network = _network(args.network)
    if not _port_ready(network.CDP_PORT):
        browser.ensure_background(store, args.network, network.LOGIN_URL, network.CDP_PORT,
                                  network.BACKGROUND_DISPLAY)
    with sync_playwright() as playwright:
        client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
        context = client.contexts[0]
        page = context.new_page()
        try:
            result = network.inspect(page)
        finally:
            page.close()
    if result["state"] == "logged-in":
        label = "WhatsApp Web" if args.network == "whatsapp" else "Mercado Livre Afiliados"
        store.save_account(args.network, handle=args.network, display_name=label)
        print(f"[commercial] {args.network} logged in")
    else:
        print(f"[commercial] {args.network} state: {result['state']}")
    print(json.dumps(store.public_status(args.network), ensure_ascii=False))


def command_products(args) -> None:
    from playwright.sync_api import sync_playwright

    if args.network != "mercadolivre":
        raise SystemExit("[commercial] products is available only for mercadolivre")
    try:
        store = _store()
        network = _network(args.network)
        browser.ensure_background(store, args.network, network.LOGIN_URL, network.CDP_PORT,
                                  network.BACKGROUND_DISPLAY)
        with sync_playwright() as playwright:
            client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
            context = client.contexts[0]
            try:
                context.grant_permissions(["clipboard-read", "clipboard-write"],
                                         origin="https://www.mercadolivre.com.br")
            except Exception:
                pass
            page = context.new_page()
            try:
                state = network.inspect(page)
                if state["state"] != "logged-in":
                    raise RuntimeError(f"{args.network} is {state['state']}; finish login first")
                rows = products.search(
                    page, args.query, limit=args.limit, share=not args.no_share,
                    details=not args.no_details,
                    image_dir=store.network(args.network) / "images",
                )
            finally:
                page.close()
        net_dir = store.network(args.network)
        ref_available, comparisons = reference.compare_with_store_reference(
            net_dir,
            args.network,
            rows,
            refresh=getattr(args, "refresh_ref", False),
        )
        if getattr(args, "skip_existing", False) and ref_available:
            unchanged_ids = {
                c["product_id"]
                for c in comparisons
                if c.get("status") == "unchanged" and c.get("product_id")
            }
            rows = [
                r for r in rows
                if str(r.get("product_id") or "").strip().upper() not in unchanged_ids
            ]
        path = net_dir / "products.json"
        products.save(path, args.query, rows)
        print(json.dumps({
            "query": args.query,
            "count": len(rows),
            "products_file": str(path),
            "reference_available": ref_available,
            "vps_comparison": comparisons,
            "products": rows,
        }, ensure_ascii=False))
    except Exception as error:
        raise SystemExit(f"[commercial] {error}")


def command_whatsapp_send(args) -> None:
    from playwright.sync_api import sync_playwright

    if not args.live and not args.dry_run:
        raise SystemExit("[commercial] whatsapp sending requires --live (or --dry-run)")
    store = _store()
    network = _network("whatsapp")
    image = Path(args.image) if args.image else None
    if image is not None and not image.is_file():
        raise SystemExit(f"[commercial] image not found: {image}")
    messages = [{"to": args.to, "text": args.text, "image": image}]
    pacing = whatsapp_sender.Pacing(args.min_interval, args.max_interval)
    try:
        if not _port_ready(network.CDP_PORT):
            browser.ensure_background(store, "whatsapp", network.LOGIN_URL, network.CDP_PORT,
                                      network.BACKGROUND_DISPLAY)
        with sync_playwright() as playwright:
            client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
            context = client.contexts[0]
            page = context.new_page()
            try:
                state = network.inspect(page)
                if state["state"] != "logged-in":
                    raise RuntimeError("WhatsApp Web is not logged in; run commercial open "
                                       "--network whatsapp and scan the QR code")
                results = whatsapp_sender.send_batch(
                    page, messages, pacing, args.dry_run or not args.live,
                    store.network("whatsapp") / "journal.jsonl", force=args.force)
            finally:
                page.close()
        print(json.dumps(results, ensure_ascii=False))
    except Exception as error:
        raise SystemExit(f"[commercial] {error}")


def _whatsapp_page(args):
    from playwright.sync_api import sync_playwright

    store = _store()
    network = _network("whatsapp")
    if not _port_ready(network.CDP_PORT):
        browser.ensure_background(store, "whatsapp", network.LOGIN_URL, network.CDP_PORT,
                                  network.BACKGROUND_DISPLAY)
    playwright = sync_playwright().start()
    client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
    context = client.contexts[0]
    page = context.new_page()
    state = network.inspect(page)
    if state["state"] != "logged-in":
        page.close()
        playwright.stop()
        raise RuntimeError("WhatsApp Web is not logged in; run commercial open --network whatsapp")
    return store, network, playwright, client, page


def command_whatsapp_listen(args) -> None:
    store, network, playwright, client, page = _whatsapp_page(args)
    try:
        events = whatsapp_listener.listen(
            page, store.network("whatsapp"), once=args.once, interval=args.interval,
            limit=args.max_chats)
    finally:
        page.close()
        client.close()
        playwright.stop()
    print(json.dumps({"events": len(events),
                      "file": str(store.network("whatsapp") / "events.jsonl")},
                     ensure_ascii=False))
    for event in events:
        print(json.dumps(event, ensure_ascii=False))


def command_whatsapp_events(args) -> None:
    store = _store()
    _network("whatsapp")
    path = store.network("whatsapp") / "events.jsonl"
    if not path.is_file():
        print(json.dumps({"events": []}, ensure_ascii=False))
        return
    lines = path.read_text(encoding="utf-8").splitlines()[-args.limit:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    print(json.dumps(events, ensure_ascii=False, indent=2))


def command_whatsapp_rules(args) -> None:
    store = _store()
    _network("whatsapp")
    path = store.network("whatsapp") / "rules.json"
    if not args.mode:
        print(json.dumps(whatsapp_listener.load_rules(path), ensure_ascii=False))
        return
    contacts = [item.strip() for item in (args.contacts or "").split(",") if item.strip()]
    rules = whatsapp_listener.save_rules(path, args.mode, contacts)
    print(json.dumps(rules, ensure_ascii=False))


def command_reference(args) -> None:
    if args.network != "mercadolivre":
        raise SystemExit("[commercial] reference is available only for mercadolivre")
    try:
        store = _store()
        _network(args.network)
        net_dir = store.network(args.network)
        sync_info = reference.refresh_from_vps() if args.refresh else None
        json_path = reference.resolve_reference_json_path(args.network, network_dir=net_dir)
        db_path = reference.resolve_reference_db_path(net_dir)
        rebuilt = reference.ensure_local_reference_db(json_path, db_path)
        result = reference.query_reference_db(
            db_path,
            query=args.query,
            product_id=args.product_id,
            category=args.category,
            trend=args.trend,
            limit=args.limit,
        )
        result["db_rebuilt"] = rebuilt
        if sync_info is not None:
            result["vps_sync"] = sync_info
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        raise SystemExit(f"[commercial] {error}")


def command_stop(args) -> None:
    store = _store()
    _network(args.network)
    browser.stop(store, args.network)


def add_parser(sub) -> None:
    commercial = sub.add_parser("commercial", help="private commercial affiliate sessions")
    actions = commercial.add_subparsers(dest="commercial_action", required=True)
    open_parser = actions.add_parser("open", help="open the visible affiliate login page")
    open_parser.add_argument("--network", choices=NETWORKS, required=True)
    open_parser.set_defaults(func=command_open)
    status_parser = actions.add_parser("status", help="detect and save the affiliate session")
    status_parser.add_argument("--network", choices=NETWORKS, required=True)
    status_parser.set_defaults(func=command_status)
    products_parser = actions.add_parser("products", help="search affiliate products and copy links")
    products_parser.add_argument("--network", choices=NETWORKS, required=True)
    products_parser.add_argument("--query", required=True)
    products_parser.add_argument("--limit", type=int, default=5)
    products_parser.add_argument("--no-share", action="store_true",
                                 help="list products without opening the share dialog")
    products_parser.add_argument("--no-details", action="store_true",
                                 help="skip the product page details and photo download")
    products_parser.add_argument("--skip-existing", action="store_true",
                                 help="omit products whose captured price equals the VPS reference")
    products_parser.add_argument("--refresh-ref", action="store_true",
                                 help="refresh the cached VPS reference database before comparing")
    products_parser.set_defaults(func=command_products)
    send_parser = actions.add_parser(
        "send", help="send one human-paced WhatsApp Web message (requires --live)")
    send_parser.add_argument("--network", choices=("whatsapp",), required=True)
    send_parser.add_argument("--to", required=True, help="contact name or phone number")
    send_parser.add_argument("--text", required=True)
    send_parser.add_argument("--image", default=None)
    send_parser.add_argument("--live", action="store_true", help="actually send")
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.add_argument("--force", action="store_true", help="ignore the sent journal")
    send_parser.add_argument("--min-interval", type=float, default=8.0)
    send_parser.add_argument("--max-interval", type=float, default=25.0)
    send_parser.set_defaults(func=command_whatsapp_send)
    listen_parser = actions.add_parser(
        "listen", help="scan WhatsApp Web and record incoming messages as events")
    listen_parser.add_argument("--network", choices=("whatsapp",), required=True)
    listen_parser.add_argument("--once", action="store_true")
    listen_parser.add_argument("--interval", type=int, default=30)
    listen_parser.add_argument("--max-chats", type=int, default=30)
    listen_parser.set_defaults(func=command_whatsapp_listen)
    events_parser = actions.add_parser("events", help="read recorded WhatsApp events")
    events_parser.add_argument("--network", choices=("whatsapp",), required=True)
    events_parser.add_argument("--limit", type=int, default=20)
    events_parser.set_defaults(func=command_whatsapp_events)
    rules_parser = actions.add_parser(
        "rules", help="allow or block contacts for future WhatsApp replies")
    rules_parser.add_argument("--network", choices=("whatsapp",), required=True)
    rules_parser.add_argument("--mode", choices=("allow", "block"), default=None)
    rules_parser.add_argument("--contacts", default="", help="comma-separated names")
    rules_parser.set_defaults(func=command_whatsapp_rules)
    ref_parser = actions.add_parser(
        "reference",
        help="query the fast local VPS product and price-history reference DB",
    )
    ref_parser.add_argument("--network", choices=NETWORKS, required=True)
    ref_parser.add_argument("--refresh", action="store_true",
                            help="sync latest ETag-cached snapshot from the VPS before querying")
    ref_parser.add_argument("--query", default="",
                            help="search keywords in title, brand, category or summary")
    ref_parser.add_argument("--product-id", default="",
                            help="exact Mercado Livre MLB catalog ID lookup")
    ref_parser.add_argument("--category", default="",
                            help="filter by category or subcategory slug")
    ref_parser.add_argument("--trend", choices=("", "new", "down", "up", "stable"), default="",
                            help="filter by price trend")
    ref_parser.add_argument("--limit", type=int, default=20)
    ref_parser.set_defaults(func=command_reference)
    sales_commands.add_parser(actions, _store, _whatsapp_page)
    stop_parser = actions.add_parser("stop", help="stop the hidden affiliate browser")
    stop_parser.add_argument("--network", choices=NETWORKS, required=True)
    stop_parser.set_defaults(func=command_stop)
