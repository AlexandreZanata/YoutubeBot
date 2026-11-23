"""Isolated Google Flow browser runtime, manual login and readiness inspection."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import browser_install, config, runtime
from ..accounts_store import private_directory, read_private, write_private

FLOW_URL = "https://labs.google/fx/tools/flow"
FLOW_HOSTS = ("labs.google", "flow.google")
FLOW_CDP_PORT = 9345
FLOW_DISPLAY = ":94"


def log(message: str) -> None:
    print(f"[flow-browser] {message}", flush=True)


class FlowStore:
    """Private state and browser profile dedicated exclusively to Google Flow."""

    def __init__(self, root: Path | None = None):
        self.root = private_directory(
            root or (config.ROOT / ".local" / "video-providers" / "google-flow")
        )

    @property
    def profile(self) -> Path:
        return private_directory(self.root / "profile")

    @property
    def account_path(self) -> Path:
        return self.root / "account.json"

    @property
    def pid_path(self) -> Path:
        return self.root / "browser.pid"

    @property
    def xvfb_pid_path(self) -> Path:
        return self.root / "xvfb.pid"

    def imports_dir(self, run_slug: str | None = None) -> Path:
        base = private_directory(self.root / "imports")
        if run_slug:
            return private_directory(base / run_slug)
        return base

    def read_account(self) -> dict[str, Any] | None:
        return read_private(self.account_path)

    def save_account(
        self,
        *,
        state: str,
        credits_reported: float | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "provider": "google-flow",
            "state": state,
            "credits_reported": credits_reported,
            "detail": str(detail)[:240],
            "verified_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_private(self.account_path, record)
        return record


def cdp_alive(port: int = FLOW_CDP_PORT, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=timeout
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _pid_data(store: FlowStore) -> dict[str, Any]:
    try:
        return json.loads(store.pid_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _running_pid(store: FlowStore) -> int | None:
    pid = int(_pid_data(store).get("pid", 0) or 0)
    if not pid:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def current_mode(store: FlowStore) -> str:
    data = _pid_data(store)
    port = int(data.get("port", 0) or 0)
    if not port or not cdp_alive(port):
        return "closed"
    return str(data.get("mode", "visible"))


def stop_flow_browser(store: FlowStore | None = None) -> None:
    store = store or FlowStore()
    pid = _running_pid(store)
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.5)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    store.pid_path.unlink(missing_ok=True)


def open_visible_login(store: FlowStore | None = None, url: str = FLOW_URL) -> int:
    """Open one visible dedicated browser window for owner login on Google Flow."""
    store = store or FlowStore()
    if cdp_alive(FLOW_CDP_PORT):
        if current_mode(store) == "hidden":
            stop_flow_browser(store)
        else:
            log(f"Google Flow visible browser is already open on port {FLOW_CDP_PORT}")
            return 0
    if _running_pid(store):
        raise RuntimeError(
            "the Google Flow browser is already running without a debug port; close it and retry"
        )
    profile = store.profile
    binary = browser_install.executable()
    command = [
        binary,
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        f"--remote-debugging-port={FLOW_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--window-position=120,80",
        "--window-size=1400,950",
        "--new-window",
        url,
    ]
    process = subprocess.Popen(
        command,
        env=browser_install.environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    write_private(
        store.pid_path,
        {
            "pid": process.pid,
            "port": FLOW_CDP_PORT,
            "mode": "visible",
            "started_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the Google Flow browser exited before opening")
        if cdp_alive(FLOW_CDP_PORT):
            store.save_account(state="login_pending", detail="Manual Google Flow login opened")
            log(f"Google Flow login browser ready on port {FLOW_CDP_PORT}")
            return process.pid
        time.sleep(0.5)
    raise RuntimeError("the Google Flow browser did not expose a debug port in time")


def _display_alive(display: str) -> bool:
    return Path(f"/tmp/.X11-unix/X{display.lstrip(':')}").exists()


def _start_display(store: FlowStore, display: str) -> None:
    if _display_alive(display):
        return
    log_path = store.root / "xvfb.log"
    with log_path.open("ab") as output:
        process = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Xvfb exited before the Google Flow display was ready")
        if _display_alive(display):
            write_private(store.xvfb_pid_path, {"pid": process.pid, "display": display})
            return
        time.sleep(0.2)
    raise RuntimeError("the Google Flow Xvfb display did not start in time")


def ensure_hidden_flow_browser(
    store: FlowStore | None = None,
    url: str = FLOW_URL,
    display: str = FLOW_DISPLAY,
) -> int:
    store = store or FlowStore()
    if cdp_alive(FLOW_CDP_PORT) and current_mode(store) == "hidden":
        return 0
    if cdp_alive(FLOW_CDP_PORT):
        stop_flow_browser(store)
    if _running_pid(store):
        raise RuntimeError(
            "the Google Flow browser is still running without a debug port; close it and retry"
        )
    _start_display(store, display)
    binary = browser_install.executable()
    environment = browser_install.environment()
    environment["DISPLAY"] = display
    environment.pop("WAYLAND_DISPLAY", None)
    command = [
        binary,
        f"--user-data-dir={store.profile}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--ozone-platform=x11",
        f"--remote-debugging-port={FLOW_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--window-position=0,0",
        "--window-size=1600,1000",
        "--new-window",
        url,
    ]
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    write_private(
        store.pid_path,
        {
            "pid": process.pid,
            "port": FLOW_CDP_PORT,
            "mode": "hidden",
            "display": display,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the hidden Google Flow browser exited before opening")
        if cdp_alive(FLOW_CDP_PORT):
            return process.pid
        time.sleep(0.5)
    raise RuntimeError("the hidden Google Flow browser did not expose a debug port in time")


def _visible(page, selector: str) -> bool:
    try:
        return bool(page.locator(selector).first.is_visible(timeout=800))
    except Exception:
        return False


def _body_text(page) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=1500) or "")
    except Exception:
        return ""


def inspect_flow_page(page) -> dict[str, Any]:
    """Read-only inspection of the Google Flow page state without bypassing checks."""
    raw_url = str(getattr(page, "url", "") or "")
    parsed = urlsplit(raw_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if (
        host == "accounts.google.com"
        or _visible(page, 'input[type="email"], input[type="password"]')
    ):
        return {"state": "login_required", "credits_reported": None}

    body = _body_text(page)
    lower_body = body.lower()
    if (
        "sorry/index" in path
        or "verify you are human" in lower_body
        or "unusual traffic" in lower_body
        or _visible(page, 'iframe[src*="recaptcha"], iframe[title*="recaptcha" i]')
    ):
        return {"state": "challenge_required", "credits_reported": None}

    on_flow_host = any(host == candidate or host.endswith("." + candidate) for candidate in FLOW_HOSTS)
    if on_flow_host:
        has_sign_in = _visible(
            page,
            'a[href*="accounts.google.com"], button:has-text("Sign in"), button:has-text("Fazer login")',
        )
        if has_sign_in:
            return {"state": "login_required", "credits_reported": None}
        has_composer = _visible(
            page,
            'textarea, [contenteditable="true"], button:has-text("New project"), '
            'button:has-text("Novo projeto"), button[aria-label*="Create" i]',
        )
        credits_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:credits?|créditos?)", body, re.I)
        credits_val = float(credits_match.group(1)) if credits_match else None
        if has_composer:
            return {"state": "ready", "credits_reported": credits_val}

    return {"state": "unknown", "credits_reported": None}


def record_flow_login_needed(reason: str, store: FlowStore | None = None) -> dict[str, Any]:
    store = store or FlowStore()
    entry = runtime.record_login_request(FLOW_URL, reason, store.profile)
    store.save_account(state="login_required", detail=reason)
    return {
        "provider": "google-flow",
        "state": "login_required",
        "at": entry["at"],
        "detail": reason,
    }


def check_flow_readiness(
    store: FlowStore | None = None,
    *,
    probe_browser: bool = False,
) -> dict[str, Any]:
    """Return bounded public readiness info for Google Flow without exposing secrets."""
    if store is None and not probe_browser:
        base = config.ROOT / ".local" / "video-providers" / "google-flow"
        if not (base / "profile" / "Default").is_dir():
            return {
                "provider": "google-flow",
                "configured": False,
                "state": "not-connected",
                "credits_reported": None,
                "browser_running": cdp_alive(FLOW_CDP_PORT),
                "verified_at": "",
                "detail": "Google Flow profile is not configured. Connect Google Flow in a visible browser first.",
            }
    store = store or FlowStore()
    configured = (store.profile / "Default").is_dir()
    account = store.read_account() or {}

    if not configured:
        return {
            "provider": "google-flow",
            "configured": False,
            "state": "not-connected",
            "credits_reported": None,
            "browser_running": cdp_alive(FLOW_CDP_PORT),
            "verified_at": "",
            "detail": "Google Flow profile is not configured. Connect Google Flow in a visible browser first.",
        }

    if probe_browser:
        from playwright.sync_api import sync_playwright

        ensure_hidden_flow_browser(store)
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{FLOW_CDP_PORT}")
            context = browser.contexts[0]
            page = context.new_page()
            try:
                page.goto(FLOW_URL, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                inspection = inspect_flow_page(page)
            finally:
                page.close()
        saved = store.save_account(
            state=inspection["state"],
            credits_reported=inspection.get("credits_reported"),
            detail=f"Probed Google Flow state: {inspection['state']}",
        )
        return {
            "provider": "google-flow",
            "configured": True,
            "state": saved["state"],
            "credits_reported": saved.get("credits_reported"),
            "browser_running": True,
            "verified_at": saved.get("verified_at", ""),
            "detail": saved.get("detail", ""),
        }

    state = str(account.get("state") or "unknown")
    if state not in {"ready", "login_required", "challenge_required", "login_pending", "unknown"}:
        state = "unknown"
    return {
        "provider": "google-flow",
        "configured": True,
        "state": state,
        "credits_reported": account.get("credits_reported"),
        "browser_running": cdp_alive(FLOW_CDP_PORT),
        "verified_at": str(account.get("verified_at") or ""),
        "detail": str(account.get("detail") or "Profile present; run readiness probe or login."),
    }
