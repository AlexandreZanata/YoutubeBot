"""CLI for private social-network sessions used by the promotion module."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config
from . import agenda as agenda_module
from . import browser, discovery
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
    if result["state"] == "logged-in" and result.get("handle"):
        store.save_account(args.network, handle=result["handle"],
                           display_name=result.get("display_name", ""))
        print(f"[social] {args.network} logged in as @{result['handle']}")
    else:
        print(f"[social] {args.network} state: {result['state']}")
    print(json.dumps(store.public_status(args.network), ensure_ascii=False))


def command_discover(args) -> None:
    from playwright.sync_api import sync_playwright

    try:
        store = SocialStore()
        network = _network(args.network)
        browser.ensure_background(store, args.network, network.LOGIN_URL, network.CDP_PORT,
                                  network.BACKGROUND_DISPLAY)
        with sync_playwright() as playwright:
            client = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{network.CDP_PORT}")
            context = client.contexts[0]
            page = context.new_page()
            try:
                state = network.inspect(page)
                if state["state"] != "logged-in":
                    raise RuntimeError(f"{args.network} is {state['state']}; finish login first")
                rows = discovery.curate(page, args.product, days=args.days, limit=args.limit,
                                        own_handle=state.get("handle", ""))
            finally:
                page.close()
        path = discovery.save_candidates(store, args.network, args.product, rows)
        print(f"[social] {len(rows)} candidate(s) saved to {path}")
        for row in rows:
            print(f"{row['score']:>3}  {row['published_at'][:10]}  @{row['author']:<15}  "
                  f"{row['url']}  {row['text'][:90].replace(chr(10), ' ')}")
    except Exception as error:
        raise SystemExit(f"[social] {error}")


def command_reply(args) -> None:
    from playwright.sync_api import sync_playwright

    try:
        text = Path(args.file).read_text(encoding="utf-8").strip() if args.file else args.text
        store = SocialStore()
        network = _network(args.network)
        browser.ensure_background(store, args.network, network.LOGIN_URL, network.CDP_PORT,
                                  network.BACKGROUND_DISPLAY)
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
            result = publish.reply(context, store, args.network, args.url, text,
                                   dry_run=args.dry_run, for_post=args.for_post)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        raise SystemExit(f"[social] {error}")


def command_quota(args) -> None:
    try:
        store = SocialStore()
        _network(args.network)
        counts = publish.reply_counts(store, args.network)
        if not counts:
            print("[social] no published posts in the journal")
            return
        for identifier, count in sorted(counts.items()):
            print(f"{identifier}  {count}/{publish.REPLIES_PER_POST}")
    except Exception as error:
        raise SystemExit(f"[social] {error}")


def command_stop(args) -> None:
    store = SocialStore()
    _network(args.network)
    browser.stop(store, args.network)


def command_agenda(args) -> None:
    try:
        store = SocialStore()
        data = agenda_module.load_agenda(Path(args.file))
        posts = agenda_module.read_posts(store, args.network).get("posts", {})
        for item in data["items"]:
            state = posts.get(item["id"], {}).get("state", "pending")
            print(f"{item['id']}  {item['date']}  {item['product']:<14}  "
                  f"{item['format']:<6}  {item['status']:<8}  {state}")
    except Exception as error:
        raise SystemExit(f"[social] {error}")


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
    browser.ensure_background(store, args.network, network.LOGIN_URL, network.CDP_PORT,
                              network.BACKGROUND_DISPLAY)
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
    stop_parser = actions.add_parser("stop", help="stop the hidden browser for a network")
    stop_parser.add_argument("--network", choices=NETWORKS, required=True)
    stop_parser.set_defaults(func=command_stop)
    quota_parser = actions.add_parser("quota", help="show contextual replies per published post")
    quota_parser.add_argument("--network", choices=NETWORKS, required=True)
    quota_parser.set_defaults(func=command_quota)
    discover_parser = actions.add_parser("discover", help="search recent posts for contextual replies")
    discover_parser.add_argument("--network", choices=NETWORKS, required=True)
    discover_parser.add_argument("--product", choices=sorted(discovery.PRODUCTS), required=True)
    discover_parser.add_argument("--days", type=int, default=7)
    discover_parser.add_argument("--limit", type=int, default=10)
    discover_parser.set_defaults(func=command_discover)
    reply_parser = actions.add_parser("reply", help="reply to one discovery target with context")
    reply_parser.add_argument("--network", choices=NETWORKS, required=True)
    reply_parser.add_argument("--url", required=True)
    reply_parser.add_argument("--for-post", required=True,
                              help="own post id this reply supports, for the five-reply quota")
    reply_group = reply_parser.add_mutually_exclusive_group(required=True)
    reply_group.add_argument("--text")
    reply_group.add_argument("--file")
    reply_parser.add_argument("--dry-run", action="store_true")
    reply_parser.set_defaults(func=command_reply)
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
