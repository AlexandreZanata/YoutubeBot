"""Version-one bounded JSON adapter for trusted local ZaturoBot worker commands."""

from __future__ import annotations
import argparse
import json
import sys
from . import channels, config, flow_profiles
from .accounts_store import AccountStore
from . import library, service_jobs


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    commands.add_parser("profiles")
    runs = commands.add_parser("runs")
    runs.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    runs.add_argument("--limit", type=int, default=20)
    submit = commands.add_parser("submit")
    submit.add_argument("--operation-id", required=True)
    submit.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    submit.add_argument("--account", required=True)
    submit.add_argument("--count", type=int, required=True)
    submit.add_argument("--approved-schedule", action="store_true")
    generate = commands.add_parser("generate")
    generate.add_argument("--operation-id", required=True)
    generate.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    generate.add_argument("--count", type=int, required=True)
    generate.add_argument("--approved-generation", action="store_true")
    for command in (submit, generate):
        command.add_argument("--flow-profile", choices=flow_profiles.NAMES, default=None)
    for verb in ["status", "_execute"]:
        command = commands.add_parser(verb)
        command.add_argument("--operation-id", required=True)
    commands.add_parser("shorts-providers")
    shorts_est = commands.add_parser("shorts-estimate")
    shorts_est.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    shorts_est.add_argument("--count", type=int, default=1)
    shorts_est.add_argument("--visual-mode", choices=("static", "ai-video"), default="ai-video")
    shorts_est.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    shorts_est.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    shorts_est.add_argument("--max-credits", type=float, default=None)
    shorts_gen = commands.add_parser("shorts-generate")
    shorts_gen.add_argument("--operation-id", required=True)
    shorts_gen.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    shorts_gen.add_argument("--count", type=int, required=True)
    shorts_gen.add_argument("--approved-generation", action="store_true")
    shorts_gen.add_argument("--visual-mode", choices=("static", "ai-video"), default="ai-video")
    shorts_gen.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    shorts_gen.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    shorts_gen.add_argument("--max-credits", type=float, default=None)
    shorts_gen.add_argument("--flow-profile", choices=flow_profiles.NAMES, default=None)
    shorts_resume = commands.add_parser("shorts-resume")
    shorts_resume.add_argument("--operation-id", required=True)
    shorts_resume.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    shorts_resume.add_argument("--run-id", required=True)
    shorts_resume.add_argument("--approved-generation", action="store_true")
    shorts_resume.add_argument("--video-provider", choices=("google-flow", "gemini-api", "manual-import"), default=None)
    shorts_resume.add_argument("--video-model", choices=("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality"), default=None)
    shorts_resume.add_argument("--max-credits", type=float, default=None)
    shorts_resume.add_argument("--flow-profile", choices=flow_profiles.NAMES, default=None)
    shorts_inspect = commands.add_parser("shorts-inspect")
    shorts_inspect.add_argument("--channel", choices=sorted(channels.CHANNELS), required=True)
    shorts_inspect.add_argument("--run-id", required=True)
    return root


def dispatch(args) -> dict | None:
    if args.command == "capabilities":
        return {
            "schema_version": 1,
            "service": "youtube",
            "max_count": 10,
            "capabilities": [
                "youtube.profiles.list",
                "youtube.runs.list",
                "youtube.batch.submit",
                "youtube.batch.generate",
                "youtube.batch.status",
                "youtube.shorts.providers",
                "youtube.shorts.estimate",
                "youtube.shorts.generate",
                "youtube.shorts.resume",
                "youtube.shorts.inspect",
            ],
        }
    if args.command == "profiles":
        return {"schema_version": 1, "profiles": library.profiles(AccountStore())}
    if args.command == "runs":
        return {
            "schema_version": 1,
            "channel": args.channel,
            "runs": library.runs(args.channel, args.limit),
        }
    if args.command == "submit":
        return service_jobs.submit(
            args.operation_id,
            args.channel,
            args.account,
            args.count,
            args.approved_schedule,
            flow_profile=flow_profiles.name(getattr(args, "flow_profile", None), environment=True),
        )
    if args.command == "generate":
        store = AccountStore()
        binding = store.load()["bindings"].get(args.channel, {})
        account = binding.get("account_id", "legacy")
        return service_jobs.submit(args.operation_id, args.channel, account, args.count, False,
                                   mode="generate", approved_generate=args.approved_generation, store=store,
                                   flow_profile=flow_profiles.name(getattr(args, "flow_profile", None), environment=True))
    if args.command == "shorts-providers":
        from .shorts_video import service_api as shorts_service
        return shorts_service.providers_status()
    if args.command == "shorts-estimate":
        from .shorts_video import service_api as shorts_service
        return shorts_service.estimate_shorts(
            args.channel,
            args.count,
            visual_mode=args.visual_mode,
            video_provider=args.video_provider,
            video_model=args.video_model,
            max_credits=args.max_credits,
        )
    if args.command == "shorts-generate":
        from .shorts_video import service_api as shorts_service
        store = AccountStore()
        binding = store.load()["bindings"].get(args.channel, {})
        account = binding.get("account_id", "legacy")
        shorts_options = {
            "visual_mode": args.visual_mode,
            "video_provider": args.video_provider,
            "video_model": args.video_model,
            "max_credits": args.max_credits,
        }
        return service_jobs.submit(
            args.operation_id,
            args.channel,
            account,
            args.count,
            False,
            mode="shorts_generate",
            approved_generate=args.approved_generation,
            shorts_options=shorts_options,
            store=store,
            flow_profile=flow_profiles.name(getattr(args, "flow_profile", None), environment=True),
        )
    if args.command == "shorts-resume":
        from .shorts_video import service_api as shorts_service
        run_id = shorts_service.validate_run_id(args.run_id)
        store = AccountStore()
        binding = store.load()["bindings"].get(args.channel, {})
        account = binding.get("account_id", "legacy")
        shorts_options = {
            "run_id": run_id,
            "visual_mode": "ai-video",
            "video_provider": args.video_provider,
            "video_model": args.video_model,
            "max_credits": args.max_credits,
        }
        return service_jobs.submit(
            args.operation_id,
            args.channel,
            account,
            1,
            False,
            mode="shorts_resume",
            approved_generate=args.approved_generation,
            shorts_options=shorts_options,
            store=store,
            flow_profile=flow_profiles.name(getattr(args, "flow_profile", None), environment=True),
        )
    if args.command == "shorts-inspect":
        from .shorts_video import service_api as shorts_service
        return shorts_service.inspect_short_run(args.channel, args.run_id)
    if args.command == "status":
        return service_jobs.status(args.operation_id)
    if args.command == "_execute":
        service_jobs.execute(args.operation_id)
        return None
    raise ValueError("unknown command")


def main() -> int:
    config.configure_timezone()
    args = parser().parse_args()
    try:
        result = dispatch(args)
        if result is not None:
            output = json.dumps(result, ensure_ascii=False)
            if len(output.encode()) > 65536:
                raise ValueError("adapter response exceeds its output limit")
            print(output)
        return 0
    except service_jobs.CapacityReached:
        print(json.dumps({"schema_version": 1, "error": "capacity_reached"}))
        return 1
    except Exception:
        # Never serialize arbitrary provider/browser exceptions, credentials or local paths.
        print(json.dumps({"schema_version": 1, "error": "operation_rejected"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
