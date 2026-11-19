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
            "Fazem site de cassino?": "custom_platform",
            "Tenho interesse. Vocês fazem site de tigrinho?": "custom_platform",
            "Vocês fazem plataforma de rifas ou marketplace?": "custom_platform",
            "quero um site simples": "site_institutional",
            "Quanto custa?": "price",
            "qual o prazo?": "deadline",
            "aceita pix?": "payment",
            "O que é domínio?": "domain",
            "O domínio está incluso no valor?": "domain",
            "Como funciona o registro.br?": "domain",
            "quanto custa o servidor por mês?": "hosting",
            "tem mais exemplos?": "examples",
            "tenho interesse": "interested",
            "Tudo bem e você?": "greeting_reply",
            "Pois não?": "greeting_reply",
            "Pode falar": "greeting_reply",
            "Obrigado!": "thanks",
            "obg": "thanks",
            "Entendi": "thanks",
            "kkkk": "thanks",
            "Vocês atendem em Sinop?": "unknown",
        }
        for text, expected in cases.items():
            self.check(text, expected)

    def test_moments_that_need_the_owner(self):
        cases = {
            "Quero falar com o Alexandre mesmo, não com robô": "human_request",
            "Isso é golpe?": "trust_concern",
            "Tá caro, faz por 300?": "negotiation",
            "Dá pra parcelar no cartão em 10x?": "negotiation",
            "Quero fechar, como faço pra pagar a entrada?": "ready_to_buy",
            "Agora estou ocupado, me chama amanhã": "callback_later",
            "Agora não posso, me chama amanhã": "callback_later",
            "Não me chama agora, me chama amanhã": "callback_later",
            "Nesse momento não posso falar": "callback_later",
            "Você é um robô? quero falar com gente": "human_request",
            "Não entendi": "confused",
            "Como assim?": "confused",
        }
        for text, expected in cases.items():
            self.check(text, expected)

    def test_links_that_do_not_open_get_the_save_contact_answer(self):
        for text in ("eu não estou conseguindo abrir o link de exemplos", "os links não abrem",
                     "não consigo ver os exemplos", "o site não abre aqui",
                     "não dá pra clicar no link", "link bloqueado"):
            self.check(text, "links_not_opening")
        self.check("não consegui abrir os sites", "links_not_opening", state="qualifying")
        self.check("Não quero site, quero um aplicativo", "system_request")
        self.check("não consigo agora, me chama amanhã", "callback_later")

    def test_app_prices_are_never_confused_with_the_site(self):
        self.check("Então um aplicativo sai 500 reais?", "app_at_site_price")
        self.check("por 500 faz um app?", "app_at_site_price")
        self.check("Quanto custa um aplicativo?", "system_price")
        self.check("Vocês fazem aplicativo de delivery?", "system_request")
        self.check("Quanto custa um site?", "site_institutional")
        self.assertTrue(self.rules.intent("app_at_site_price").messages[0].startswith("Não"))

    def test_busy_or_redirecting_messages_are_never_refusals(self):
        for text in ("Agora não posso, me chama amanhã", "Não quero site, quero um aplicativo",
                     "Não me chama agora, me chama amanhã", "Nesse momento não posso falar"):
            self.assertNotIn(classifier.classify(self.rules, text, None, "engaged"),
                             ("refusal", "opt_out"), text)
        self.check("Não me chama mais", "opt_out")
        self.check("Não quero, obrigado", "refusal")

    def test_short_answers_read_the_offer_question(self):
        self.check("Sim", "quote_accept", OFFER)
        self.check("pode sim", "quote_accept", OFFER)
        self.check("Issae", "quote_accept", OFFER)
        self.check("Fechou", "quote_accept", OFFER)
        self.check("Show", "quote_accept", OFFER)
        self.check("Não", "refusal", OFFER)

    def test_qualifying_text_is_the_project_description(self):
        self.check("Barbearia, quero agendamento online e lembrete", "quote_details",
                   state="qualifying")
        self.check("Photo\nEstúdio de fotos, atendo segunda a sexta", "quote_details",
                   state="qualifying")
        self.check("Photo", "quote_details", state="qualifying")
        self.check("No site coloca o WhatsApp (66) 99999-1234", "quote_details",
                   state="qualifying")
        self.check("Agora não", "quote_details", state="qualifying")
        self.check("Não, obrigado, é só isso", "quote_details", state="qualifying")
        self.check("Pode fazer!", "quote_details", state="qualifying")
        self.check("Desisti, não tenho interesse", "refusal", state="qualifying")
        self.check("Para de me mandar mensagem", "opt_out", state="qualifying")
        self.check("[imagem]", "media", state="engaged")
        self.check("é robô?", "bot_question", state="qualifying")

    def test_only_short_messages_are_decided_locally(self):
        self.assertTrue(classifier.decisive("refusal", "Não, obrigado"))
        long_text = "Não quero só um site simples, quero um sistema de agendamento completo " * 2
        self.assertFalse(classifier.decisive("refusal", long_text))
        self.assertFalse(classifier.decisive("price", "Quanto custa?"))

    def test_forwarding_to_responsible_maps_to_forwarded_to_decider_without_breaking_guards(self):
        for text in (
            "Irei encaminhar para o responsável!!",
            "Vou encaminhar para o responsável",
            "Estarei encaminhando para a diretoria",
            "Vou encaminhar pro setor de marketing",
            "Já encaminhei pro dono",
            "Encaminhei para a gerência",
            "Vou repassar para o responsável",
            "Irei passar para o responsável",
            "Vou passar para o responsável",
            "Vou encaminhar!",
            "Já encaminhei",
        ):
            self.check(text, "forwarded_to_decider")
        self.assertTrue(classifier.decisive("forwarded_to_decider", "Irei encaminhar para o responsável!!"))
        self.check("Vou encaminhar, mas pode chamar no (65) 90000-0009", "referral")
        self.check("Não temos interesse, não vou encaminhar", "refusal")
        self.check("Esta é uma mensagem automática. Encaminharemos para o setor responsável.", "auto_reply")
        self.check("Encaminhei o comprovante pro financeiro", "payment_sent")
        self.check("Vou encaminhar a logo pro marketing", "quote_details", state="qualifying")
        self.check("Sou funcionária, o dono não está", "gatekeeper")
        self.check("Vou passar pra doutora ver", "gatekeeper")
        self.check("Vou passar pro dono, ele te chama", "gatekeeper")
        self.check("Quero falar com o responsável", "human_request")
        for msg in ("Muito obrigado", "Muito obrigada!"):
            self.check(msg, "thanks")
            self.assertTrue(classifier.decisive("thanks", msg))
        self.check("No momento não tenho interesse\nMuito obrigado", "refusal")
        self.assertTrue(classifier.decisive("refusal", "No momento não tenho interesse\nMuito obrigado"))


if __name__ == "__main__":
    unittest.main()
