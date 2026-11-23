"""Command line entry point for the local YouTube automation bot."""

from __future__ import annotations

import argparse
import contextlib
import json
from datetime import datetime

from . import account, catalog, channels, comments, community, config, flow_profiles, logic, runtime


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
    if not args.channel:
        results = community.publish_all(dry_run=args.dry_run)
        if not results:
            raise SystemExit("no channel posts were attempted")
        return
    channels.apply(args.channel)
    runtime.start_hidden_chrome()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        _browser, context = runtime.connect_hidden(playwright)
        account.ensure_channel(context)
        topics = args.topic or []
        if not topics and config.TOPICS.is_file():
            topics = [config.TOPICS.read_text(encoding="utf-8").splitlines()[0].strip()]
        community.ensure_post(context, topics or ["What do you think?"], args.dry_run)


def command_comments(args) -> None:
    from .comments import answer_all
    slugs = [args.channel] if args.channel else None
    results = answer_all(slugs=slugs, limit=args.limit, dry_run=args.dry_run)
    if not results:
        raise SystemExit("no channel comments were checked")


def command_distribute_shorts(args) -> None:
    from .shorts_distribute import run_distribution
    failures = run_distribution(
        args.count,
        args.dry_run,
        visual_mode=getattr(args, "visual_mode", None),
        video_provider=getattr(args, "video_provider", None),
        video_model=getattr(args, "video_model", None),
    )
    print("[ytbot] shorts distribution finished")
    if failures:
        print(f"[ytbot] shorts channel failures: {failures}")
        raise SystemExit(1)


