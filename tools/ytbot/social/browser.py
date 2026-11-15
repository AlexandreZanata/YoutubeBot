"""Visible login and hidden Xvfb browser per social network, with a bounded CDP check."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import browser_install
from ..accounts_store import write_private
from .store import SocialStore


def log(message: str) -> None:
    print(f"[social] {message}", flush=True)


def cdp_alive(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _pid_path(store: SocialStore, network: str) -> Path:
    return store.network(network) / "browser.pid"


def _pid_data(store: SocialStore, network: str) -> dict:
    try:
        return json.loads(_pid_path(store, network).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _running_pid(store: SocialStore, network: str) -> int | None:
    pid = int(_pid_data(store, network).get("pid", 0))
    if not pid:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def current_mode(store: SocialStore, network: str) -> str:
    if not cdp_alive(int(_pid_data(store, network).get("port", 0) or 0)):
        return "closed"
    return str(_pid_data(store, network).get("mode", "visible"))


def stop(store: SocialStore, network: str) -> None:
    pid = _running_pid(store, network)
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("the social browser did not stop in time")
    _pid_path(store, network).unlink(missing_ok=True)
    log(f"{network} browser stopped")


def open_visible(store: SocialStore, network: str, url: str, port: int) -> int:
    if cdp_alive(port):
        if current_mode(store, network) == "hidden":
            stop(store, network)
        else:
            log(f"{network} browser is already open on port {port}")
            return 0
    previous = _running_pid(store, network)
    if previous:
        raise RuntimeError(
            f"the {network} browser is still running without a debug port; close it and try again"
        )
    profile = store.profile(network)
    binary = browser_install.executable()
    command = [
        binary,
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        f"--remote-debugging-port={port}",
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
    write_private(_pid_path(store, network), {
        "pid": process.pid,
        "port": port,
        "mode": "visible",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the social browser exited before the login page opened")
        if cdp_alive(port):
            log(f"{network} browser ready on port {port}")
            return process.pid
        time.sleep(0.5)
    raise RuntimeError("the social browser did not expose a debug port in time; close it and retry")


def _display_alive(display: str) -> bool:
    return Path(f"/tmp/.X11-unix/X{display.lstrip(':')}").exists()


def _start_display(store: SocialStore, network: str, display: str) -> None:
    if _display_alive(display):
        return
    log_path = store.network(network) / "xvfb.log"
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
            raise RuntimeError("Xvfb exited before the hidden display was ready")
        if _display_alive(display):
            write_private(store.network(network) / "xvfb.pid",
                          {"pid": process.pid, "display": display})
            return
        time.sleep(0.2)
    raise RuntimeError("the hidden Xvfb display did not start in time")


def _launch_hidden(store: SocialStore, network: str, url: str, port: int, display: str) -> int:
    _start_display(store, network, display)
    profile = store.profile(network)
    binary = browser_install.executable()
    environment = browser_install.environment()
    environment["DISPLAY"] = display
    environment.pop("WAYLAND_DISPLAY", None)
    command = [
        binary,
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--ozone-platform=x11",
        f"--remote-debugging-port={port}",
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
    write_private(_pid_path(store, network), {
        "pid": process.pid,
        "port": port,
        "mode": "hidden",
        "display": display,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the hidden social browser exited before opening")
        if cdp_alive(port):
            log(f"{network} browser ready in background on display {display}")
            return process.pid
        time.sleep(0.5)
    raise RuntimeError("the hidden social browser did not expose a debug port in time")


def ensure_background(store: SocialStore, network: str, url: str, port: int,
                      display: str) -> int:
    if cdp_alive(port) and current_mode(store, network) == "hidden":
        return 0
    if cdp_alive(port):
        log(f"switching {network} from the visible window to the hidden runtime")
        stop(store, network)
    previous = _running_pid(store, network)
    if previous:
        raise RuntimeError(
            f"the {network} browser is still running without a debug port; close it and try again"
        )
    return _launch_hidden(store, network, url, port, display)
