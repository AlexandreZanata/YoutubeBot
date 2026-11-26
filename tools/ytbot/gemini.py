"""Gemini web generation for Shorts: script, background image and read-aloud narration.

Uses the owner's Google Flow browser profile (the same Google account signed in for
Gemini), so no API key is required. The read-aloud audio is captured from the default
PulseAudio monitor, trimmed, and encoded as AAC for the existing Shorts renderer.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import config
from .shorts_video import flow_browser

GEMINI_URL = "https://gemini.google.com/app"
CDP_PORT = flow_browser.FLOW_CDP_PORT


class GeminiUnavailableError(RuntimeError):
    """Raised when the Gemini session or the audio monitor is not available."""


def log(message: str) -> None:
    print(f"[gemini] {message}", flush=True)


def available() -> bool:
    return flow_browser.cdp_alive(CDP_PORT)


CAPTURE_SINK = "ytbot_gemini_capture"


def _ensure_capture_sink() -> str:
    """Create a private null sink so Gemini audio never mixes with ChatGPT playback."""
    listing = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True,
                             text=True, timeout=10).stdout
    if CAPTURE_SINK not in listing:
        subprocess.run(["pactl", "load-module", "module-null-sink",
                        f"sink_name={CAPTURE_SINK}",
                        f"sink_properties=device.description={CAPTURE_SINK}"],
                       capture_output=True, text=True, timeout=15, check=False)
    return f"{CAPTURE_SINK}.monitor"


def _flow_chrome_pids() -> set[str]:
    out = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True, text=True,
                         timeout=10).stdout
    return {line.split()[0] for line in out.splitlines()
            if f"--remote-debugging-port={CDP_PORT}" in line and "chrome" in line}


def _move_chrome_streams() -> list[str]:
    """Route the Gemini browser's audio streams into the private capture sink."""
    pids = _flow_chrome_pids()
    if not pids:
        return []
    listing = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True,
                             text=True, timeout=10).stdout
    moved = []
    current = None
    for line in listing.splitlines():
        line = line.strip()
        if line.startswith("Sink Input #"):
            current = line.split("#")[1]
        if current and "application.process.id" in line:
            pid = line.split("=")[-1].strip().strip('"')
            if pid in pids:
                subprocess.run(["pactl", "move-sink-input", current, CAPTURE_SINK],
                               check=False, timeout=10)
                moved.append(current)
    return moved


def _trim_audio(source: Path, destination: Path) -> Path:
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-af",
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
        "areverse",
        "-ar", "48000", "-ac", "1", "-c:a", "aac", "-b:a", "128k", str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size < 2048:
        raise GeminiUnavailableError(
            f"narration trim failed: {(result.stderr or '')[-200:]}")
    return destination


def _open_chat(page) -> None:
    page.goto(GEMINI_URL, timeout=90000)
    page.wait_for_timeout(6000)
    page.keyboard.press("Escape")


def _send(page, prompt: str) -> None:
    editor = page.locator("div.ql-editor[contenteditable=true]").first
    if not editor.count():
        raise GeminiUnavailableError("Gemini composer was not found; check the session")
    editor.click()
    page.keyboard.insert_text(prompt)
    page.wait_for_timeout(600)
    page.keyboard.press("Enter")


def _last_reply(page, timeout: int = 240) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        bubbles = page.locator("model-response, .model-response-text")
        if bubbles.count():
            text = bubbles.last.inner_text().strip()
            if text and "O Gemini é uma IA" not in text:
                return text
    raise GeminiUnavailableError("Gemini did not answer in time")


def generate_script(topic: str, language: str = "en", max_words: int = 130) -> str:
    """Ask Gemini for the Short narration in the channel language."""
    with _sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}",
                                                      timeout=60000)
        context = browser.contexts[0]
        page = context.new_page()
        try:
            _open_chat(page)
            if language == "pt-BR":
                prompt = (
                    f"Escreva uma narração de Short de até {max_words} palavras em português do "
                    f"Brasil, em segunda pessoa, com imagens concretas, sem introdução, sem "
                    f"conclusão e sem hashtags. Tema: {topic}. Responda apenas com a narração.")
            else:
                prompt = (
                    f"Write a Short narration of up to {max_words} English words, second person, "
                    f"concrete images, no intro, no summary, no hashtags. Topic: {topic}. "
                    f"Return only the narration text.")
            _send(page, prompt)
            text = _last_reply(page)
            return text
        finally:
            page.close()
            browser.close()


def generate_image(prompt: str, destination: Path) -> Path:
    """Generate one vertical 9:16 image in Gemini and save the original size."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}",
                                                      timeout=60000)
        page = browser.contexts[0].new_page()
        try:
            _open_chat(page)
            _send(page, prompt)
            deadline = time.time() + 240
            while time.time() < deadline:
                page.wait_for_timeout(4000)
                images = page.locator("img[src^='blob:']")
                if images.count():
                    images.last.hover()
                    page.wait_for_timeout(800)
                    with page.expect_download(timeout=90000) as info:
                        page.get_by_label("Baixar imagem no tamanho original").last.click()
                    info.value.save_as(destination)
                    if destination.is_file() and destination.stat().st_size > 20000:
                        return destination
                if "erro" in page.locator("body").inner_text().lower()[-500:]:
                    raise GeminiUnavailableError("Gemini image generation returned an error")
            raise GeminiUnavailableError("Gemini did not return an image in time")
        finally:
            page.close()
            browser.close()


def read_aloud(text: str, destination: Path, *, timeout: int = 600) -> Path:
    """Read the text in Gemini and capture the audio from the system monitor."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    monitor = _ensure_capture_sink()
    with _sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}",
                                                      timeout=60000)
        page = browser.contexts[0].new_page()
        raw = destination.with_suffix(".capture.wav")
        try:
            _open_chat(page)
            _send(page, "Repita exatamente este texto, sem comentários:\n\n" + text)
            _last_reply(page)
            words = max(20, len(text.split()))
            record_seconds = min(timeout, int(words / 2.1) + 25)
            recorder = subprocess.Popen(
                ["ffmpeg", "-y", "-v", "error", "-f", "pulse", "-i", monitor,
                 "-t", str(record_seconds), "-ac", "1", "-ar", "48000", str(raw)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            page.wait_for_timeout(1500)
            page.get_by_label("Mostrar mais opções").last.click()
            page.wait_for_timeout(1200)
            page.get_by_text("Ouvir", exact=True).last.click()
            page.wait_for_timeout(1500)
            _move_chrome_streams()
            recorder.wait(timeout=record_seconds + 60)
        finally:
            page.close()
            browser.close()
    if not raw.is_file() or raw.stat().st_size < 4096:
        raise GeminiUnavailableError("Gemini read-aloud audio was not captured")
    return _trim_audio(raw, destination)


def _sync_playwright():
    from playwright.sync_api import sync_playwright

    return sync_playwright()
