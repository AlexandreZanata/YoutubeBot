"""Visible, persistent browser per social network with a bounded CDP check."""

from __future__ import annotations

import json
import os
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


def _running_pid(store: SocialStore, network: str) -> int | None:
    try:
        data = json.loads(_pid_path(store, network).read_text(encoding="utf-8"))
        pid = int(data["pid"])
    except (OSError, ValueError, KeyError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def open_visible(store: SocialStore, network: str, url: str, port: int) -> int:
    if cdp_alive(port):
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
