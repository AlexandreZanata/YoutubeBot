"""Channel metadata and thumbnail generation."""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import codex_media, config, logic
from .chat import copy_last, dismiss_notice, log, send_text, wait_for_assistant


def article_excerpt(run_dir: Path, limit: int = 8000) -> str:
    script = run_dir / "article.txt"
    if not script.is_file():
        script = run_dir / "short.txt"
    return script.read_text(encoding="utf-8")[:limit]


def generate_metadata(context, run_dir: Path, topic: str) -> dict:
    if codex_media.available():
        try:
            return codex_media.generate_metadata(run_dir, topic)
        except Exception as error:
            log(f"Codex metadata failed ({error}); using ChatGPT web")
    page = context.new_page()
    try:
        page.goto("https://chatgpt.com/", timeout=90000)
        page.wait_for_timeout(7000)
        dismiss_notice(page)
        request = (config.prompt("metadata.txt") + "\n\nStory topic: " + topic
                   + "\n\nARTICLE (excerpt, included below):\n" + article_excerpt(run_dir))
        send_text(page, request)
        log(f"metadata prompt sent: {topic}")
        wait_for_assistant(page)
        raw = copy_last(page).strip()
        (run_dir / "metadata.txt").write_text(raw, encoding="utf-8")
        parsed = logic.parse_metadata(raw)
        (run_dir / "metadata.json").write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"metadata saved: title={parsed['title']!r}")
        return parsed
    finally:
        page.close()


def image_data_url(page) -> str | None:
    return page.evaluate(
        """async () => {
          const imgs = [...document.querySelectorAll('img')].filter(
            (i) => i.naturalWidth >= 400 && i.naturalHeight >= 200);
          if (!imgs.length) return null;
          const img = imgs[imgs.length - 1];
          try {
            const resp = await fetch(img.src);
            const blob = await resp.blob();
            return await new Promise((resolve) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result);
              reader.readAsDataURL(blob);
            });
          } catch (error) { return null; }
        }"""
    )


def generate_thumbnail(context, run_dir: Path, style: str = "dense", timeout: int = 1200,
                       variation: str = "") -> Path | None:
    if codex_media.available():
        for attempt in range(2):
            try:
                return codex_media.generate_thumbnail(run_dir, style, variation)
            except Exception as error:
                log(f"Codex thumbnail failed ({error}); trying ChatGPT web after this attempt")
                if attempt:
                    break
                stale = run_dir / "thumbnail.png"
                if stale.is_file():
                    stale.rename(run_dir / f"thumbnail-attempt-{int(time.time())}.png")
                state = run_dir / ".codex-media" / "thumbnail"
                if state.is_dir():
                    state.rename(state.with_name(f"thumbnail-attempt-{int(time.time())}"))
    page = context.new_page()
    try:
        page.goto("https://chatgpt.com/", timeout=90000)
        page.wait_for_timeout(7000)
        dismiss_notice(page)
        prompt_file = {"classic": "thumbnail-classic.txt",
                       "shorts": "thumbnail-shorts.txt",
                       "short-background": "shorts_background.txt"}.get(style, "thumbnail.txt")
        topic_path = run_dir / "topic.txt"
        topic = topic_path.read_text(encoding="utf-8").strip() if topic_path.is_file() else ""
        identity = config.prompt(prompt_file)
        # The web image tool fails on the full Zaflas/Whispers briefs; their identity
        # is front-loaded, so the browser path keeps the leading sections only.
        if len(identity) > 4000:
            identity = identity[:4000].rsplit("\n\n", 1)[0]
        subject = (topic + "\n\nShow this story's own subject, place and moment. Do not reuse "
                   "a character, setting or composition from another video.")
        request = (subject
                   + "\n\n" + identity
                   + ("\n\n" + variation if variation else "")
                   + "\n\nGenerate the final image now and reply only after it exists.")
        send_text(page, request)
        log("thumbnail prompt sent")
        deadline = time.time() + timeout
        while time.time() < deadline:
            page.wait_for_timeout(5000)
            data = image_data_url(page)
            if data and data.startswith("data:image/"):
                destination = run_dir / "thumbnail.png"
                with Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1]))) as master:
                    size = (1080, 1920) if style in ("shorts", "short-background") else (1280, 720)
                    exported = ImageOps.fit(master.convert("RGB"), size, Image.Resampling.LANCZOS)
                    exported.save(destination, format="PNG", optimize=True)
                (run_dir / "thumbnail-source.json").write_text(
                    json.dumps({"provider": "chatgpt-browser", "style": style}),
                    encoding="utf-8")
                log("thumbnail saved")
                return destination
            body = page.locator("body").inner_text()
            if "violate our content policies" in body.lower():
                (run_dir / "thumbnail-response.txt").write_text(body, encoding="utf-8")
                raise RuntimeError("ChatGPT rejected the thumbnail prompt by content policy; "
                                   "completed assets were preserved")
            if "Image generation failed" in body:
                (run_dir / "thumbnail-response.txt").write_text(body, encoding="utf-8")
                raise RuntimeError("ChatGPT image generation failed; completed assets were preserved. Supply a channel-style thumbnail before resuming this run.")
        (run_dir / "thumbnail-response.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
        raise RuntimeError("thumbnail image was not generated")
    finally:
        page.close()
