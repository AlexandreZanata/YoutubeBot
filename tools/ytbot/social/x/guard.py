"""Temporary owner kill switch for X (Twitter) access.

The owner disabled X on the corporate network until they explicitly ask to
re-enable it. Every code path that opens an X page checks this guard first;
status, discovery, replies and publishing all refuse before touching the
browser. Re-enable by removing the private marker file.
"""

from __future__ import annotations

from ... import config

MARKER = config.ROOT / ".local" / "social" / "x" / "DISABLED"


class XDisabledError(RuntimeError):
    """Raised when X is used while the owner's temporary block is active."""


def x_disabled() -> bool:
    return MARKER.is_file()


def require_enabled() -> None:
    if x_disabled():
        raise XDisabledError(
            "X access is temporarily disabled by the owner on the corporate network. "
            "Do not open X, not even to check status; re-enable only when the owner asks "
            f"by removing {MARKER}."
        )
