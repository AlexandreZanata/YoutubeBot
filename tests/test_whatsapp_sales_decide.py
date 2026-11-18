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
        decision, _ = self.run_model("E pra uma loja pequena, quanto fica?", {
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
            if intent.fixed:
                continue  # sent verbatim, never through the model (e.g. the Pix keys)
            self.assertEqual(guard.violations(self.rules, list(intent.messages) or ["ok"]), [],
                             intent.id)
        self.assertEqual(
            guard.violations(self.rules, guard.split_links(list(self.rules.brief["domain_messages"]))),
            [],
        )

    def test_domain_reply_sends_registro_br_link_and_forty_reais_option(self):
        decision, _ = self.run_model("O que é domínio e quanto custa?", {
            "intent": "domain",
            "messages": list(self.rules.intent("domain").messages),
        })
        self.assertEqual((decision.intent, decision.source), ("domain", "model"))
        self.assertIn("https://registro.br/", decision.messages)
        self.assertTrue(any("R$ 40" in msg and "1 ano" in msg for msg in decision.messages))

    def test_site_prices_never_describe_an_app(self):
        decision, _ = self.run_model("E pra minha loja de roupas, quanto ficaria?", {
            "intent": "price", "messages": ["Um aplicativo fica em média R$ 500."]})
        self.assertIn("site price next to an app or system", decision.violations)
        self.assertNotIn("Um aplicativo fica em média R$ 500.", decision.messages)

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

    def test_project_description_while_qualifying_is_final_locally(self):
        lead = {**LEAD, "state": "qualifying"}
        model = FakeModel({"intent": "media", "messages": []})
        decision = decide(self.rules, lead, [], "Photo\nEstúdio de fotos, atendo de segunda a "
                          "sexta das 10h às 18h e queria agendamento online", model, MONDAY)
        self.assertEqual((decision.intent, decision.action), ("quote_details", "collect"))
        self.assertEqual(model.calls, [])

    def test_caption_reaches_the_model_as_text(self):
        _, model = self.run_model("Photo\nQuanto custa um site assim pra minha loja de roupas?",
                                  {"intent": "price", "messages": ["Ok"]})
        self.assertIn("[mídia anexada] Quanto custa", model.calls[0]["messages"][1]["content"])

    def test_negotiation_goes_to_the_owner_even_if_the_model_answers(self):
        decision, _ = self.run_model("Faz mais barato?", {
            "intent": "price", "messages": ["O site fica em média R$ 500."]})
        self.assertEqual((decision.intent, decision.action), ("negotiation", "handoff"))

    def test_local_buying_signal_is_never_weakened_by_the_model(self):
        for answer in ({"intent": "unknown", "messages": []},
                       {"intent": "price", "messages": ["O site fica em média R$ 500."]}):
            decision, _ = self.run_model("Gostei muito dos exemplos que você mandou, quero fechar. "
                                         "Como faço pra pagar a entrada?", answer)
            self.assertEqual((decision.intent, decision.priority), ("ready_to_buy", "hot"))

    def test_fixed_owner_answer_beats_a_model_unknown(self):
        decision, _ = self.run_model("E aplicativo?", {"intent": "unknown", "messages": []})
        self.assertEqual((decision.intent, decision.action), ("system_request", "reply"))
        self.assertEqual(decision.messages, list(self.rules.intent("system_request").messages))

    def test_short_decisive_messages_never_call_the_model(self):
        decision, model = self.run_model("Não, obrigado", {"intent": "interested"})
        self.assertEqual(model.calls, [])
        self.assertEqual(decision.action, "block")


if __name__ == "__main__":
    unittest.main()
