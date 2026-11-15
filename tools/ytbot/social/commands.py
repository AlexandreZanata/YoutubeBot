"""CLI for private social-network sessions used by the promotion module."""

from __future__ import annotations

import json

from . import browser
from .store import SocialStore
from .x import account as x_account

NETWORKS = ("x",)


def _network(name: str):
    if name == "x":
        return x_account
    raise ValueError("unsupported social network")


def command_open(args) -> None:
    store = SocialStore()
    network = _network(args.network)
    browser.open_visible(store, args.network, network.LOGIN_URL, network.CDP_PORT)
    print(f"[social] {args.network} window opened. Log in there; the session stays in the "
          f"private {args.network} profile and is never written to Git.")
    print(f"[social] when finished run: python3 -m tools.ytbot social status --network {args.network}")


def command_status(args) -> None:
    from playwright.sync_api import sync_playwright

    store = SocialStore()
    network = _network(args.network)
    if not browser.cdp_alive(network.CDP_PORT):
        browser.open_visible(store, args.network, network.LOGIN_URL, network.CDP_PORT)
    with sync_playwright() as playwright:
        client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
        context = client.contexts[0]
        page = context.new_page()
        try:
            result = network.inspect(page)
        finally:
            page.close()
    if result["state"] == "logged-in" and result.get("handle"):
        store.save_account(args.network, handle=result["handle"],
                           display_name=result.get("display_name", ""))
        print(f"[social] {args.network} logged in as @{result['handle']}")
    else:
        print(f"[social] {args.network} state: {result['state']}")
    print(json.dumps(store.public_status(args.network), ensure_ascii=False))


def add_parser(sub) -> None:
    social = sub.add_parser("social", help="private social-network sessions for project promotion")
    actions = social.add_subparsers(dest="social_action", required=True)
    open_parser = actions.add_parser("open", help="open the visible login browser for a network")
    open_parser.add_argument("--network", choices=NETWORKS, required=True)
    open_parser.set_defaults(func=command_open)
    status_parser = actions.add_parser("status", help="detect and save the logged-in account")
    status_parser.add_argument("--network", choices=NETWORKS, required=True)
    status_parser.set_defaults(func=command_status)
