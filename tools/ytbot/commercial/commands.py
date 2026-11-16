"""CLI for private commercial affiliate sessions."""

from __future__ import annotations

import json

from .. import config
from ..social import browser
from ..social.store import SocialStore
from . import reference
from .mercadolivre import account as mercadolivre
from .mercadolivre import products

NETWORKS = ("mercadolivre",)


def _store() -> SocialStore:
    return SocialStore(config.ROOT / ".local" / "commercial")


def _network(name: str):
    if name == "mercadolivre":
        return mercadolivre
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
        store.save_account(args.network, handle="mercadolivre",
                           display_name="Mercado Livre Afiliados")
        print(f"[commercial] {args.network} logged in")
    else:
        print(f"[commercial] {args.network} state: {result['state']}")
    print(json.dumps(store.public_status(args.network), ensure_ascii=False))


def command_products(args) -> None:
    from playwright.sync_api import sync_playwright

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


def command_reference(args) -> None:
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
    stop_parser = actions.add_parser("stop", help="stop the hidden affiliate browser")
    stop_parser.add_argument("--network", choices=NETWORKS, required=True)
    stop_parser.set_defaults(func=command_stop)
