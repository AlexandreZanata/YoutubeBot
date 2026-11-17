import unittest

from sales_fixtures import MONDAY, FakeModel
from tools.ytbot.commercial.whatsapp.sales import guard
from tools.ytbot.commercial.whatsapp.sales.decide import decide
from tools.ytbot.commercial.whatsapp.sales.rules import load

LEAD = {"id": "Ltest", "name": "Barbearia Teste", "category": "Barbearia", "city": "Cuiabá",
        "state": "engaged", "phone": "5565900000001"}


class SalesDecisionTests(unittest.TestCase):
    rules = load()

    def run_model(self, text, answer, history=None):
        model = FakeModel(answer)
        return decide(self.rules, LEAD, history or [], text, model, MONDAY), model

    def test_valid_model_text_is_sent(self):
        decision, model = self.run_model("Quanto fica um site?", {
            "intent": "site_institutional",
            "messages": ["O site institucional fica em média R$ 500, com entrada de R$ 250.",
                         "Fica pronto em média em 15 dias."]})
        self.assertEqual(decision.source, "model")
        self.assertEqual(decision.action, "reply")
        self.assertEqual(model.calls[0]["session_id"], "zaflas-sales-Ltest")

    def test_context_carries_rules_history_and_no_phone(self):
        history = [{"at": "2026-11-16T09:00:00", "dir": "out", "text": "Bom dia", "state": "sent"}]
        _, model = self.run_model("Quanto custa?", {"intent": "price", "messages": ["Ok"]},
                                  history)
        system, user = model.calls[0]["messages"]
        self.assertIn("R$ 39,90", system["content"])
        self.assertIn("Alexandre: Bom dia", user["content"])
        self.assertIn("Quanto custa?", user["content"])
        self.assertNotIn(LEAD["phone"], system["content"] + user["content"])

    def test_invented_price_falls_back_to_the_rules_text(self):
        decision, _ = self.run_model("Faz mais barato?", {
            "intent": "price", "messages": ["Faço por R$ 300 pra você."]})
        self.assertEqual(decision.source, "template")
        self.assertIn("money value not in the rules: 300.00", decision.violations)
        self.assertEqual(decision.messages, list(self.rules.intent("price").messages))

    def test_discount_unknown_link_and_human_claim_are_rejected(self):
        problems = guard.violations(self.rules, [
            "Te dou desconto", "Veja https://example.com", "Não sou robô, sou o Alexandre"])
        self.assertIn("forbidden term: desconto", problems)
        self.assertIn("link not in the rules: example.com", problems)
        self.assertIn("claims to be human", problems)

    def test_reply_cannot_promise_the_quote_it_offers(self):
        decision, _ = self.run_model("Quanto custa?", {"intent": "price", "messages": [
            "Sistemas e aplicativos dependem do que você precisa, então eu faço um orçamento. "
            "Você gostaria que eu fizesse um orçamento?"]})
        self.assertEqual(decision.source, "template")
        self.assertIn("promises the quote and also offers it", decision.violations)
        self.assertEqual(guard.violations(self.rules, decision.messages), [])

    def test_every_reference_text_passes_the_guard(self):
        for intent in self.rules.intents:
            self.assertEqual(guard.violations(self.rules, list(intent.messages) or ["ok"]), [],
                             intent.id)

    def test_links_are_split_into_their_own_messages(self):
        self.assertEqual(guard.split_links(["Veja: https://zaflas.com.br e https://abastevo.com.br"]),
                         ["Veja", "https://zaflas.com.br", "e", "https://abastevo.com.br"])

    def test_model_refusal_blocks_with_the_fixed_text(self):
        decision, _ = self.run_model("Talvez outro dia, por enquanto deixa quieto, tá bom assim", {
            "intent": "later", "messages": ["Tudo bem!"], "do_not_contact": True})
        self.assertEqual((decision.intent, decision.action), ("refusal", "block"))
        self.assertEqual(decision.messages, list(self.rules.intent("refusal").messages))

    def test_local_refusal_wins_over_the_model(self):
        text = ("Nesse momento não estou precisando, mas achei os sites bonitos, "
                "quem sabe no ano que vem a gente conversa")
        decision, _ = self.run_model(text, {"intent": "interested", "messages": ["Que bom!"]})
        self.assertEqual(decision.action, "block")

    def test_model_handoff_sends_only_the_owner_ack(self):
        decision, _ = self.run_model("Vocês emitem nota?", {
            "intent": "price", "messages": ["Sim, emitimos."], "handoff": True})
        self.assertEqual(decision.action, "handoff")
        self.assertEqual(decision.messages, self.rules.handoff_messages())

    def test_unknown_question_goes_to_the_owner(self):
        decision, _ = self.run_model("Vocês atendem em Sinop?", {
            "intent": "unknown", "messages": ["Atendemos sim!"]})
        self.assertEqual(decision.action, "handoff")
        self.assertNotIn("Atendemos sim!", decision.messages)

    def test_model_failure_uses_the_local_intent(self):
        model = FakeModel(error="HTTP 500: upstream")
        decision = decide(self.rules, LEAD, [], "Quanto custa?", model, MONDAY)
        self.assertEqual((decision.intent, decision.source), ("price", "local"))
        self.assertEqual(decision.error, "HTTP 500: upstream")

    def test_invalid_json_uses_the_local_intent(self):
        decision, _ = self.run_model("Quanto custa?", "não sei")
        self.assertEqual(decision.source, "local")
        self.assertTrue(decision.error.startswith("invalid model output"))

    def test_robot_question_is_always_answered_honestly(self):
        text = "Isso aqui é robô ou é você mesmo? E quanto custa um site para minha loja de roupas?"
        decision, _ = self.run_model(text, {
            "intent": "price", "messages": ["O site fica em média R$ 500."]})
        self.assertEqual(decision.messages[0], self.rules.intent("bot_question").messages[0])

    def test_short_decisive_messages_never_call_the_model(self):
        decision, model = self.run_model("Não, obrigado", {"intent": "interested"})
        self.assertEqual(model.calls, [])
        self.assertEqual(decision.action, "block")


if __name__ == "__main__":
    unittest.main()
