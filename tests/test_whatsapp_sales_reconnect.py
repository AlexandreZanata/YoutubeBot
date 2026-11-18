import unittest
from types import SimpleNamespace

from tools.ytbot.commercial.whatsapp.sales import commands
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore


class TargetClosedError(Exception):
    """Same name as Playwright's error for a closed page or connection."""


EMPTY = {"ingested": [], "replies": [], "followups": [], "openings": []}


class Page:
    def __init__(self, closes=0):
        self.closes = closes

    def wait_for_timeout(self, ms):
        if self.closes:
            self.closes -= 1
            raise TargetClosedError("Page.wait_for_timeout: Target page, context or browser has been closed")


class Session:
    def __init__(self, page):
        self.page = page
        self.reopened = 0
        self.channel = "new-channel"

    def reopen(self, agent, error):
        self.reopened += 1
        self.page = Page()
        agent.channel = self.channel


class Agent:
    live = True

    def __init__(self, summaries=None):
        self.store = SimpleNamespace(base="base")
        self.summaries = list(summaries or [])
        self.channel = "old-channel"
        self.cycles = 0

    def cycle(self, events, prospect=False, limit=None):
        self.cycles += 1
        return self.summaries.pop(0) if self.summaries else EMPTY

    def use_rules(self, rules):
        pass


def args(**changes):
    values = {"rules": None, "max_chats": 30, "prospect": False, "limit": None, "once": False,
              "max_cycles": 3, "interval": 15}
    values.update(changes)
    return SimpleNamespace(**values)


class ReconnectTests(unittest.TestCase):
    def run_loop(self, agent, session, listen=None, **changes):
        commands.run_cycles(agent, session, args(**changes),
                            listen=listen or (lambda *a, **k: []), out=lambda line: None)

    def test_a_page_closed_while_waiting_reconnects_and_keeps_going(self):
        agent, session = Agent(), Session(Page(closes=1))
        self.run_loop(agent, session)
        self.assertEqual((session.reopened, agent.cycles), (1, 3))
        self.assertEqual(agent.channel, "new-channel")

    def test_a_page_closed_while_listening_reconnects(self):
        calls = {"count": 0}

        def listen(page, base, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TargetClosedError("Target page, context or browser has been closed")
            return []
        agent, session = Agent(), Session(Page())
        self.run_loop(agent, session, listen=listen)
        self.assertEqual((session.reopened, agent.cycles), (1, 3))

    def test_repeated_closures_stop_after_the_limit(self):
        def listen(page, base, **kwargs):
            raise TargetClosedError("Browser closed")
        with self.assertRaises(TargetClosedError):
            self.run_loop(Agent(), Session(Page()), listen=listen)

    def test_other_errors_are_not_hidden(self):
        def listen(page, base, **kwargs):
            raise ValueError("selector changed")
        with self.assertRaises(ValueError):
            self.run_loop(Agent(), Session(Page()), listen=listen)

    def test_an_unconfirmed_send_still_stops_the_run(self):
        failed = {**EMPTY, "replies": [{"state": "unconfirmed"}]}
        with self.assertRaises(SystemExit):
            self.run_loop(Agent([failed]), Session(Page()))

    def test_closed_errors_are_recognized(self):
        self.assertTrue(commands.is_closed(TargetClosedError("x")))
        self.assertTrue(commands.is_closed(RuntimeError("Connection closed while reading")))
        self.assertFalse(commands.is_closed(RuntimeError("timeout 30000ms exceeded")))


if __name__ == "__main__":
    unittest.main()


class StopSignalTests(unittest.TestCase):
    def test_sigterm_closes_the_tab_and_releases_the_run_lock(self):
        import os
        import signal
        import tempfile
        from pathlib import Path
        from unittest import mock

        closed = []

        class Closable:
            def __init__(self, name):
                self.name = name

            def close(self):
                closed.append(self.name)

            def stop(self):
                closed.append(self.name)

        def page_factory(_args):
            return None, None, Closable("playwright"), Closable("client"), Closable("page")

        locks = []

        def stopped(agent, *_args, **_kwargs):
            locks.append(agent.store.lock_path.exists())
            os.kill(os.getpid(), signal.SIGTERM)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "whatsapp"
            factory = lambda: SimpleNamespace(network=lambda name: base)  # noqa: E731
            run_args = SimpleNamespace(**{**vars(args()), "live": False, "no_llm": True})
            previous = signal.getsignal(signal.SIGTERM)
            with mock.patch.object(commands, "run_cycles", stopped), \
                    self.assertRaises(SystemExit):
                commands.command_run(run_args, factory, page_factory)
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
            self.assertIn("page", closed)
            self.assertEqual(locks, [True])
            self.assertFalse(SalesStore(base).lock_path.exists())
