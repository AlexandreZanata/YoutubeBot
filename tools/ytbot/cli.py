"""Command line entry point for the local YouTube automation bot."""

from __future__ import annotations

import argparse
import contextlib
import json
from datetime import datetime

from . import account, catalog, channels, community, config, flow_profiles, logic, runtime


def command_setup(_args) -> None:
    runtime.setup_profile()
    runtime.start_hidden_chrome()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser, context = runtime.connect_hidden(playwright)
        runtime.configure_downloads(browser)
        runtime.configure_extension(context)
    print("[ytbot] runtime ready in hidden workspace", config.DISPLAY)


def command_catalog(args) -> None:
    if args.channel:
        channels.apply(args.channel)
    runtime.start_hidden_chrome()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser, context = runtime.connect_hidden(playwright)
        data = catalog.scrape_public_catalog(context)
        catalog.write_catalog_markdown(data)
    print(f"[ytbot] catalog: {len(data)} videos")


def command_check(args) -> None:
    if args.channel:
        channels.apply(args.channel)
    matches = logic.similar_topics(args.topic, logic.load_catalog())
    if matches:
        print("[ytbot] topic is similar to:")
        for title in matches:
            print("  - " + title)
    else:
        print("[ytbot] topic is new")


def command_community(args) -> None:
    channels.apply(args.channel)
    runtime.start_hidden_chrome()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        _browser, context = runtime.connect_hidden(playwright)
        account.ensure_channel(context)
        topics = args.topic or []
        if not topics and config.TOPICS.is_file():
            topics = [config.TOPICS.read_text(encoding="utf-8").splitlines()[0].strip()]
        community.ensure_post(context, topics or ["What do you think?"])


def command_shorts(args) -> None:
    from .shorts import run_shorts
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    failures = run_shorts(args.channel, args.count, args.per_day, start_date,
                          args.upload_account, args.start_index, args.skip_slots)
    print("[ytbot] shorts process finished")
    if failures:
        print(f"[ytbot] {len(failures)} shorts failure(s): {failures}")
        raise SystemExit(1)


def command_run(args) -> None:
    flow_profiles.activate(flow_profiles.name(getattr(args, "flow_profile", None), environment=True))
    channels.apply(args.channel)
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    if args.upload_account and args.upload_cdp:
        raise SystemExit("use --upload-account or --upload-cdp, not both")
    from .batch import run_batch
    from .account_commands import apply_bound_account
    from .accounts_store import AccountStore
    from .service_jobs import channel_lock
    store = AccountStore()
    upload_cdp = args.upload_cdp or 0
    if args.upload_account:
        upload = store.account(args.upload_account)
        upload_cdp = upload["cdp_port"]
        store.activate(args.upload_account)
        runtime.start_hidden_chrome()
    selected = apply_bound_account(args.channel, args.account)
    runtime.start_hidden_chrome()
    with contextlib.ExitStack() as stack:
        stack.enter_context(store.profile_lock(selected))
        if args.upload_account and args.upload_account != selected:
            stack.enter_context(store.profile_lock(args.upload_account))
        stack.enter_context(channel_lock(args.channel))
        try:
            failures = run_batch(args.count, args.parallel, upload_cdp or None, start_date,
                                 args.topic or None)
        except RuntimeError as error:
            print(f"[ytbot] {error}")
            raise SystemExit(1)
    print("[ytbot] process finished")
    if failures:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ytbot", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="prepare cookies, extension and hidden Chrome").set_defaults(func=command_setup)
    catalog_parser = sub.add_parser("catalog", help="refresh the channel catalog")
    catalog_parser.add_argument("--channel", choices=sorted(channels.CHANNELS), default="")
    catalog_parser.set_defaults(func=command_catalog)
    check = sub.add_parser("check", help="check a topic against the catalog")
    check.add_argument("topic")
    check.add_argument("--channel", choices=sorted(channels.CHANNELS), default="")
    check.set_defaults(func=command_check)
    community_parser = sub.add_parser("community", help="check the Community tab and publish a first post when empty")
    community_parser.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    community_parser.add_argument("--topic", action="append", default=[])
    community_parser.set_defaults(func=command_community)
    shorts = sub.add_parser("shorts", help="generate, render and schedule vertical Shorts")
    shorts.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    shorts.add_argument("--count", type=int, default=12)
    shorts.add_argument("--per-day", type=int, choices=(1, 2), default=2)
    shorts.add_argument("--start-date", default=None, help="first schedule date (YYYY-MM-DD)")
    shorts.add_argument("--upload-account", default="zaflas")
    shorts.add_argument("--start-index", type=int, default=0,
                        help="skip this many topics in the shorts queue")
    shorts.add_argument("--skip-slots", type=int, default=0,
                        help="skip this many leading schedule slots")
    shorts.set_defaults(func=command_shorts)
    run = sub.add_parser("run", help="generate, render, upload and schedule videos")
    run.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True,
                     help="channel profile; ask the user when it is not specified")
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--start-date", default=None, help="first schedule date (YYYY-MM-DD)")
    run.add_argument("--topic", action="append", default=[],
                     help="explicit topic; repeat for many, skips topic suggestion")
    run.add_argument("--account", default=None, help="explicit registered browser account (otherwise the channel binding or legacy session)")
    run.add_argument("--parallel", type=int, default=0,
                     help="tabs used for article and audio stages (0 = one per video)")
    run.add_argument("--upload-cdp", type=int, default=0)
    run.add_argument("--upload-account", default=None,
                     help="separate upload-only account/profile; generation stays in --account")
    run.add_argument("--flow-profile", choices=flow_profiles.NAMES, default=None,
                     help="ASR/render execution profile (or YTBOT_FLOW_PROFILE; default standard)")
    run.set_defaults(func=command_run)
    from .account_commands import add_parser
    add_parser(sub)
    from .social.commands import add_parser as add_social_parser
    add_social_parser(sub)
    from .commercial.commands import add_parser as add_commercial_parser
    add_commercial_parser(sub)
    return parser


def main() -> None:
    config.configure_timezone()
    args = build_parser().parse_args()
    args.func(args)