def command_faith_shorts(args) -> None:
    from .faith_shorts import run
    start = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    failures = run(
        args.channel,
        args.count,
        start,
        args.skip_slots,
        args.start_index,
        visual_mode=getattr(args, "visual_mode", None),
        video_provider=getattr(args, "video_provider", None),
        video_model=getattr(args, "video_model", None),
        max_credits=getattr(args, "max_credits", None),
        max_scenes=getattr(args, "max_scenes", None),
        fallback_to_static=(False if getattr(args, "no_static_fallback", False) else None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    print("[ytbot] faith shorts finished")
    if failures:
        print(f"[ytbot] {len(failures)} failure(s): {failures}")
        raise SystemExit(1)


def command_cleanup(args) -> None:
    from .cleanup import before_run
    before_run(args.dry_run)


def command_shorts(args) -> None:
    from . import cleanup
    from .shorts import run_shorts
    if not getattr(args, "dry_run", False):
        cleanup.before_run()
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    failures = run_shorts(
        args.channel,
        args.count,
        args.per_day,
        start_date,
        args.upload_account,
        args.start_index,
        args.skip_slots,
        visual_mode=getattr(args, "visual_mode", None),
        video_provider=getattr(args, "video_provider", None),
        video_model=getattr(args, "video_model", None),
        max_credits=getattr(args, "max_credits", None),
        max_scenes=getattr(args, "max_scenes", None),
        fallback_to_static=(False if getattr(args, "no_static_fallback", False) else None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    print("[ytbot] shorts process finished")
    if failures:
        print(f"[ytbot] {len(failures)} shorts failure(s): {failures}")
        raise SystemExit(1)


def command_shorts_video(args) -> None:
    import shutil
    from pathlib import Path
    from .shorts_video import credits, flow_browser, settings
    from .shorts_video.pipeline import render_ai_short
    from .shorts_video.providers import get_provider
    from .shorts_video.settings import resolve_runtime_settings

    action = args.action
    if action == "status":
        active = settings.load_settings()
        flow_status = flow_browser.check_flow_readiness(probe_browser=bool(args.probe))
        provider_status = {
            name: get_provider(name).check_availability(active)
            for name in settings.VALID_PROVIDERS
        }
        print(json.dumps({
            "settings": active,
            "flow": flow_status,
            "providers": provider_status,
            "credits": credits.ledger_summary(),
        }, indent=2, ensure_ascii=False))
        return
    if action == "login":
        pid = flow_browser.open_visible_login()
        print(f"[shorts-video] Google Flow visible browser opened (pid={pid})")
        return
    if action == "stop":
        flow_browser.stop_flow_browser()
        print("[shorts-video] Google Flow browser stopped")
        return
    if action == "configure":
        updates = {}
        if args.enable:
            updates["enabled"] = True
            updates["visual_mode"] = "ai-video"
        elif args.disable:
            updates["enabled"] = False
            updates["visual_mode"] = "static"
        if args.video_provider:
            updates["provider"] = args.video_provider
        if args.video_model:
            updates["model"] = args.video_model
        if args.quality:
            updates["quality"] = args.quality
        if args.max_credits_short is not None:
            updates["max_credits_per_short"] = args.max_credits_short
        if args.max_credits_batch is not None:
            updates["max_credits_per_batch"] = args.max_credits_batch
        if args.max_scenes is not None:
            updates["max_scenes_per_short"] = args.max_scenes
        if args.allow_paid_api:
            updates["allow_paid_api"] = True
        elif args.disallow_paid_api:
            updates["allow_paid_api"] = False
        if args.fallback_static:
            updates["fallback_to_static"] = True
        elif args.no_static_fallback:
            updates["fallback_to_static"] = False
        saved = settings.save_settings(updates)
        print(json.dumps(saved, indent=2, ensure_ascii=False))
        return
    if action == "estimate":
        channels.apply(args.channel)
        resolved = resolve_runtime_settings(
            visual_mode="ai-video",
            provider=args.video_provider,
            model=args.video_model,
            max_credits_per_short=args.max_credits,
            max_scenes_per_short=args.max_scenes,
        )
        topic = args.topic or "Sample Short topic"
        run_dir = config.DATA_DIR / "shorts" / logic.slug(topic)
        short_file = run_dir / "short.txt"
        script_text = short_file.read_text(encoding="utf-8") if short_file.is_file() else topic
        summary = render_ai_short(
            run_dir,
            args.channel,
            topic,
            script_text,
            visual_mode="ai-video",
            video_provider=resolved["provider"],
            video_model=resolved["model"],
            max_credits_per_short=resolved["max_credits_per_short"],
            max_scenes=resolved["max_scenes_per_short"],
            dry_run=True,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return
    if action == "movie":
        channels.apply(args.channel)
        if not args.run_dir:
            raise SystemExit("movie requires --run-dir with narration and clips")
        run_dir = Path(args.run_dir)
        topic = args.topic or run_dir.name.replace("-", " ").strip()
        resolved = resolve_runtime_settings(
            visual_mode="ai-video",
            provider=args.video_provider,
            model=args.video_model,
            max_credits_per_short=args.max_credits,
            max_scenes_per_short=args.max_scenes,
        )
        summary = render_ai_short(
            run_dir,
            args.channel,
            topic,
            topic,
            visual_mode="ai-video",
            video_provider=resolved["provider"],
            video_model=resolved["model"],
            max_credits_per_short=resolved["max_credits_per_short"],
            max_scenes=resolved["max_scenes_per_short"],
            width=args.width,
            height=args.height,
            context_kind="long-video",
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return
    if action == "import":
        channels.apply(args.channel)
        run_dir = config.DATA_DIR / "shorts" / logic.slug(args.topic)
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        if args.source_dir:
            src = Path(args.source_dir)
            if not src.is_dir():
                raise SystemExit(f"import source directory not found: {src}")
            for clip in sorted(src.glob("*.mp4")):
                shutil.copy2(clip, clips_dir / clip.name)
        short_file = run_dir / "short.txt"
        script_text = short_file.read_text(encoding="utf-8") if short_file.is_file() else args.topic
        from . import faith_shorts, shorts as legacy_shorts
        fallback_fn = legacy_shorts.render_short if args.channel == "zaflas" else faith_shorts.render_short
        summary = render_ai_short(
            run_dir,
            args.channel,
            args.topic,
            script_text,
            visual_mode="ai-video",
            video_provider=args.video_provider or "manual-import",
            video_model=args.video_model,
            static_fallback_fn=fallback_fn,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return
    raise SystemExit(f"unknown shorts-video action: {action}")


def command_reschedule(args) -> None:
    from .reschedule import run
    failures = run(args.channel, args.dry_run, args.enforce_interval)
    print("[ytbot] reschedule finished")
    if failures:
        print(f"[ytbot] {len(failures)} failure(s): {failures}")
        raise SystemExit(1)


def command_distribute(args) -> None:
    from .distribute import run_distribution
    failures = run_distribution(args.count, args.dry_run, args.concurrency)
    print("[ytbot] distribution finished")
    if failures:
        print(f"[ytbot] channel failures: {failures}")
        raise SystemExit(1)


def command_run(args) -> None:
    from . import cleanup
    cleanup.before_run()
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
        # The legacy profile is the shared generation browser: concurrent channel
        # batches bound it through generation slots instead of one exclusive lock.
        if selected == "legacy":
            stack.enter_context(store.generation_slots())
        else:
            stack.enter_context(store.profile_lock(selected))
        if args.upload_account and args.upload_account != selected:
            stack.enter_context(store.profile_lock(args.upload_account))
        stack.enter_context(channel_lock(args.channel))
        try:
            failures = run_batch(args.count, args.parallel, upload_cdp or None, start_date,
                                 args.topic or None, args.upload_parallel)
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
    community_parser.add_argument("--channel", choices=sorted(channels.CHANNELS), default="")
    community_parser.add_argument("--topic", action="append", default=[])
    community_parser.add_argument("--dry-run", action="store_true")
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
    shorts.add_argument("--visual-mode", choices=("static", "ai-video"), default=None)
    shorts.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    shorts.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    shorts.add_argument("--max-credits", type=float, default=None)
    shorts.add_argument("--max-scenes", type=int, default=None)
    shorts.add_argument("--no-static-fallback", action="store_true")
    shorts.add_argument("--dry-run", action="store_true")
    shorts.set_defaults(func=command_shorts)
    distribute_shorts = sub.add_parser(
        "distribute-shorts",
        help="spread Shorts over the channels that use them")
    distribute_shorts.add_argument("--count", type=int, default=10)
    distribute_shorts.add_argument("--dry-run", action="store_true")
    distribute_shorts.add_argument("--visual-mode", choices=("static", "ai-video"), default=None)
    distribute_shorts.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    distribute_shorts.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    distribute_shorts.set_defaults(func=command_distribute_shorts)
    faith = sub.add_parser("faith-shorts",
                           help="religious Shorts with one generated background per short")
    faith.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True,
                       help="channel profile with a Shorts queue")
    faith.add_argument("--count", type=int, default=5)
    faith.add_argument("--start-date", default=None, help="first schedule date (YYYY-MM-DD)")
    faith.add_argument("--skip-slots", type=int, default=0,
                       help="skip this many leading schedule slots")
    faith.add_argument("--start-index", type=int, default=0,
                       help="skip this many topics in the channel queue")
    faith.add_argument("--visual-mode", choices=("static", "ai-video"), default=None)
    faith.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    faith.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    faith.add_argument("--max-credits", type=float, default=None)
    faith.add_argument("--max-scenes", type=int, default=None)
    faith.add_argument("--no-static-fallback", action="store_true")
    faith.add_argument("--dry-run", action="store_true")
    faith.set_defaults(func=command_faith_shorts)
    shorts_video = sub.add_parser(
        "shorts-video",
        help="manage Shorts-only Google Flow / AI video provider settings, login and imports",
    )
    shorts_video.add_argument(
        "action",
        choices=("status", "login", "stop", "configure", "estimate", "import", "movie"),
    )
    shorts_video.add_argument("--channel", choices=sorted(channels.CHANNELS), default="zaflas")
    shorts_video.add_argument("--topic", default="")
    shorts_video.add_argument("--source-dir", default="")
    shorts_video.add_argument("--run-dir", default="")
    shorts_video.add_argument("--width", type=int, default=1920)
    shorts_video.add_argument("--height", type=int, default=1080)
    shorts_video.add_argument("--probe", action="store_true")
    shorts_video.add_argument("--enable", action="store_true")
    shorts_video.add_argument("--disable", action="store_true")
    shorts_video.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    shorts_video.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    shorts_video.add_argument("--quality", choices=("fast", "standard", "quality"), default=None)
    shorts_video.add_argument("--max-credits", type=float, default=None)
    shorts_video.add_argument("--max-credits-short", type=float, default=None)
    shorts_video.add_argument("--max-credits-batch", type=float, default=None)
    shorts_video.add_argument("--max-scenes", type=int, default=None)
    shorts_video.add_argument("--allow-paid-api", action="store_true")
    shorts_video.add_argument("--disallow-paid-api", action="store_true")
    shorts_video.add_argument("--fallback-static", action="store_true")
    shorts_video.add_argument("--no-static-fallback", action="store_true")
    shorts_video.set_defaults(func=command_shorts_video)
    clean = sub.add_parser("cleanup", help="free trash, staging and already scheduled media")
    clean.add_argument("--dry-run", action="store_true")
    clean.set_defaults(func=command_cleanup)
    comments_parser = sub.add_parser(
        "comments", help="like, heart and answer unanswered comments on the channels")
    comments_parser.add_argument("--channel", choices=sorted(channels.CHANNELS), default="")
    comments_parser.add_argument("--limit", type=int, default=25)
    comments_parser.add_argument("--dry-run", action="store_true")
    comments_parser.set_defaults(func=command_comments)
    distribute = sub.add_parser("distribute",
                                help="spread new videos over the channels with fewer scheduled")
    distribute.add_argument("--count", type=int, default=20)
    distribute.add_argument("--concurrency", type=int, default=2,
                            help="channels produced at once (1 = sequential)")
    distribute.add_argument("--dry-run", action="store_true")
    distribute.set_defaults(func=command_distribute)
    reschedule = sub.add_parser(
        "reschedule",
        help="move already-scheduled future videos to the channel's current slots")
    reschedule.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    reschedule.add_argument("--dry-run", action="store_true")
    reschedule.add_argument("--enforce-interval", action="store_true",
                            help="re-space every future video on the channel's interval_days cadence")
    reschedule.set_defaults(func=command_reschedule)
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
    run.add_argument("--upload-parallel", type=int, default=2,
                     help="concurrent Studio upload tabs; 1 keeps the sequential path")
    run.add_argument("--flow-profile", choices=flow_profiles.NAMES, default=None,
                     help="ASR/render execution profile (or YTBOT_FLOW_PROFILE; default standard)")
    run.set_defaults(func=command_run)
    from .account_commands import add_parser
    add_parser(sub)
    from .social.commands import add_parser as add_social_parser
    add_social_parser(sub)
    from .commercial.commands import add_parser as add_commercial_parser
    add_commercial_parser(sub)
    from .documentary_commands import add_parser as add_documentary_parser
    add_documentary_parser(sub)
    return parser


def main() -> None:
    config.configure_timezone()
    args = build_parser().parse_args()
    args.func(args)
