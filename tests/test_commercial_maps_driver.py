import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from maps_support import fixture, listing
from tools.ytbot.commercial.maps import driver, record, rules, verify

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=ZoneInfo("America/Cuiaba"))


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def count(self):
        return self.page.count(self.selector)

    def click(self):
        pass

    def fill(self, _value):
        pass

    def press_sequentially(self, value, delay=0):
        self.page.typed.append((value, delay))

    def evaluate(self, _script):
        self.page.scrolls += 1

    def inner_text(self):
        return self.page.content()


class FakePage:
    """The tiny part of Playwright the driver touches, backed by saved HTML."""

    def __init__(self):
        self.state = "feed"
        self.url = "https://www.google.com/maps"
        self.typed = []
        self.opened = []
        self.scrolls = 0
        self.challenge = False
        self.challenge_on_place = False

    def set_default_timeout(self, _milliseconds):
        pass

    def wait_for_timeout(self, _milliseconds):
        pass

    def content(self):
        if self.challenge or (self.challenge_on_place and self.state == "place"):
            return fixture("challenge.html")
        if self.state == "place":
            return fixture("listing_sem_site.html")
        if self.state == "search":
            return fixture("search_results.html")
        return fixture("feed.html")

    def count(self, selector):
        if "combobox" in selector:
            return 1
        if "role='feed'" in selector:
            return 1 if self.state == "feed" else 0
        return 0

    def locator(self, selector):
        return FakeLocator(self, selector)

    def goto(self, url, **_kwargs):
        self.opened.append(url)
        self.url = url
        if "/maps/place/" in url:
            self.state = "place"
        elif "google.com/search" in url:
            self.state = "search"
        else:
            self.state = "feed"

    def go_back(self):
        self.state = "feed"
        self.url = "https://www.google.com/maps"

    @property
    def keyboard(self):
        return SimpleNamespace(press=lambda _key: None)


class MapsDriverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.rules = rules.load()
        self.store = record.RunStore(Path(self.directory.name) / "maps")
        self.run = self.store.create("Lucas do Rio Verde", "MT", NOW)
        self.searches = [rules.Search("saude", "dentista")]

    def tearDown(self):
        self.directory.cleanup()

    def test_research_reads_one_business_and_resumes_without_reopening(self):
        page = FakePage()
        result = driver.research(page, self.run, self.rules, self.searches, 1, NOW,
                                 log=lambda _message: None, sleep=lambda _seconds: None,
                                 rng=random.Random(7))
        self.assertEqual(result["opened"], 1)
        self.assertEqual(len(self.run.read_listings()), 1)
        done = [entry for entry in self.run.queries() if entry["status"] == "done"]
        self.assertEqual(len(done[0]["links"]), 3)
        first_opened = list(page.opened)

        second = driver.research(page, self.run, self.rules, self.searches, 5, NOW,
                                 log=lambda _message: None, sleep=lambda _seconds: None,
                                 rng=random.Random(7))
        self.assertEqual(second["opened"], 2)
        self.assertEqual(len(set(page.opened)), 3)
        self.assertEqual(page.opened[:len(first_opened)], first_opened)

    def test_challenge_stops_before_reading_the_listing(self):
        page = FakePage()
        page.challenge_on_place = True
        with self.assertRaises(driver.ChallengeError):
            driver.research(page, self.run, self.rules, self.searches, 1, NOW,
                            log=lambda _message: None, sleep=lambda _seconds: None,
                            rng=random.Random(7))
        self.assertEqual(self.run.read_listings(), [])
        self.assertTrue([entry for entry in self.run.listings()
                         if entry["state"] == "opening"])

    def test_verify_run_writes_a_check_for_each_pending_listing(self):
        self.run.append_listing({**listing(), "state": "read"})
        page = FakePage()
        result = driver.verify_run(
            page, self.run, self.rules, log=lambda _message: None,
            sleep=lambda _seconds: None, rng=random.Random(7),
            fetcher=lambda url, _rules: verify.Fetched(url, url, 0, "", "", "não resolveu",
                                                       url.startswith("https://"), False))
        self.assertEqual(result["checked"], 1)
        check = self.run.checks()[0]
        self.assertEqual(check["outcome"], "weak-site")
        self.assertEqual(check["identity"], record.identity(listing()))


if __name__ == "__main__":
    unittest.main()
