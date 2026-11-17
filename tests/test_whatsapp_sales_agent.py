import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sales_fixtures import MONDAY, Clock, FakeChannel, FakeModel, lead_rows, write_csv
from tools.ytbot.commercial.whatsapp import listener, sender
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent, owner_resolve
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore


class SalesAgentTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SalesStore(root / "whatsapp")
        self.clock = Clock()
        self.notes = []
        self.pauses = []

    def tearDown(self):
        self.directory.cleanup()

    def leads(self, count=1):
        csv = write_csv(Path(self.directory.name) / "leads.csv", lead_rows(count))
        self.store.import_csv(csv, self.clock())
        return sorted(self.store.leads().values(), key=lambda lead: lead["phone"])

    def agent(self, channel=None, model=None, live=True):
        channel = channel if channel is not None else FakeChannel(self.store.journal_path)
        return SalesAgent(self.rules, self.store, channel if live else None, model, live=live,
                          clock=self.clock, sleep=self.pauses.append,
                          notify=lambda title, body: self.notes.append(body),
                          log=lambda message: None), channel

    def event(self, text, number="0001", event_id="e1"):
        return {"id": event_id, "at": "2026-11-16T09:30:00", "message_at": "09:30",
                "chat": f"+55 65 90000-{number}", "text": text, "unread": True, "allowed": True}

    def opened_lead(self):
        lead = self.leads(1)[0]
        agent, channel = self.agent()
        agent.prospect()
        return lead, agent, channel

    # Openings ------------------------------------------------------------------------
    def test_opening_sends_the_script_in_order_and_records_memory(self):
        lead, _, channel = self.opened_lead()
        texts = [item["text"] for item in channel.sent]
        self.assertEqual(texts, self.rules.opening_messages(MONDAY))
        self.assertEqual(self.store.lead(lead["id"])["state"], "opened")
        history = self.store.history(lead["id"])
        self.assertEqual([entry["kind"] for entry in history], ["opening"] * 8)
        journal = sender.read_journal(self.store.journal_path)
        self.assertTrue(all(entry.get("kind") == "sales-opening" for entry in journal))
        rules = listener.load_rules(self.store.contact_rules_path)
        self.assertTrue(listener.contact_allowed("+55 65 90000-0001", rules))

    def test_opening_uses_the_owner_intervals(self):
        _, _, channel = self.opened_lead()
        self.assertEqual([item["delay"] for item in channel.sent], [4, 2, 8, 8, 4, 4, 4, 4])

    def test_reply_delay_follows_message_length(self):
        _, agent, channel = self.opened_lead()
        agent.llm = FakeModel({"intent": "site_institutional", "messages": [
            "Fica em média R$ 500.",
            "Um site institucional é a vitrine da sua empresa na internet: mostra quem vocês "
            "são, os serviços, fotos, endereço, horário e um botão para chamar no WhatsApp."]})
        agent.ingest([self.event("Quanto fica um site para a minha barbearia?")])
        agent.reply_pending()
        short, long = channel.sent[-2]["delay"], channel.sent[-1]["delay"]
        pacing = agent.pacing
        self.assertLessEqual(short, pacing.max_seconds + pacing.reading_max)
        self.assertGreater(long, pacing.min_seconds)
        self.assertLessEqual(long, pacing.max_seconds)

    def test_chat_list_echo_of_our_message_is_not_an_incoming_message(self):
        lead, agent, channel = self.opened_lead()
        agent.ingest([self.event("https://abastevo.com.br")])
        self.assertIsNone(self.store.lead(lead["id"])["awaiting"])
        self.assertEqual(agent.reply_pending(), [])

    def test_opening_is_never_repeated(self):
        lead, agent, channel = self.opened_lead()
        self.assertEqual(agent.prospect(), [])
        self.assertEqual(len(channel.sent), 8)
        self.assertEqual(agent.open_lead(self.store.lead(lead["id"]))["state"], "already-opened")

    def test_daily_limit_of_ten_first_contacts(self):
        self.leads(12)
        agent, channel = self.agent()
        results = agent.prospect()
        self.assertEqual(sum(1 for item in results if item["state"] == "opened"), 10)
        self.assertEqual(agent.prospect(), [])
        self.clock.now = MONDAY + timedelta(days=1)
        self.assertEqual(len(agent.prospect()), 2)
        self.assertTrue(self.pauses, "chats are paced one after another")

    def test_no_first_contact_outside_business_hours(self):
        self.leads(1)
        self.clock.now = MONDAY.replace(hour=20)
        agent, channel = self.agent()
        self.assertEqual(agent.prospect(), [])
        self.assertEqual(channel.sent, [])

    def test_do_not_contact_number_is_never_opened(self):
        lead = self.leads(1)[0]
        self.store.add_dnc(lead["phone"], "refusal", MONDAY)
        agent, channel = self.agent()
        agent.prospect()
        self.assertEqual(channel.sent, [])
        self.assertEqual(self.store.lead(lead["id"])["state"], "do-not-contact")

    def test_unconfirmed_opening_is_fenced_and_owner_notified(self):
        lead = self.leads(1)[0]
        channel = FakeChannel(self.store.journal_path, states=["sent", "sent", "unconfirmed"])
        agent, _ = self.agent(channel)
        self.assertEqual(agent.prospect()[0]["state"], "unconfirmed")
        self.assertEqual(len(channel.sent), 2)
        self.assertEqual(self.store.lead(lead["id"])["state"], "unconfirmed")
        self.assertTrue(self.notes)
        self.assertEqual(agent.prospect(), [])
        self.assertEqual(len(channel.sent), 2)

    def test_number_without_whatsapp_is_not_counted(self):
        lead = self.leads(1)[0]
        agent, channel = self.agent(FakeChannel(self.store.journal_path,
                                                open_status="invalid-number"))
        agent.prospect()
        self.assertEqual(self.store.lead(lead["id"])["state"], "invalid-number")
        self.assertEqual(agent.openings_today(), 0)

    def test_dry_run_plans_without_sending_or_changing_state(self):
        lead = self.leads(1)[0]
        agent, _ = self.agent(live=False)
        result = agent.prospect()[0]
        self.assertEqual(result["state"], "planned")
        self.assertEqual(self.store.lead(lead["id"])["state"], "new")
        self.assertFalse(self.store.journal_path.exists())

    # Replies -------------------------------------------------------------------------
    def test_reply_uses_the_model_and_keeps_full_memory(self):
        lead, agent, channel = self.opened_lead()
        agent.llm = FakeModel({"intent": "site_institutional",
                               "messages": ["O site institucional fica em média R$ 500."]})
        agent.ingest([self.event("Quanto fica um site?")])
        results = agent.reply_pending()
        self.assertEqual(results[0]["state"], "engaged")
        self.assertEqual(channel.sent[-1]["text"], "O site institucional fica em média R$ 500.")
        user_prompt = agent.llm.calls[0]["messages"][1]["content"]
        self.assertIn("Tudo bem?", user_prompt)
        history = self.store.history(lead["id"])
        self.assertEqual([entry["dir"] for entry in history[-2:]], ["in", "out"])
        self.assertIsNone(self.store.lead(lead["id"])["awaiting"])

    def test_messages_from_other_chats_are_ignored(self):
        _, agent, channel = self.opened_lead()
        agent.ingest([{"id": "x", "chat": "Mãe", "text": "Oi filho"}])
        self.assertEqual(agent.reply_pending(), [])
        self.assertEqual(len(channel.sent), 8)

    def test_refusal_blocks_forever(self):
        lead, agent, channel = self.opened_lead()
        agent.ingest([self.event("Nesse momento não estou precisando")])
        agent.reply_pending()
        self.assertEqual(channel.sent[-1]["text"], "Entendo, obrigado pela atenção! Tenha um ótimo dia.")
        self.assertEqual(self.store.lead(lead["id"])["state"], "do-not-contact")
        self.assertTrue(self.store.is_dnc(lead["phone"]))
        rules = listener.load_rules(self.store.contact_rules_path)
        self.assertFalse(listener.contact_allowed("+55 65 90000-0001", rules))
        sent = len(channel.sent)
        agent.ingest([self.event("Oi de novo", event_id="e2")])
        self.assertEqual(agent.reply_pending(), [])
        self.clock.now = MONDAY + timedelta(days=10)
        agent.followups()
        self.assertEqual(len(channel.sent), sent)
        self.assertTrue(any("bloqueado" in note for note in self.notes))

    def test_quote_flow_goes_to_the_owner(self):
        lead, agent, channel = self.opened_lead()
        agent.ingest([self.event("Vocês fazem sistema de agendamento?")])
        agent.reply_pending()
        self.assertEqual([item["text"] for item in channel.sent[-2:]],
                         ["Sim, nós podemos fazer isso.", "Você gostaria que eu fizesse um orçamento?"])
        agent.ingest([self.event("Sim", event_id="e2")])
        agent.reply_pending()
        self.assertEqual(self.store.lead(lead["id"])["state"], "qualifying")
        agent.ingest([self.event("Barbearia, quero agenda online com lembrete", event_id="e3")])
        agent.reply_pending()
        self.assertEqual(self.store.lead(lead["id"])["state"], "quote-requested")
        self.assertTrue(any("quote_details" in note for note in self.notes))
        sent = len(channel.sent)
        agent.ingest([self.event("Alguma novidade?", event_id="e4")])
        self.assertEqual(agent.reply_pending(), [])
        self.assertEqual(len(channel.sent), sent)

    def test_robot_question_gets_the_honest_answer(self):
        _, agent, channel = self.opened_lead()
        agent.ingest([self.event("Isso é robô?")])
        agent.reply_pending()
        self.assertIn("assistente automático", channel.sent[-1]["text"])

    def test_business_auto_reply_gets_no_answer(self):
        lead, agent, channel = self.opened_lead()
        agent.ingest([self.event("Olá! Esta é uma mensagem automática. Retornaremos em breve.")])
        agent.reply_pending()
        self.assertEqual(len(channel.sent), 8)
        self.assertIsNone(self.store.lead(lead["id"])["awaiting"])

    def test_unknown_question_sends_ack_and_hands_off(self):
        lead, agent, channel = self.opened_lead()
        agent.llm = FakeModel({"intent": "unknown", "messages": []})
        agent.ingest([self.event("Vocês emitem nota fiscal e atendem em Sinop?")])
        agent.reply_pending()
        self.assertEqual(channel.sent[-1]["text"], self.rules.handoff_messages()[0])
        self.assertEqual(self.store.lead(lead["id"])["state"], "needs-owner")
        self.assertTrue(self.store.handoffs())
        owner_resolve(self.store, lead["id"], "engaged")
        self.assertEqual(self.store.lead(lead["id"])["state"], "engaged")

    def test_owner_reply_in_the_chat_pauses_automation(self):
        lead, agent, channel = self.opened_lead()
        channel.bubbles = [{"dir": "in", "text": "Quanto custa?"},
                           {"dir": "out", "text": "Te ligo já já"}]
        agent.ingest([self.event("Quanto custa?")])
        self.assertEqual(agent.reply_pending()[0]["state"], "owner")
        self.assertEqual(len(channel.sent), 8)

    def test_full_chat_text_replaces_the_truncated_preview(self):
        lead, agent, channel = self.opened_lead()
        model = FakeModel({"intent": "system_request", "messages": []})
        agent.llm = model
        channel.bubbles = [{"dir": "out", "text": "https://abastevo.com.br Abastevo"},
                           {"dir": "in", "text": "Oi, eu tenho uma barbearia e queria um sistema"}]
        agent.ingest([self.event("Oi, eu tenho uma barbearia e queria…")])
        agent.reply_pending()
        prompt = model.calls[0]["messages"][1]["content"] if model.calls else ""
        history = self.store.history(lead["id"])
        self.assertTrue(any(entry.get("replaces") == "e1" for entry in history))
        self.assertEqual(channel.sent[-1]["text"], "Você gostaria que eu fizesse um orçamento?")
        self.assertNotIn("queria…", prompt)

    def test_messages_outside_reply_hours_wait_for_the_window(self):
        _, agent, channel = self.opened_lead()
        self.clock.now = MONDAY.replace(hour=23)
        agent.ingest([self.event("Quanto custa?")])
        self.assertEqual(agent.reply_pending(), [])
        self.clock.now = MONDAY.replace(hour=23) + timedelta(hours=9)
        self.assertEqual(len(agent.reply_pending()), 1)
        self.assertGreater(len(channel.sent), 8)

    def test_same_event_is_never_answered_twice(self):
        lead, agent, channel = self.opened_lead()
        agent.ingest([self.event("Quanto custa?")])
        agent.reply_pending()
        sent = len(channel.sent)
        agent.ingest([self.event("Quanto custa?")])
        self.store.update_lead(lead["id"], awaiting="e1")
        agent.reply_pending()
        self.assertEqual(len(channel.sent), sent)

    def test_contact_blocked_in_rules_json_gets_no_automatic_reply(self):
        _, agent, channel = self.opened_lead()
        listener.save_rules(self.store.contact_rules_path, "block", ["+5565900000001"])
        agent.ingest([self.event("Quanto custa?")])
        self.assertEqual(agent.reply_pending()[0]["state"], "blocked-by-rules")
        self.assertEqual(len(channel.sent), 8)

    def test_daily_reply_cap_hands_the_chat_to_the_owner(self):
        lead, agent, _ = self.opened_lead()
        today = MONDAY.date().isoformat()
        self.store.update_lead(lead["id"], replies={today: 12})
        agent.ingest([self.event("Quanto custa?")])
        self.assertEqual(agent.reply_pending()[0]["state"], "needs-owner")

    def test_dry_run_reply_is_planned_only(self):
        lead = self.leads(1)[0]
        live, _ = self.agent()
        live.prospect()
        agent, _ = self.agent(live=False)
        agent.ingest([self.event("Quanto custa?")])
        result = agent.reply_pending()[0]
        self.assertEqual(result["state"], "planned")
        self.assertEqual(self.store.lead(lead["id"])["awaiting"], "e1")

    def test_dry_run_decides_each_message_once(self):
        self.leads(1)
        live, _ = self.agent()
        live.prospect()
        model = FakeModel({"intent": "price", "messages": ["O site fica em média R$ 500."]})
        agent, _ = self.agent(model=model, live=False)
        agent.ingest([self.event("Quanto custa um site para minha barbearia no centro?")])
        agent.reply_pending()
        self.assertEqual(agent.reply_pending()[0]["state"], "already-planned")
        self.assertEqual(len(model.calls), 1)

    def test_browser_error_while_opening_a_chat_keeps_the_message_pending(self):
        lead, agent, channel = self.opened_lead()

        def broken(lead):
            raise RuntimeError("chat did not open")
        channel.open = broken
        agent.ingest([self.event("Quanto custa?")])
        self.assertEqual(agent.reply_pending()[0]["state"], "error")
        self.assertEqual(self.store.lead(lead["id"])["awaiting"], "e1")
        self.assertEqual(len(channel.sent), 8)

    # Follow-ups ----------------------------------------------------------------------
    def test_one_follow_up_then_stop(self):
        lead, agent, channel = self.opened_lead()
        self.clock.now = MONDAY + timedelta(hours=73)
        self.assertEqual(agent.followups()[0]["state"], "followed-up")
        self.assertEqual(channel.sent[-1]["text"], self.rules.followup_messages()[0])
        self.clock.now = MONDAY + timedelta(hours=100)
        self.assertEqual(agent.followups(), [])
        self.clock.now = MONDAY + timedelta(hours=73 + 97)
        self.assertEqual(agent.followups()[0]["state"], "no-response")
        self.clock.now = MONDAY + timedelta(days=30)
        agent.followups()
        agent.prospect()
        self.assertEqual(len(channel.sent), 9)
        self.assertEqual(self.store.lead(lead["id"])["state"], "no-response")

    def test_lead_who_answered_gets_no_follow_up(self):
        _, agent, channel = self.opened_lead()
        agent.ingest([self.event("Obrigado!")])
        agent.reply_pending()
        self.clock.now = MONDAY + timedelta(days=5)
        self.assertEqual(agent.followups(), [])
        self.assertEqual(len(channel.sent), 8)


if __name__ == "__main__":
    unittest.main()
