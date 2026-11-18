"""App/system requirements interview (owner, 2026-11-18) and the Central ficha export."""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sales_fixtures import PHONES, Clock, FakeChannel, FakeModel
from tools.ytbot.commercial.whatsapp.sales import central, dossier
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore

JPEG = b"\xff\xd8\xff\xe0fixture-image"


def brief(**changes):
    data = json.loads(json.dumps(dossier.SYSTEM_SCHEMA))
    data["empresa"]["nome"] = "Barbearia Navalha"
    data["projeto"].update(tipo="aplicativo de celular", objetivo="agenda online",
                           funcionalidades=["clientes marcam horário pelo celular"])
    data["faltando"] = ["como isso é feito hoje", "onde vai usar"]
    data["proxima_pergunta"] = ("Entendi, então os clientes vão marcar o horário pelo celular. "
                                "Hoje vocês anotam os horários onde, e quem vai usar o sistema?")
    for key, value in changes.items():
        data[key] = value
    return data


SUMMARY = ("Você precisa de um aplicativo para os clientes marcarem horário pelo celular. "
           "Quem usa são você e os barbeiros, que hoje anotam tudo no caderno.")
SUMMARY_PIX = SUMMARY + " O cliente também paga pelo Pix na hora de marcar."


class InterviewTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = SalesStore(Path(self.directory.name) / "whatsapp")
        self.store.import_rows([{"name": "Barbearia Navalha", "phone": PHONES[0],
                                 "category": "Barbearia", "city": "Cuiabá"}],
                               Clock().now)
        self.lead = next(iter(self.store.leads().values()))
        self.clock = Clock()
        self.notes = []
        self.model = FakeModel()
        self.channel = FakeChannel(self.store.journal_path, media={"m1": (JPEG, ".jpg")})
        self.agent = SalesAgent(self.rules, self.store, self.channel, self.model, live=True,
                                clock=self.clock, sleep=lambda seconds: None,
                                notify=self.notes.append, log=lambda message: None)
        self.agent.prospect()
        self.count = 0

    def tearDown(self):
        self.directory.cleanup()

    def say(self, text, *answers):
        self.count += 1
        self.model.answers = list(answers)
        self.clock.now = self.clock.now + timedelta(minutes=1)
        self.agent.ingest([{"id": f"e{self.count}", "chat": "+55 65 90000-0001", "text": text}])
        return self.agent.reply_pending()

    def lead_now(self):
        return self.store.lead(self.lead["id"])

    def sent(self):
        return [item["text"] for item in self.channel.sent]

    def offered(self):
        self.say("Vocês fazem aplicativo de agendamento para a barbearia?",
                 {"intent": "system_request", "messages": []})
        self.assertEqual(self.sent()[-1], "Você gostaria que eu fizesse um orçamento?")

    def test_interview_restates_confirms_and_then_hands_over_the_full_ficha(self):
        self.offered()
        self.say("Sim", {"intent": "quote_accept", "messages": []}, brief())
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.assertEqual(self.sent()[-2:], self.rules.brief_system["start"]
                         + [brief()["proxima_pergunta"]])
        done = brief(faltando=[], proxima_pergunta="", confirmacao=SUMMARY,
                     duvidas_do_cliente=["Manda lembrete no WhatsApp?"])
        self.say("No caderno, somos eu e dois barbeiros. Manda lembrete no WhatsApp?", done)
        texts = self.rules.brief_system
        self.assertEqual(self.sent()[-3:], [texts["confirm_intro"], SUMMARY,
                                            texts["confirm_question"]])
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.assertEqual(self.notes, [], "the owner is not called before the client confirms")
        fixed = brief(faltando=[], proxima_pergunta="", confirmacao=SUMMARY_PIX,
                      duvidas_do_cliente=["Manda lembrete no WhatsApp?"])
        self.say("Faltou: quero receber pelo Pix na hora de marcar", fixed)
        self.assertEqual(self.sent()[-2], SUMMARY_PIX)
        self.say("Isso mesmo, está certo", fixed)
        lead = self.lead_now()
        self.assertEqual(lead["state"], "quote-requested")
        self.assertEqual(self.sent()[-1], texts["done_messages"][0])
        self.assertEqual(self.notes[-1]["priority"], "hot")
        folder = dossier.client_dir(self.store.root, lead)
        ficha = (folder / "ficha.md").read_text(encoding="utf-8")
        self.assertIn("aplicativo ou sistema", ficha)
        self.assertIn("clientes marcam horário pelo celular", ficha)
        self.assertIn("Manda lembrete no WhatsApp?", ficha)
        record = json.loads((folder / "ficha.json").read_text(encoding="utf-8"))
        self.assertEqual(record["tipo"], "sistema")
        self.assertEqual(record["status"], "pronta para orçamento")

    def test_a_system_question_outside_the_facts_starts_the_interview_not_a_handoff(self):
        self.offered()
        question = brief(duvidas_do_cliente=["Emite nota fiscal?"])
        self.say("E o aplicativo consegue emitir nota fiscal?",
                 {"intent": "unknown", "messages": [], "handoff": True}, question)
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.assertEqual(self.notes, [])
        self.assertIn(self.rules.brief_system["start"][0], self.sent())

    def test_describing_the_system_again_after_the_offer_starts_the_interview(self):
        self.offered()
        self.say("Precisa ter cadastro dos clientes e lembrete no WhatsApp",
                 {"intent": "system_request", "messages": []}, brief())
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.assertEqual(self.lead_now()["brief_kind"], "system")

    def test_a_summary_with_numbers_is_not_sent_and_the_safe_one_is_used(self):
        self.offered()
        self.say("Sim", {"intent": "quote_accept", "messages": []}, brief())
        unsafe = brief(faltando=[], proxima_pergunta="", resumo=SUMMARY,
                       confirmacao="Serão 50 clientes por dia no aplicativo.")
        self.say("Uns 50 clientes por dia, é isso", unsafe)
        self.assertIn(SUMMARY, self.sent())
        self.assertNotIn("Serão 50 clientes por dia no aplicativo.", self.sent())

    def test_closing_in_the_middle_keeps_asking_and_ends_as_buying(self):
        self.offered()
        self.say("Sim", {"intent": "quote_accept", "messages": []}, brief())
        self.say("Quero fechar, como faço?", {"intent": "ready_to_buy", "messages": []}, brief())
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.assertTrue(self.lead_now()["buy_intent"])
        done = brief(faltando=[], proxima_pergunta="", confirmacao=SUMMARY)
        self.say("Hoje é no caderno, só no celular", done)
        self.say("Sim, certo", done)
        self.assertEqual(self.lead_now()["state"], "buying")
        self.assertEqual(self.sent()[-1], self.rules.brief_system["done_messages_buy"][0])

    def test_central_lists_the_ficha_with_its_fields_and_media(self):
        self.offered()
        self.say("Sim", {"intent": "quote_accept", "messages": []}, brief())
        self.channel.bubbles = [{"dir": "in", "text": "", "id": "m1", "media": "image"}]
        self.say("Segue a logo", brief(resumo="Agenda online para a barbearia."))
        data = central.snapshot(self.store, self.clock())
        [ficha] = data["fichas"]
        self.assertEqual((ficha["kind"], ficha["status"]), ("sistema", "coletando dados"))
        self.assertEqual(ficha["resumo"], "Agenda online para a barbearia.")
        titles = [section["title"] for section in ficha["sections"]]
        self.assertIn("Funções pedidas", titles)
        self.assertEqual(ficha["pendencias"], brief()["faltando"])
        [media] = ficha["media"]
        self.assertEqual(media["kind"], "image")
        self.assertEqual(Path(media["path"]).read_bytes(), JPEG)
        self.assertTrue(Path(media["path"]).is_relative_to(ficha["folder"]))

    def test_central_drops_media_outside_the_client_folder(self):
        folder = Path(self.directory.name) / "whatsapp" / "sales" / "clientes" / "x-L1"
        folder.mkdir(parents=True)
        (folder / "ficha.json").write_text(json.dumps({
            "status": "coletando dados", "gerada_em": "2026-11-18T09:00:00",
            "ficha": {}, "arquivos": [{"tipo": "image", "arquivo": "../../../segredo.txt"}]}))
        lead = {"id": "L1", "state": "qualifying", "ficha": str(folder / "ficha.md")}
        contact = {"label": "x-1", "name": "X", "phone": "", "wa_link": ""}
        self.assertEqual(central.ficha_entry(folder, lead, contact)["media"], [])

    def test_central_keeps_a_ficha_after_its_lead_was_reset(self):
        self.offered()
        self.say("Sim", {"intent": "quote_accept", "messages": []}, brief())
        self.store.update_lead(self.lead["id"], ficha=None, state="new")
        [ficha] = central.snapshot(self.store, self.clock())["fichas"]
        self.assertEqual((ficha["lead"], ficha["label"]), (self.lead["id"], "barbearia-1"))

    def test_unusual_platform_request_starts_interview_directly_with_questions(self):
        question = brief(
            empresa={"nome": None, "segmento": "Entretenimento", "cidade": None,
                     "sobre_e_diferenciais": None},
            projeto={"tipo": "plataforma web", "objetivo": "site de cassino",
                     "como_faz_hoje": "Projeto novo", "funcionalidades": []},
            duvidas_do_cliente=["Fazem site de cassino?"],
            faltando=["como o sistema deve funcionar", "quais jogos e pagamentos precisa ter"],
            proxima_pergunta=("Entendi que você pensa em um site de cassino. Como exatamente "
                              "você imagina esse sistema funcionando na prática e quais jogos "
                              "ou funções principais ele precisa ter?"),
        )
        self.say("Fazem site de cassino?",
                 {"intent": "unknown", "messages": [], "handoff": True}, question)
        lead = self.lead_now()
        self.assertEqual((lead["state"], lead["brief_kind"], lead["interest"]),
                         ("qualifying", "system", "system"))
        self.assertEqual(self.notes, [], "unusual request must interview before calling the owner")
        self.assertEqual(self.sent()[-2:], self.rules.brief_system["start_custom"]
                         + [question["proxima_pergunta"]])

        done = brief(
            faltando=[], proxima_pergunta="",
            confirmacao=("Você precisa de uma plataforma web com jogos estilo tigrinho e roleta, "
                         "cadastro de jogadores, depósitos por Pix e painel para acompanhar tudo."),
        )
        self.say("Quero jogos tipo tigrinho e roleta, cadastro de usuários, Pix e painel admin",
                 done)
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.say("Isso mesmo, está certo", done)
        self.assertEqual(self.lead_now()["state"], "quote-requested")
        self.assertEqual(self.notes[-1]["priority"], "hot")

    def test_unusual_platform_without_model_uses_custom_fallback_questions(self):
        offline = SalesAgent(self.rules, self.store, self.channel, None, live=True,
                             clock=self.clock, sleep=lambda seconds: None,
                             notify=self.notes.append, log=lambda message: None)
        self.count += 1
        offline.ingest([{"id": f"e{self.count}", "chat": "+55 65 90000-0001",
                         "text": "Fazem site de tigrinho?"}])
        offline.reply_pending()
        lead = self.lead_now()
        self.assertEqual((lead["state"], lead["brief_kind"], lead["interest"]),
                         ("qualifying", "system", "system"))
        self.assertEqual(self.sent()[-2:], self.rules.brief_system["start_custom"]
                         + [self.rules.brief_system["first_question_custom"]])

    def test_closing_a_custom_platform_never_sends_site_pix_keys(self):
        self.say("Quero fechar um site de cassino",
                 {"intent": "ready_to_buy", "messages": []}, brief())
        self.assertEqual(self.lead_now()["state"], "qualifying")
        self.assertTrue(self.lead_now()["buy_intent"])
        self.assertNotIn("financeiro@zaflas.com.br", self.sent())

    def test_informal_confirmation_slang_finishes_on_first_reply_and_keeps_corrections(self):
        self.say("Fazem site de cassino?",
                 {"intent": "custom_platform", "messages": []}, brief())
        ready = brief(
            empresa={"nome": "Zaflas Restaurantes", "segmento": "Restaurante", "cidade": "Cuiabá",
                     "sobre_e_diferenciais": None},
            projeto={"tipo": "site de cassino",
                     "objetivo": "criar um site de cassino com sistema de tigrinho",
                     "como_faz_hoje": "Projeto novo",
                     "usuarios": ["jogadores", "equipe de gerenciamento"],
                     "quantidade_de_usuarios": "1000 pessoas",
                     "funcionalidades": ["sistema de tigrinho", "100% self service"],
                     "plataformas": ["navegador do computador"],
                     "integracoes": ["Pix", "cartão", "boleto"]},
            duvidas_do_cliente=["Se fazem site de cassino"],
            faltando=[],
            proxima_pergunta="",
            confirmacao=("Entendi que você precisa de um site de cassino com sistema de tigrinho, "
                         "totalmente self service, rodando no navegador e ligado a Pix, cartão e boleto."),
        )
        self.say("tigrinho self service, mil pessoas no navegador, jogadores e equipe, Pix cartão boleto",
                 ready)
        self.assertEqual(self.lead_now()["collect_stage"], "confirming")
        # A correction with slang ("Beleza, mas faltou...") must update, not confirm prematurely.
        self.say("Beleza, mas faltou relatório diário", ready)
        self.assertEqual(self.lead_now()["collect_stage"], "confirming")
        self.assertEqual(self.lead_now()["state"], "qualifying")
        # Informal PT-BR confirmation ("Issae chefia") must confirm immediately without repeating.
        self.say("Issae chefia", ready)
        lead = self.lead_now()
        self.assertEqual(lead["state"], "quote-requested")
        self.assertEqual(self.notes[-1]["priority"], "hot")
        ficha = Path(lead["ficha"]).read_text(encoding="utf-8")
        self.assertIn("1000 pessoas", ficha)
        self.assertIn("Se fazem site de cassino", ficha)
        self.assertIn("Pix; cartão; boleto", ficha)

    def test_ready_to_buy_at_confirmation_stage_finishes_as_buying(self):
        self.offered()
        self.say("Sim", {"intent": "quote_accept", "messages": []}, brief())
        done = brief(faltando=[], proxima_pergunta="", confirmacao=SUMMARY)
        self.say("Tudo certo, só isso", done)
        self.assertEqual(self.lead_now()["collect_stage"], "confirming")
        self.say("Quero fechar, pode começar", {"intent": "ready_to_buy", "messages": []}, done)
        self.assertEqual(self.lead_now()["state"], "buying")
        self.assertEqual(self.sent()[-1], self.rules.brief_system["done_messages_buy"][0])


if __name__ == "__main__":
    unittest.main()
