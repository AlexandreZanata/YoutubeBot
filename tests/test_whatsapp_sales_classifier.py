import unittest

from tools.ytbot.commercial.whatsapp.sales import classifier
from tools.ytbot.commercial.whatsapp.sales.rules import load

OFFER = [{"dir": "out", "text": "Você gostaria que eu fizesse um orçamento?", "state": "sent"}]


class SalesClassifierTests(unittest.TestCase):
    rules = load()

    def check(self, text, expected, history=None, state="engaged"):
        self.assertEqual(classifier.classify(self.rules, text, history, state), expected, text)

    def test_portuguese_messages_map_to_rule_intents(self):
        cases = {
            "Nesse momento não estou precisando": "refusal",
            "Não, obrigado": "refusal",
            "agora não": "refusal",
            "Não tenho interesse": "refusal",
            "Para de me mandar mensagem": "opt_out",
            "isso é spam": "opt_out",
            "Olá! Esta é uma mensagem automática. Retornaremos em breve.": "auto_reply",
            "Isso é robô?": "bot_question",
            "é mensagem automática?": "bot_question",
            "Como você conseguiu meu número?": "how_got_number",
            "quem é?": "who_are_you",
            "Me liga depois do almoço": "call_request",
            "Audio": "audio",
            "0:12": "audio",
            "Photo": "media",
            "Sticker": "sticker",
            "Já temos site": "already_has_site",
            "vou pensar": "later",
            "Vocês fazem aplicativo de delivery?": "system_request",
            "quero um site simples": "site_institutional",
            "Quanto custa?": "price",
            "qual o prazo?": "deadline",
            "aceita pix?": "payment",
            "tem mais exemplos?": "examples",
            "tenho interesse": "interested",
            "Tudo bem e você?": "greeting_reply",
            "Obrigado!": "thanks",
            "Vocês atendem em Sinop?": "unknown",
        }
        for text, expected in cases.items():
            self.check(text, expected)

    def test_short_answers_read_the_offer_question(self):
        self.check("Sim", "quote_accept", OFFER)
        self.check("pode sim", "quote_accept", OFFER)
        self.check("Não", "refusal", OFFER)

    def test_qualifying_text_is_the_project_description(self):
        self.check("Barbearia, quero agendamento online e lembrete", "quote_details",
                   state="qualifying")
        self.check("é robô?", "bot_question", state="qualifying")

    def test_only_short_messages_are_decided_locally(self):
        self.assertTrue(classifier.decisive("refusal", "Não, obrigado"))
        long_text = "Não quero só um site simples, quero um sistema de agendamento completo " * 2
        self.assertFalse(classifier.decisive("refusal", long_text))
        self.assertFalse(classifier.decisive("price", "Quanto custa?"))


if __name__ == "__main__":
    unittest.main()
