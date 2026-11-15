"""CLI for private social-network sessions used by the promotion module."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config
from . import agenda as agenda_module
from . import browser
from .store import SocialStore
from .x import account as x_account
from .x import publish

NETWORKS = ("x",)
DEFAULT_AGENDA = config.ROOT / ".local" / "promotion" / "agenda.json"


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


def command_agenda(args) -> None:
    store = SocialStore()
    data = agenda_module.load_agenda(Path(args.file))
    posts = agenda_module.read_posts(store, args.network).get("posts", {})
    for item in data["items"]:
        state = posts.get(item["id"], {}).get("state", "pending")
        print(f"{item['id']}  {item['date']}  {item['product']:<14}  "
              f"{item['format']:<6}  {item['status']:<8}  {state}")


def command_post(args) -> None:
    try:
        _post(args)
    except Exception as error:
        raise SystemExit(f"[social] {error}")


def _post(args) -> None:
    from playwright.sync_api import sync_playwright

    store = SocialStore()
    network = _network(args.network)
    data = agenda_module.load_agenda(Path(args.file))
    item = agenda_module.item_by_id(data, args.id)
    if not browser.cdp_alive(network.CDP_PORT):
        browser.open_visible(store, args.network, network.LOGIN_URL, network.CDP_PORT)
    with sync_playwright() as playwright:
        client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
        context = client.contexts[0]
        page = context.new_page()
        try:
            state = network.inspect(page)
        finally:
            page.close()
        if state["state"] != "logged-in":
            raise RuntimeError(f"{args.network} is {state['state']}; finish login first")
        result = publish.publish(context, store, args.network, item, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))


def add_parser(sub) -> None:
    social = sub.add_parser("social", help="private social-network sessions for project promotion")
    actions = social.add_subparsers(dest="social_action", required=True)
    open_parser = actions.add_parser("open", help="open the visible login browser for a network")
    open_parser.add_argument("--network", choices=NETWORKS, required=True)
    open_parser.set_defaults(func=command_open)
    status_parser = actions.add_parser("status", help="detect and save the logged-in account")
    status_parser.add_argument("--network", choices=NETWORKS, required=True)
    status_parser.set_defaults(func=command_status)
    agenda_parser = actions.add_parser("agenda", help="list the private promotion agenda")
    agenda_parser.add_argument("--network", choices=NETWORKS, required=True)
    agenda_parser.add_argument("--file", default=str(DEFAULT_AGENDA))
    agenda_parser.set_defaults(func=command_agenda)
    post_parser = actions.add_parser("post", help="publish one approved agenda item")
    post_parser.add_argument("--network", choices=NETWORKS, required=True)
    post_parser.add_argument("--id", required=True)
    post_parser.add_argument("--file", default=str(DEFAULT_AGENDA))
    post_parser.add_argument("--dry-run", action="store_true",
                             help="fill the composer and close it without posting")
    post_parser.set_defaults(func=command_post)
