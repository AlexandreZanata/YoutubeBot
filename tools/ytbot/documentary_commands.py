"""Deterministic, resumable CLI pipeline for documentary channels (Bathylora & Sepia Atlas).

Exposes six simple, bounded subcommands under ``python3 -m tools.ytbot documentary``:
  init    -> create run folder with starter scenes.json and metadata.json templates
  collect -> download verified public-domain / CC-BY photographs + credits.md
  audit   -> hard gate checking script format, length and narration-to-image alignment
  narrate -> capture Cove Read aloud audio (legacy profile) and render 0.9x track
  render  -> align timeline, render 0.9x video (voice filter + analog tone + 1.2s xfade),
             thumbnail, subtitles.srt and metadata.txt
  qc      -> verify ffprobe, broadcast LUFS loudness, assets, 4 QC frames and PACKAGE.md

Never uploads, schedules or publishes automatically.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from . import channels, config, documentary, logic

DOC_CHANNELS = ("bathylora", "sepia-atlas")
NOAA_DISCLAIMER = (
    "Bathylora is an independent educational channel and is not affiliated "
    "with NOAA or other research institutions."
)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "episode"


def _run_dir(channel_slug: str, run_slug: str) -> Path:
    channels.apply(channel_slug)
    return config.RUNS / run_slug


def _write_srt(article: str, total_dur: float, destination: Path) -> int:
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", article.strip()))
        if s.strip()
    ]
    cues: list[str] = []
    for sent in sentences:
        words = sent.split()
        while len(words) > 16:
            cues.append(" ".join(words[:13]))
            words = words[13:]
        if words:
            cues.append(" ".join(words))
    total_words = max(sum(len(c.split()) for c in cues), 1)

    def _ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    cursor = 0
    for idx, cue in enumerate(cues, 1):
        wc = len(cue.split())
        t0 = total_dur * cursor / total_words
        cursor += wc
        t1 = total_dur * cursor / total_words
        lines.append(f"{idx}\n{_ts(t0)} --> {_ts(t1)}\n{cue}\n")
    destination.write_text("\n".join(lines), encoding="utf-8")
    return len(cues)


def _check_script_alignment(article: str, sources: list[dict], duration: float) -> tuple[list[dict], list[str], float]:
    rows = documentary.timeline_aligned(article, duration, sources, min_seconds=8.0, max_seconds=55.0)
    words = article.split()
    total = max(len(words), 1)
    lowered = [w.strip(".,;:!?\"'()[]").lower() for w in words]
    matched = 0
    report_lines = []
    for idx, row in enumerate(rows):
        w0 = int(row["start"] / max(duration, 0.01) * total)
        w1 = max(w0 + 1, int(row["end"] / max(duration, 0.01) * total))
        window_tokens = lowered[max(0, w0 - 8):min(total, w1 + 8)]
        kws = documentary._keywords(row.get("caption", ""))
        hit = any(
            kw == tok or (len(kw) > 5 and kw in tok) or (len(tok) > 5 and tok in kw)
            for kw in kws for tok in window_tokens if tok
        )
        if hit or idx == 0:
            matched += 1
        flag = "OK" if (hit or idx == 0) else "CHECK"
        snippet = " ".join(words[w0:min(w0 + 12, w1)])
        report_lines.append(
            f"[{idx + 1:02d}] {flag:5s} {row['start']:6.1f}-{row['end']:6.1f}s "
            f"| {row.get('caption', '')[:38]:38s} || {snippet}"
        )
    ratio = matched / max(len(rows), 1)
    return rows, report_lines, ratio


def cmd_init(args) -> None:
    slug = args.run or _slugify(args.title)
    run_dir = _run_dir(args.channel, slug)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "topic.txt").write_text(args.title.strip() + "\n", encoding="utf-8")

    scenes_path = run_dir / "scenes.json"
    if not scenes_path.is_file():
        starter = [
            {
                "subject": "Opening scene concrete visual description matching the narration",
                "species": "Species or main subject",
                "expedition": "NOAA Ocean Exploration" if args.channel == "bathylora" else "Archive collection",
                "place": "Specific location",
                "depth": "Depth in meters (if ocean)" if args.channel == "bathylora" else "",
                "queries": ["Primary archive search query", "Backup archive search query"],
            }
        ]
        scenes_path.write_text(json.dumps(starter, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    meta_path = run_dir / "metadata.json"
    if not meta_path.is_file():
        hashtags = (
            "#deepsea #oceanexploration #marinebiology #oceandocumentary #bathylora #science"
            if args.channel == "bathylora"
            else "#history #documentary #archivalphotography #historicalphotos #sepiaatlas"
        )
        disclaimer = f"\n\n{NOAA_DISCLAIMER}" if args.channel == "bathylora" else ""
        starter_meta = {
            "title": args.title.strip(),
            "title_options": [args.title.strip(), "Alternative Factual Title 2", "Alternative Factual Title 3"],
            "description": (
                f"Replace with a 120-180 word English summary of the real verified subjects in "
                f"{args.title.strip()}.{disclaimer}\n\n{hashtags}"
            ),
            "hashtags": hashtags,
            "tags": ["deep sea documentary", "ocean exploration", "marine biology", "Bathylora"]
            if args.channel == "bathylora"
            else ["history", "documentary", "archival photography", "Sepia Atlas"],
            "scientific_references": [],
            "playlists": ["Ocean Expeditions", "Creatures of the Deep"] if args.channel == "bathylora" else [],
        }
        meta_path.write_text(json.dumps(starter_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[doc] initialized run: {run_dir}")
    print(f"[doc] 1. Fill 30-50 concrete scenes in: {scenes_path}")
    print(f"[doc] 2. Next command: python3 -m tools.ytbot documentary collect --channel {args.channel} --run {slug}")


def cmd_collect(args) -> None:
    run_dir = _run_dir(args.channel, args.run)
    scenes_path = Path(args.scenes) if args.scenes else (run_dir / "scenes.json")
    if not scenes_path.is_file():
        raise SystemExit(f"missing scenes file: {scenes_path}")
    scenes = json.loads(scenes_path.read_text(encoding="utf-8"))
    if args.channel == "bathylora":
        sources = documentary.collect_ocean(run_dir, scenes, resume=not args.no_resume)
    else:
        sources = documentary.collect(run_dir, scenes)
        documentary.write_credits(run_dir, sources, heading="Sepia Atlas — Image Credits & Archival Sources")
    print(f"\n[doc] collected {len(sources)} / {len(scenes)} verified photographs:")
    for item in sources:
        desc = (item.get("original_description") or "")[:100]
        print(f"  [{item.get('id')}] {item.get('resolution', ''):9s} | {item.get('license', ''):13s} "
              f"| {item.get('title', '')[:42]:42s} || {desc}")
    if len(sources) < args.min_photos:
        raise SystemExit(f"only {len(sources)} photos collected (minimum required: {args.min_photos}); add better queries in scenes.json and re-run collect")
    print("\n[doc] AUDIT EVERY DESCRIPTION ABOVE before writing article.txt.")
    print(f"[doc] Next command after writing article.txt: python3 -m tools.ytbot documentary audit --channel {args.channel} --run {args.run}")


def cmd_audit(args) -> None:
    run_dir = _run_dir(args.channel, args.run)
    article_path = run_dir / "article.txt"
    sources_path = run_dir / "sources.json"
    if not article_path.is_file():
        raise SystemExit(f"missing {article_path}")
    if not sources_path.is_file():
        raise SystemExit(f"missing {sources_path}; run collect first")

    article = article_path.read_text(encoding="utf-8").strip()
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if re.search(r"(?m)^\s*(#{1,6}\s|[-*]\s|\d+\.\s)", article):
        errors.append("article.txt contains markdown headings or bullet/numbered lists (must be pure spoken prose)")
    if "http://" in article or "https://" in article:
        errors.append("article.txt contains URLs (must be pure spoken narration)")

    words = article.split()
    wc = len(words)
    est_min = wc / 127.0
    if not args.allow_length and (wc < 1700 or wc > 5200):
        errors.append(f"word count {wc} (~{est_min:.1f} min at 0.9x) is outside allowed 1,700-5,200 word range (target 1,900-3,200 / 15-25 min, max 40 min)")

    est_dur = wc / 127.0 * 60.0
    _, report_lines, ratio = _check_script_alignment(article, sources, est_dur)
    print(f"[doc] article: {wc} words ({len(article)} chars), estimated {est_min:.1f} min at 0.9x")
    print(f"[doc] alignment match rate: {ratio * 100:.1f}% across {len(sources)} photos")
    for line in report_lines:
        print(" ", line)
    if ratio < args.min_match:
        errors.append(f"narration-to-image alignment is {ratio * 100:.1f}% (< {args.min_match * 100:.0f}%); update article.txt or sources.json so every photo matches what is spoken")

    if errors:
        print("\n[doc] AUDIT FAILED:")
        for err in errors:
            print("  -", err)
        raise SystemExit(1)

    shutil.copy2(article_path, run_dir / "article.md")
    print("\n[doc] AUDIT PASSED.")
    print(f"[doc] Next command: python3 -m tools.ytbot documentary narrate --channel {args.channel} --run {args.run}")


def cmd_narrate(args) -> None:
    run_dir = _run_dir(args.channel, args.run)
    article_path = run_dir / "article.txt"
    if not article_path.is_file():
        raise SystemExit(f"missing {article_path}; write article.txt and run audit first")

    raw_audio = run_dir / "narration.aac"
    if not raw_audio.is_file() or raw_audio.stat().st_size < 10000:
        from playwright.sync_api import sync_playwright
        from . import chat, runtime
        from .accounts_store import AccountStore

        article = article_path.read_text(encoding="utf-8").strip()
        AccountStore().activate("legacy")
        runtime.start_hidden_chrome()
        with sync_playwright() as pw:
            browser, context = runtime.connect_hidden(pw)
            runtime.configure_downloads(browser)
            runtime.configure_extension(context)
            page = context.new_page()
            try:
                page.goto("https://chatgpt.com/", timeout=90000)
                page.wait_for_timeout(5000)
                prompt = (
                    "Repeat the following English documentary narration verbatim, word for word, "
                    "from the first word to the last word. Do not add any introduction, headings, "
                    "notes, or closing remarks. Output only the narration text itself:\n\n"
                    + article
                )
                chat.send_text(page, prompt)
                print("[doc] prompt sent to ChatGPT; waiting for full response...", flush=True)
                chat.wait_for_assistant(page, timeout=900)
                spoken = chat.extract_assistant_text(page)
                if len(spoken) >= int(len(article) * 0.85):
                    article_path.write_text(spoken + "\n", encoding="utf-8")
                    (run_dir / "article.md").write_text(spoken + "\n", encoding="utf-8")
                logic.set_run_field(run_dir, conversation=page.url)
                chat.capture_audio(page, context, run_dir, timeout=1800)
            finally:
                page.close()
    else:
        print(f"[doc] reusing existing {raw_audio.name} ({raw_audio.stat().st_size:,} bytes)")

    narration_90x = documentary.slow_narration(run_dir, factor=0.9)
    dur = documentary.exact_duration(narration_90x)
    print(f"[doc] narration-90x.aac ready: {dur:.2f}s ({dur / 60:.2f} min)")
    print(f"[doc] Next command: python3 -m tools.ytbot documentary render --channel {args.channel} --run {args.run} --thumb-photo 001 --thumb-title \"YOUR TITLE\"")


def cmd_render(args) -> None:
    run_dir = _run_dir(args.channel, args.run)
    article_path = run_dir / "article.txt"
    sources_path = run_dir / "sources.json"
    narration_90x = run_dir / "narration-90x.aac"
    if not narration_90x.is_file():
        if (run_dir / "narration.aac").is_file():
            narration_90x = documentary.slow_narration(run_dir, factor=0.9)
        else:
            raise SystemExit(f"missing {narration_90x}; run narrate first")

    article = article_path.read_text(encoding="utf-8").strip()
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    dur = documentary.exact_duration(narration_90x)
    rows = documentary.timeline_aligned(article, dur, sources, min_seconds=8.0, max_seconds=55.0)
    (run_dir / "timeline-09x.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "timeline.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # Subtitles
    cues = _write_srt(article, dur, run_dir / "subtitles.srt")
    print(f"[doc] subtitles.srt written ({cues} cues)")

    # Thumbnail
    thumb_style = "abyssal" if args.channel == "bathylora" else "sepia"
    photo_path = None
    if args.thumb_photo:
        cand = run_dir / "photos" / f"{args.thumb_photo}.jpg"
        photo_path = cand if cand.is_file() else Path(args.thumb_photo)
    elif sources:
        photo_path = Path(sources[0]["file"])
    if photo_path and photo_path.is_file():
        thumb_title = (args.thumb_title or (run_dir / "topic.txt").read_text(encoding="utf-8").strip()[:24]).replace("\\n", "\n")
        documentary.thumbnail(
            run_dir, photo_path, thumb_title, style=thumb_style,
            template=args.thumb_template, output_name="thumbnail.png",
        )
        print(f"[doc] thumbnail.png rendered ({thumb_style}/{args.thumb_template})")

    # Metadata.txt sync (enforce NOAA disclaimer for Bathylora)
    meta_path = run_dir / "metadata.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if args.channel == "bathylora" and NOAA_DISCLAIMER not in meta.get("description", ""):
            meta["description"] = meta.get("description", "").rstrip() + f"\n\n{NOAA_DISCLAIMER}"
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        documentary.apply_description_chapters(run_dir, rows, args.channel)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        opts = meta.get("title_options") or [meta.get("title", "")]
        txt = [
            "TITLE OPTIONS:",
            *(f"{i}. {t}" for i, t in enumerate(opts, 1)),
            "",
            "DESCRIPTION:",
            meta.get("description", ""),
            "",
            "TAGS: " + ", ".join(meta.get("tags") or []),
        ]
        (run_dir / "metadata.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")

    # Always render with locked standards: 0.9x, broadcast voice filter, subtle analog texture, 1.2s xfade
    out = documentary.render(
        run_dir, rows, narration=narration_90x, output_name="video-09x.mp4",
        crossfade=1.2, analog_texture=True, voice_filter=True,
    )
    shutil.copy2(out, run_dir / "video.mp4")
    print(f"[doc] rendered {out} and video.mp4")
    print(f"[doc] Next command: python3 -m tools.ytbot documentary qc --channel {args.channel} --run {args.run}")


def cmd_qc(args) -> None:
    run_dir = _run_dir(args.channel, args.run)
    video = run_dir / "video-09x.mp4"
    errors: list[str] = []
    for req in ("video-09x.mp4", "article.txt", "narration-90x.aac", "sources.json",
                "credits.md", "timeline-09x.json", "thumbnail.png", "metadata.json", "subtitles.srt"):
        if not (run_dir / req).is_file():
            errors.append(f"missing required deliverable: {req}")
    if errors:
        for e in errors:
            print("[qc] FAIL:", e)
        raise SystemExit(1)

    # ffprobe verification
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json", str(video),
    ], text=True))
    dur = float(probe["format"]["duration"])
    size_mb = int(probe["format"]["size"]) / (1024 * 1024)
    vstream = next((s for s in probe["streams"] if s.get("codec_type") == "video"), {})
    astream = next((s for s in probe["streams"] if s.get("codec_type") == "audio"), {})
    if vstream.get("width") != 1920 or vstream.get("height") != 1080:
        errors.append(f"video resolution is {vstream.get('width')}x{vstream.get('height')}, expected 1920x1080")
    if not astream:
        errors.append("missing audio stream")
    if (dur < args.min_minutes * 60 or dur > 42 * 60) and not args.allow_length:
        errors.append(f"duration {dur / 60:.1f} min outside allowed {args.min_minutes}-42 min bounds")

    # Loudness check (up to 180s sample)
    sample_sec = min(180, int(dur))
    loud = subprocess.run(
        ["ffmpeg", "-hide_banner", "-t", str(sample_sec), "-i", str(video),
         "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    i_match = re.findall(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", loud.stderr, re.M)
    p_match = re.findall(r"^\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", loud.stderr, re.M)
    lufs = float(i_match[-1]) if i_match else -99.0
    peak = float(p_match[-1]) if p_match else 0.0
    if not (-19.0 <= lufs <= -13.0):
        errors.append(f"audio loudness {lufs:.1f} LUFS outside broadcast range (-19 to -13 LUFS)")
    if peak >= 0.0:
        errors.append(f"audio true peak {peak:.1f} dBFS is clipping (>= 0.0 dBFS)")

    # Thumbnail & metadata & sources checks
    with Image.open(run_dir / "thumbnail.png") as thumb:
        if thumb.size != (1280, 720):
            errors.append(f"thumbnail size is {thumb.size}, expected (1280, 720)")
    sources = json.loads((run_dir / "sources.json").read_text(encoding="utf-8"))
    real_sources = [s for s in sources if not s.get("generated")]
    if any(not s.get("license") or not s.get("source_page") for s in real_sources):
        errors.append("one or more sources.json records are missing license or source_page")
    meta = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    if args.channel == "bathylora" and "not affiliated with NOAA" not in meta.get("description", ""):
        errors.append("metadata.json description is missing mandatory NOAA non-affiliation disclaimer")

    # Extract 4 visual QC frames into run_dir/qc/
    qc_dir = run_dir / "qc"
    qc_dir.mkdir(exist_ok=True)
    frame_times = [min(15, max(1, int(dur * 0.05))), int(dur * 0.25), int(dur * 0.60), int(dur * 0.90)]
    for idx, ts in enumerate(frame_times, 1):
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", str(ts), "-i", str(video),
            "-frames:v", "1", "-q:v", "3", str(qc_dir / f"frame-{idx}-{ts:04d}s.jpg"),
        ], check=True)

    print(f"[qc] video: {vstream.get('width')}x{vstream.get('height')}, {dur / 60:.2f} min ({dur:.1f}s), {size_mb:.1f} MiB")
    print(f"[qc] audio: {lufs:.1f} LUFS, True Peak {peak:.1f} dBFS")
    print(f"[qc] sources: {len(sources)} verified records | QC frames saved in: {qc_dir}")

    if errors:
        print("\n[qc] QUALITY CONTROL FAILED:")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)

    print("\n[qc] ALL AUTOMATED CHECKS PASSED.")
    print("[qc] Inspect the 4 frames in qc/ and thumbnail.png visually, then STOP and present to the owner.")
    print("[qc] NEVER upload, schedule or publish without explicit owner approval.")


def add_parser(subparsers) -> None:
    doc = subparsers.add_parser(
        "documentary",
        help="step-by-step documentary pipeline for Bathylora and Sepia Atlas (never auto-publishes)",
    )
    doc_sub = doc.add_subparsers(dest="doc_command", required=True)

    p_init = doc_sub.add_parser("init", help="create episode folder with scenes.json and metadata.json templates")
    p_init.add_argument("--channel", choices=DOC_CHANNELS, required=True)
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--run", default="")
    p_init.set_defaults(func=cmd_init)

    p_col = doc_sub.add_parser("collect", help="collect verified scientific/archival photographs and credits.md")
    p_col.add_argument("--channel", choices=DOC_CHANNELS, required=True)
    p_col.add_argument("--run", required=True)
    p_col.add_argument("--scenes", default="")
    p_col.add_argument("--min-photos", type=int, default=20)
    p_col.add_argument("--no-resume", action="store_true")
    p_col.set_defaults(func=cmd_collect)

    p_aud = doc_sub.add_parser("audit", help="verify script length, prose rules and narration-to-image alignment")
    p_aud.add_argument("--channel", choices=DOC_CHANNELS, required=True)
    p_aud.add_argument("--run", required=True)
    p_aud.add_argument("--min-match", type=float, default=0.80)
    p_aud.add_argument("--allow-length", action="store_true")
    p_aud.set_defaults(func=cmd_audit)

    p_nar = doc_sub.add_parser("narrate", help="capture Cove Read aloud narration.aac (legacy) and render 0.9x track")
    p_nar.add_argument("--channel", choices=DOC_CHANNELS, required=True)
    p_nar.add_argument("--run", required=True)
    p_nar.set_defaults(func=cmd_narrate)

    p_ren = doc_sub.add_parser("render", help="render 0.9x video (voice filter + analog tone + 1.2s xfade), thumbnail and SRT")
    p_ren.add_argument("--channel", choices=DOC_CHANNELS, required=True)
    p_ren.add_argument("--run", required=True)
    p_ren.add_argument("--thumb-photo", default="", help="photo ID (e.g. 012) or path")
    p_ren.add_argument("--thumb-title", default="", help="short 2-4 word title (use \\n for 2 lines)")
    p_ren.add_argument("--thumb-template", choices=("encounter", "discovery", "unknown"), default="encounter")
    p_ren.set_defaults(func=cmd_render)

    p_qc = doc_sub.add_parser("qc", help="run automated quality checks and extract 4 visual QC frames")
    p_qc.add_argument("--channel", choices=DOC_CHANNELS, required=True)
    p_qc.add_argument("--run", required=True)
    p_qc.add_argument("--min-minutes", type=float, default=14.0)
    p_qc.add_argument("--allow-length", action="store_true",
                      help="owner override: accept a duration outside the 14-42 min bounds")
    p_qc.set_defaults(func=cmd_qc)
