"""Private social-network profiles and account records for project promotion."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .. import config
from ..accounts_store import private_directory, read_private, write_private

NETWORK = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


class SocialStore:
    """One private profile directory per social network, never in Git."""

    def __init__(self, root: Path | None = None):
        self.root = private_directory(root or config.ROOT / ".local" / "social")

    def _name(self, network: str) -> str:
        if not NETWORK.fullmatch(network):
            raise ValueError("use a lowercase social network name")
        return network

    def network(self, network: str) -> Path:
        return private_directory(self.root / self._name(network))

    def profile(self, network: str) -> Path:
        return private_directory(self.network(network) / "profile")

    def account_path(self, network: str) -> Path:
        return self.network(network) / "account.json"

    def read_account(self, network: str) -> dict | None:
        return read_private(self.account_path(network))

    def save_account(self, network: str, *, handle: str, display_name: str,
                     state: str = "logged-in") -> dict:
        record = {
            "network": self._name(network),
            "state": state,
            "handle": handle,
            "display_name": display_name,
            "verified_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_private(self.account_path(network), record)
        return record

    def public_status(self, network: str) -> dict:
        account = self.read_account(network)
        if not account:
            return {"network": network, "state": "not-connected"}
        return {
            "network": account["network"],
            "state": account["state"],
            "handle": account["handle"],
            "display_name": account["display_name"],
            "verified_at": account["verified_at"],
        }
