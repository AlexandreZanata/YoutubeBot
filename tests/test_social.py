import tempfile
import unittest
from pathlib import Path

from tools.ytbot.social.instagram import account as instagram
from tools.ytbot.social.store import SocialStore
from tools.ytbot.social.x import account


class SocialStoreTests(unittest.TestCase):
    def test_each_network_keeps_its_own_private_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SocialStore(Path(directory))
            self.assertNotEqual(store.profile("x"), store.profile("instagram"))
            self.assertEqual(store.profile("x").stat().st_mode & 0o077, 0)

    def test_account_record_has_no_cookie_or_token_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SocialStore(Path(directory))
            store.save_account("x", handle="example", display_name="Example")
            record = store.read_account("x")
            self.assertEqual(record["handle"], "example")
            self.assertNotIn("cookies", record)
            self.assertNotIn("token", record)
            self.assertEqual(store.account_path("x").stat().st_mode & 0o077, 0)
            self.assertEqual(store.public_status("x")["state"], "logged-in")


class InstagramAccountTests(unittest.TestCase):
    def test_handle_from_profile_alt_and_href(self):
        self.assertEqual(instagram.parse_handle(text="Foto do perfil de exemplo.user"), "exemplo.user")
        self.assertEqual(instagram.parse_handle(href="/exemplo.user/"), "exemplo.user")

    def test_reserved_paths_are_not_handles(self):
        self.assertEqual(instagram.parse_handle(href="/explore/"), "")
        self.assertEqual(instagram.parse_handle(href="/direct/inbox/"), "")

    def test_constants_are_separate_from_x(self):
        self.assertNotEqual(instagram.CDP_PORT, 9322)
        self.assertNotEqual(instagram.BACKGROUND_DISPLAY, ":90")


class XAccountTests(unittest.TestCase):
    def test_handle_and_display_name_are_parsed_from_the_account_button(self):
        text = "Alexandre Zanata\n@AlexandreZanata\nMais"
        self.assertEqual(account.parse_handle(text), "AlexandreZanata")
        self.assertEqual(account.parse_display_name(text), "Alexandre Zanata")

    def test_profile_link_is_used_when_the_button_has_no_handle(self):
        self.assertEqual(account.parse_handle(href="/AlexandreZanata"), "AlexandreZanata")
        self.assertEqual(account.parse_handle(href="/home"), "")

    def test_login_url_and_port_are_explicit(self):
        self.assertEqual(account.LOGIN_URL, "https://x.com/home")
        self.assertNotEqual(account.CDP_PORT, 9300)


if __name__ == "__main__":
    unittest.main()
