#!/usr/bin/env python3
"""Capture every page of the manager in one theme on a private Xvfb display.

Drives the app only through its keyboard shortcuts (XTest through ctypes), so the capture
also exercises Ctrl+1…8, the arrows, End and Enter. Requires Xvfb and ImageMagick `import`.

    python3 desktop/scripts/demo_root.py /tmp/ytbot-demo
    python3 desktop/scripts/capture.py --root /tmp/ytbot-demo --theme light --out docs/images/desktop
    python3 desktop/scripts/capture.py --root /tmp/ytbot-demo --theme dark --out /tmp/shots \
        --size 1024x720 --only central,ficha-detail

Images are named `<shot>-<theme>.png`, with `-<width>x<height>` added for a non-default size.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

PAGES = ["central", "overview", "channels", "shorts", "social", "commercial", "sessions",
         "settings"]
DEFAULT_SIZE = (1280, 800)
SHOTS = ["keyboard-focus", *PAGES[:1], "ficha-detail", "ficha-detail-end", *PAGES[1:3], "channel-detail",
         *PAGES[3:]]


class Keyboard:
    def __init__(self, display: str) -> None:
        self.x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        self.xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XStringToKeysym.restype = ctypes.c_ulong
        self.x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.x11.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        self.display = self.x11.XOpenDisplay(display.encode())
        if not self.display:
            raise SystemExit(f"cannot open display {display}")

    def top_window(self) -> int:
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XQueryTree.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint)]
        self.x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        root = self.x11.XDefaultRootWindow(self.display)
        parent, top = ctypes.c_ulong(), ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        self.x11.XQueryTree(self.display, root, ctypes.byref(top), ctypes.byref(parent),
                            ctypes.byref(children), ctypes.byref(count))
        return children[count.value - 1] if count.value else 0

    def fill_screen(self, width: int, height: int) -> None:
        """The app opens at 1280x800; without a window manager, resize it to the screen."""
        window = self.top_window()
        if window:
            self.x11.XMoveResizeWindow(self.display, window, 0, 0, width, height)
        self.x11.XFlush(self.display)
        time.sleep(1.0)

    def focus_top_window(self) -> None:
        """Without a window manager nothing gives the app keyboard focus; give it explicitly."""
        window = self.top_window()
        if window:
            self.x11.XSetInputFocus(self.display, window, 1, 0)
        self.x11.XFlush(self.display)
        time.sleep(0.5)

    def point(self, x: int, y: int) -> None:
        self.xtst.XTestFakeMotionEvent(self.display, -1, x, y, 0)
        self.x11.XFlush(self.display)

    def press(self, combo: str) -> None:
        codes = [self.x11.XKeysymToKeycode(self.display, self.x11.XStringToKeysym(part.encode()))
                 for part in combo.split("+")]
        for code in codes:
            self.xtst.XTestFakeKeyEvent(self.display, code, 1, 0)
        for code in reversed(codes):
            self.xtst.XTestFakeKeyEvent(self.display, code, 0, 0)
        self.x11.XFlush(self.display)
        time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--theme", choices=("light", "dark"), required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--binary", type=Path,
                        default=Path(__file__).resolve().parents[1] / "target/debug/manager-app")
    parser.add_argument("--display", default=":97")
    parser.add_argument("--size", default="x".join(map(str, DEFAULT_SIZE)),
                        help="screen and window size, WIDTHxHEIGHT (the app's minimum is 1024x720)")
    parser.add_argument("--only", default="",
                        help=f"comma-separated shots to save (default: all of {', '.join(SHOTS)})")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    width, height = (int(value) for value in arguments.size.lower().split("x"))
    wanted = {name.strip() for name in arguments.only.split(",") if name.strip()} or set(SHOTS)
    unknown = wanted - set(SHOTS)
    if unknown:
        parser.error(f"unknown shots: {', '.join(sorted(unknown))}")
    suffix = "" if (width, height) == DEFAULT_SIZE else f"-{width}x{height}"

    with tempfile.TemporaryDirectory() as config:
        settings = Path(config) / "settings.json"
        settings.write_text(json.dumps({"theme": arguments.theme, "refresh_seconds": 0}))
        server = subprocess.Popen(
            ["Xvfb", arguments.display, "-screen", "0", f"{width}x{height}x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        app = None
        try:
            time.sleep(1.5)
            environment = {
                **os.environ, "DISPLAY": arguments.display, "YTBOT_ROOT": str(arguments.root.resolve()),
                "YTBOT_MANAGER_CONFIG": str(settings), "WAYLAND_DISPLAY": "",
                # Paths render relative to HOME (`~/demo`), so no local user name reaches Git.
                "HOME": str(arguments.root.resolve().parent),
            }
            app = subprocess.Popen([str(arguments.binary)], env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            time.sleep(4)
            if app.poll() is not None:
                raise SystemExit(app.stderr.read().decode(errors="replace"))
            keys = Keyboard(arguments.display)
            if (width, height) != DEFAULT_SIZE:
                keys.fill_screen(width, height)
            keys.point(width // 2, height // 2)
            keys.focus_top_window()

            def shot(name: str) -> None:
                if name not in wanted:
                    return
                time.sleep(1.2)
                target = arguments.out / f"{name}-{arguments.theme}{suffix}.png"
                subprocess.run(["import", "-display", arguments.display, "-window", "root", str(target)],
                               check=True)
                print(target)

            keys.press("Control_L+1")
            keys.press("Tab")
            keys.press("Tab")
            shot("keyboard-focus")
            keys.press("Escape")

            for index, page in enumerate(PAGES, start=1):
                keys.press(f"Control_L+{index}")
                if page in ("central", "overview", "sessions"):
                    keys.press("Down")
                shot(page)
                if page == "central":
                    # End selects the last client ficha, Enter opens its detail (with photos).
                    keys.press("End")
                    keys.press("Return")
                    time.sleep(1.0)
                    shot("ficha-detail")
                    # In the detail, End scrolls to the bottom (photos and files).
                    keys.press("End")
                    shot("ficha-detail-end")
                    keys.press("Escape")
                if page == "channels":
                    keys.press("Down")
                    keys.press("Down")
                    keys.press("Down")
                    keys.press("Return")
                    shot("channel-detail")
                    keys.press("Escape")
        finally:
            if app:
                app.terminate()
                app.wait(timeout=10)
            server.terminate()
            server.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
