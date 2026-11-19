"""The opening queue (owner, 2026-11-18): one Maps number at a time, in CSV order.

Synthetic numbers and a fake WhatsApp channel only; nothing here touches the real account.
"""

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sales_fixtures import MONDAY, PHONES, Clock, FakeChannel, write_csv
from tools.ytbot.commercial.whatsapp.sales import commands, queue
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore, canonical_phone

# Deliberately not alphabetical and not in phone order: the queue must follow the CSV rows.
ROWS = [{"name": "Zeta Pneus", "phone": PHONES[5], "city": "Sinop", "category": "Pneus"},
        {"name": "Alfa Barbearia", "phone": PHONES[1], "city": "Sinop",
         "category": "Barbearia"},
        {"name": "Meio Odontologia", "phone": PHONES[3], "city": "Sinop",
         "category": "Dentista"}]


class PerLeadChannel(FakeChannel):
    """A fake channel where chosen numbers have no WhatsApp."""

    def __init__(self, journal_path, invalid=()):
        super().__init__(journal_path)
        self.invalid = set(invalid)

    def open(self, lead):
        self.opened.append(lead["id"])
        return "invalid-number" if lead["id"] in self.invalid else "ready"


class QueueTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name) / "whatsapp"
        self.store = SalesStore(self.base)
        self.clock = Clock(MONDAY)
        self.notes = []
        self.channel = FakeChannel(self.store.journal_path)

    def tearDown(self):
        self.directory.cleanup()

    def import_rows(self, rows=ROWS):
        csv = write_csv(Path(self.directory.name) / "sinop.csv", rows)
        return self.store.import_csv(csv, self.clock(), "google-maps-manual")

    def lead(self, index):
        phone = canonical_phone(ROWS[index]["phone"]) if index < len(ROWS) else None
        return next(lead for lead in self.store.leads().values() if lead["phone"] == phone)

    def queue(self, operation, live=False, dry_run=False, limit=1):
        """Run `sales queue <operation>` as the CLI does, with the fake channel and clock."""
        args = SimpleNamespace(network="whatsapp", rules=None, operation=operation, live=live,
                               dry_run=dry_run, limit=limit)
        agent = partial(SalesAgent, clock=self.clock, sleep=lambda seconds: None,
                        notify=self.notes.append, log=lambda message: None)
        session = SimpleNamespace(channel=self.channel, close=lambda: None)
        out = io.StringIO()
        with mock.patch.object(commands, "SalesAgent", agent), \
                mock.patch.object(commands, "Session", lambda *a, **k: session), \
                contextlib.redirect_stdout(out):
            try:
                commands.command_queue(args, lambda: SimpleNamespace(network=lambda name: self.base),
                                       page_factory=None)
                error = None
            except SystemExit as stop:
                error = stop
        text = out.getvalue()
        return (json.loads(text[text.find("{"):]) if "{" in text else {}), error

    def statuses(self):
        return [(item["name"], item["status"]) for item in queue.items(self.store)]

    def sent_to(self, lead_id):
        return [item["text"] for item in self.channel.sent if item["lead"] == lead_id]

    # Order and listing ---------------------------------------------------------------
    def test_import_queues_the_three_leads_in_csv_order_all_pending(self):
        self.import_rows()
        self.assertEqual(self.statuses(), [(row["name"], "pending") for row in ROWS])
        self.assertEqual([self.lead(index)["queue_position"] for index in range(3)], [1, 2, 3])
        listed, _ = self.queue("list")
        self.assertEqual(listed["next"]["name"], "Zeta Pneus")
        self.assertEqual(listed["blocked"], "")

    def test_referrals_and_other_sources_are_not_in_the_queue(self):
        self.import_rows()
        self.store.import_rows([{"name": "Carlos · Zeta", "phone": PHONES[9]}], self.clock(),
                               "referral", extra={"referral": {"from": "x", "staff": "",
                                                               "company": "Zeta"}})
        self.store.import_rows([{"name": "Manual", "phone": PHONES[10]}], self.clock(), "manual")
        self.assertEqual([name for name, _ in self.statuses()], [row["name"] for row in ROWS])

    def test_list_never_shows_a_full_phone(self):
        self.import_rows()
        listed, _ = self.queue("list")
        text = json.dumps(listed)
        for row in ROWS:
            digits = canonical_phone(row["phone"])
            self.assertNotIn(digits, text)
            self.assertNotIn(digits[-8:], re.sub(r"\D", "", text))

    # Dry run and sending ---------------------------------------------------------------
    def test_dry_run_shows_the_company_name_and_sends_nothing(self):
        self.import_rows()
        output, error = self.queue("send", dry_run=True)
        self.assertIsNone(error)
        [first] = output["would_send"]
        self.assertIn("a empresa Zeta Pneus ainda não tem site", first["messages"][2])
        self.assertEqual(self.channel.sent, [])
        self.assertFalse(self.store.journal_path.exists())
        self.assertEqual({lead["state"] for lead in self.store.leads().values()}, {"new"})

    def test_live_limit_one_sends_only_the_first_then_the_second(self):
        self.import_rows()
        output, error = self.queue("send", live=True)
        self.assertIsNone(error)
        self.assertEqual([item["state"] for item in output["sent"]], ["opened"])
        self.assertEqual([status for _, status in self.statuses()],
                         ["sent", "pending", "pending"])
        self.clock.now += timedelta(minutes=5)
        self.queue("send", live=True)
        self.assertEqual([status for _, status in self.statuses()], ["sent", "sent", "pending"])
        self.assertEqual(len(self.sent_to(self.lead(0)["id"])), 8, "never sent twice")

    def test_the_third_bubble_names_the_company_and_nothing_else_changes(self):
        self.import_rows()
        self.queue("send", live=True)
        texts = self.sent_to(self.lead(0)["id"])
        template = self.rules.raw["opening"]
        self.assertEqual(texts[2], template["messages"][2].replace("{company}", "Zeta Pneus"))
        self.assertEqual(texts[3:4], template["messages"][3:4])
        self.assertEqual(texts[4:], template["links"])
        self.assertNotIn(canonical_phone(ROWS[0]["phone"])[-8:], re.sub(r"\D", "", texts[2]))

    def test_a_lead_without_name_gets_the_vocês_text(self):
        self.import_rows()
        self.store.update_lead(self.lead(0)["id"], name="")
        self.queue("send", live=True)
        self.assertEqual(self.sent_to(self.lead(0)["id"])[2], self.rules.raw["opening"]["unnamed"])

    # Limits and skips ----------------------------------------------------------------
    def test_outside_the_opening_window_nothing_is_sent_and_the_reason_is_given(self):
        self.import_rows()
        self.clock.now = MONDAY.replace(hour=20)
        output, error = self.queue("send", live=True)
        self.assertIsNone(error)
        self.assertIn("fora do horário de abertura", output["blocked"])
        self.assertEqual(self.channel.sent, [])
        preview, _ = self.queue("send")
        self.assertIn("fora do horário de abertura", preview["blocked"])

    def test_the_daily_limit_holds(self):
        limit = int(self.rules.limits["daily_openings"])
        rows = [{"name": f"Loja {index}", "phone": PHONES[index]} for index in range(limit + 2)]
        self.import_rows(rows)
        output, _ = self.queue("send", live=True, limit=limit + 2)
        self.assertEqual(sum(1 for item in output["sent"] if item["state"] == "opened"), limit)
        again, _ = self.queue("send", live=True)
        self.assertEqual(again["blocked"], f"limite diário de {limit} aberturas atingido")

    def test_do_not_contact_is_skipped_and_the_next_one_is_sent(self):
        self.import_rows()
        self.store.add_dnc(self.lead(0)["phone"], "refusal", self.clock())
        self.assertEqual(self.statuses()[0][1], "skipped")
        self.queue("send", live=True)
        self.assertEqual(self.sent_to(self.lead(0)["id"]), [])
        self.assertEqual([status for _, status in self.statuses()],
                         ["skipped", "sent", "pending"])

    def test_a_number_without_whatsapp_is_skipped_without_sending(self):
        self.import_rows()
        self.channel = PerLeadChannel(self.store.journal_path, invalid={self.lead(0)["id"]})
        self.queue("send", live=True)
        self.assertEqual(self.lead(0)["state"], "invalid-number")
        self.assertEqual(self.sent_to(self.lead(0)["id"]), [])
        self.assertEqual([status for _, status in self.statuses()],
                         ["skipped", "sent", "pending"])

    # Uncertain sends ---------------------------------------------------------------------
    def test_an_unconfirmed_send_stops_the_queue_and_is_never_repeated(self):
        self.import_rows()
        self.channel = FakeChannel(self.store.journal_path, states=["sent", "unconfirmed"])
        output, error = self.queue("send", live=True, limit=3)
        self.assertIsNotNone(error)
        self.assertEqual([item["state"] for item in output["sent"]], ["unconfirmed"])
        self.assertEqual([status for _, status in self.statuses()],
                         ["unconfirmed", "pending", "pending"])
        self.channel = FakeChannel(self.store.journal_path)
        self.queue("send", live=True)
        self.assertEqual(self.sent_to(self.lead(0)["id"]), [])
        self.assertEqual(self.statuses()[1][1], "sent")

    def test_a_crash_in_the_middle_of_an_opening_is_reconciled_without_resending(self):
        self.import_rows()
        first = self.lead(0)["id"]
        self.store.update_lead(first, state="opening", opened_at=self.clock().isoformat())
        self.assertEqual(self.statuses()[0][1], "sending")
        output, error = self.queue("send", live=True)
        self.assertIsNotNone(error)
        self.assertEqual(output["reconciled"][0]["lead"], first)
        self.assertEqual(self.store.lead(first)["state"], "unconfirmed")
        self.assertIn("Abertura interrompida", self.notes[-1]["reason"])
        self.assertEqual(self.channel.sent, [])
        self.queue("send", live=True)
        self.assertEqual(self.sent_to(first), [])
        self.assertEqual([status for _, status in self.statuses()],
                         ["unconfirmed", "sent", "pending"])

    def test_only_one_process_sends_at_a_time(self):
        self.import_rows()
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.store.lock_path.write_text(str(os.getppid()), encoding="utf-8")
        _, error = self.queue("send", live=True)
        self.assertIn("only one process sends at a time", str(error))
        self.assertEqual(self.channel.sent, [])

    # PR #86: a number that writes first keeps being answered --------------------------
    def test_a_lead_that_writes_before_the_opening_is_answered_and_skipped(self):
        self.import_rows()
        first = self.lead(0)
        agent = SalesAgent(self.rules, self.store, self.channel, None, live=True,
                           clock=self.clock, sleep=lambda seconds: None,
                           notify=self.notes.append, log=lambda message: None)
        chat = "+55 65 90000-0006"
        agent.ingest([{"id": "e1", "chat": chat, "text": "Quanto custa um site?"}])
        agent.reply_pending()
        self.assertTrue(self.sent_to(first["id"]), "the number that wrote is answered")
        self.assertEqual(self.store.lead(first["id"])["state"], "engaged")
        self.assertEqual(self.statuses()[0][1], "skipped")
        before = len(self.sent_to(first["id"]))
        self.queue("send", live=True)
        self.assertEqual(len(self.sent_to(first["id"])), before, "no opening after a reply")
        self.assertEqual(self.statuses()[1][1], "sent")


if __name__ == "__main__":
    unittest.main()
