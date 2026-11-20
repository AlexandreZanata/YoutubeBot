"""Session-expiry contract: never crash on a signed-out profile; stop and ask the owner."""

import unittest
from pathlib import Path

from tools.ytbot import upload_guard

ROOT = Path(__file__).resolve().parents[1]


class SessionContractTests(unittest.TestCase):
    def test_signed_out_and_challenge_pages_are_recognised(self):
        for body in (
            "Fazer login\nCriar conta\nMais opções",
            "Sign in\nCreate account",
            "Verifique se é você\nConfirme sua identidade",
            "Verify it's you",
        ):
            self.assertTrue(upload_guard.login_required(body), body)

    def test_normal_pages_are_not_misdetected(self):
        for body in (
            "Seu canal\nPainel\nConteúdo\nInsights",
            "YouTube Studio\nCriar\nEnviar vídeos",
            "",
        ):
            self.assertFalse(upload_guard.login_required(body), body)

    def test_account_check_gates_the_avatar_click_behind_login_detection(self):
        source = (ROOT / "tools/ytbot/account.py").read_text(encoding="utf-8")
        guard_at = source.index("upload_guard.login_required(body)")
        click_at = source.index("#avatar-btn")
        self.assertLess(guard_at, click_at,
                        "the signed-out check must run before any avatar click")


if __name__ == "__main__":
    unittest.main()
