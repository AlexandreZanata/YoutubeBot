"""CLI for private commercial affiliate sessions."""

from __future__ import annotations

import json

from .. import config
from ..social import browser
from ..social.store import SocialStore
from .mercadolivre import account as mercadolivre

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
    stop_parser = actions.add_parser("stop", help="stop the hidden affiliate browser")
    stop_parser.add_argument("--network", choices=NETWORKS, required=True)
    stop_parser.set_defaults(func=command_stop)
