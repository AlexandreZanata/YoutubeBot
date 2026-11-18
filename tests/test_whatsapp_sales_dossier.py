import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from sales_fixtures import MONDAY, Clock, FakeChannel, FakeModel, lead_rows, write_csv
from tools.ytbot.commercial.whatsapp.sales import dossier
from tools.ytbot.commercial.whatsapp.sales.agent import SalesAgent, owner_reset
from tools.ytbot.commercial.whatsapp.sales.rules import load
from tools.ytbot.commercial.whatsapp.sales.store import SalesStore

JPEG = b"\xff\xd8\xff\xe0fake-logo"
OGG = b"OggSfake-voice"
BRIEF_PARTIAL = {
    "empresa": {"nome": "Barbearia Navalha", "segmento": "Barbearia", "cidade": None},
    "pedido": {"tipo": "site institucional", "servicos_ou_produtos": ["corte", "barba"]},
    "contato_no_site": {}, "materiais_citados": ["logo"], "resumo": "Site com serviços.",
    "faltando": ["contato para o site (WhatsApp, endereço ou horário de atendimento)"],
    "cliente_terminou": False,
    "proxima_pergunta": "Perfeito! Qual endereço e horário de atendimento vão no site?",
}
BRIEF_DONE = {
    **BRIEF_PARTIAL,
    "contato_no_site": {"endereco": "Rua das Flores, 10", "horario": "seg a sex 9h às 19h"},
    "faltando": [], "cliente_terminou": True, "proxima_pergunta": "",
}


class ClientDossierTests(unittest.TestCase):
    rules = load()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = SalesStore(Path(self.directory.name) / "whatsapp")
        self.clock = Clock()
        self.notes = []
        self.transcribed = []
        self.store.import_csv(write_csv(Path(self.directory.name) / "l.csv", lead_rows(1)),
                              self.clock())
        self.lead = next(iter(self.store.leads().values()))

    def tearDown(self):
        self.directory.cleanup()

    def transcriber(self, path):
        self.transcribed.append(path)
        if path.read_bytes() != OGG:
            raise RuntimeError("cannot decode")
        return "Quanto custa um site para a minha barbearia?"

    def agent(self, channel, model=None):
        return SalesAgent(self.rules, self.store, channel, model, live=True, clock=self.clock,
                          sleep=lambda seconds: None, notify=self.notes.append,
                          log=lambda message: None, transcriber=self.transcriber)

    def event(self, text, event_id):
        return {"id": event_id, "chat": "+55 65 90000-0001", "text": text}

    def qualifying(self, channel, model=None):
        if model is not None:
            model.answers = [
                {"intent": "site_institutional", "messages": []},
                {"intent": "quote_accept", "messages": [
                    "Ótimo! Me conta o nome da empresa e o que o site deve mostrar?"]}]
        agent = self.agent(channel, model)
        agent.prospect()
        agent.ingest([self.event("Quero um site para a barbearia", "e1")])
        agent.reply_pending()
        agent.ingest([self.event("Sim", "e2")])
        agent.reply_pending()
        self.assertEqual(self.store.lead(self.lead["id"])["state"], "qualifying")
        return agent

    def test_voice_message_is_transcribed_and_answered(self):
        channel = FakeChannel(self.store.journal_path, media={"m1": (OGG, ".ogg")},
                              bubbles=[{"dir": "in", "text": "", "id": "m1", "media": "audio"}])
        agent = self.agent(channel)
        agent.prospect()
        agent.ingest([self.event("0:07", "e1")])
        result = agent.reply_pending()[0]
        self.assertEqual(result["intent"], "site_institutional")
        history = self.store.history(self.lead["id"])
        voice = next(entry for entry in history if entry.get("media") == "audio")
        self.assertEqual(voice["text"], "Quanto custa um site para a minha barbearia?")
        self.assertTrue((dossier.client_dir(self.store.root, self.lead) / voice["file"]).is_file())
        self.assertNotIn("0:07", [entry["text"] for entry in
                                  agent_effective(history)])

    def test_untranscribable_audio_goes_to_the_owner(self):
        channel = FakeChannel(self.store.journal_path, media={"m1": (b"broken", ".ogg")},
                              bubbles=[{"dir": "in", "text": "", "id": "m1", "media": "audio"}])
        agent = self.agent(channel)
        agent.prospect()
        agent.ingest([self.event("0:07", "e1")])
        self.assertEqual(agent.reply_pending()[0]["intent"], "audio")
        self.assertEqual(self.notes[-1]["reason"], "Mandou áudio")

    def test_collection_asks_what_is_missing_then_writes_the_ficha(self):
        channel = FakeChannel(self.store.journal_path, media={"m1": (JPEG, ".jpg")})
        model = FakeModel()
        agent = self.qualifying(channel, model)
        model.answers = [BRIEF_PARTIAL]
        channel.bubbles = [{"dir": "out", "text": "Ótimo!", "id": "o1"},
                           {"dir": "in", "text": "Barbearia Navalha, corte e barba. Segue a logo",
                            "id": "m0"},
                           {"dir": "in", "text": "", "id": "m1", "media": "image"}]
        agent.ingest([self.event("Barbearia Navalha, corte e barba. Segue a logo", "e3")])
        agent.reply_pending()
        self.assertEqual(channel.sent[-1]["text"], BRIEF_PARTIAL["proxima_pergunta"])
        self.assertEqual(self.store.lead(self.lead["id"])["state"], "qualifying")
        model.answers = [BRIEF_DONE]
        channel.bubbles = [{"dir": "out", "text": BRIEF_PARTIAL["proxima_pergunta"], "id": "o2"},
                           {"dir": "in", "text": "Rua das Flores, 10. Seg a sex 9h às 19h. É isso",
                            "id": "m2"}]
        agent.ingest([self.event("Rua das Flores, 10. Seg a sex 9h às 19h. É isso", "e4")])
        agent.reply_pending()
        lead = self.store.lead(self.lead["id"])
        self.assertEqual(lead["state"], "quote-requested")
        folder = dossier.client_dir(self.store.root, lead)
        ficha = (folder / "ficha.md").read_text(encoding="utf-8")
        self.assertIn("Barbearia Navalha", ficha)
        self.assertIn("Rua das Flores, 10", ficha)
        self.assertIn("pronta para orçamento", ficha)
        record = json.loads((folder / "ficha.json").read_text(encoding="utf-8"))
        self.assertEqual(len(record["arquivos"]), 1)
        self.assertEqual((folder / record["arquivos"][0]["arquivo"]).read_bytes(), JPEG)
        self.assertIn("Cliente: Rua das Flores", (folder / "conversa.md").read_text("utf-8"))
        self.assertEqual(self.notes[-1]["ficha"], str(folder / "ficha.md"))
        self.assertEqual(oct((folder / "ficha.md").stat().st_mode & 0o777), "0o600")

    def test_question_with_a_price_is_replaced_by_the_rules_text(self):
        channel = FakeChannel(self.store.journal_path)
        model = FakeModel()
        agent = self.qualifying(channel, model)
        model.answers = [{**BRIEF_PARTIAL, "proxima_pergunta": "Fica R$ 300, me manda o endereço?"}]
        agent.ingest([self.event("Barbearia Navalha", "e3")])
        agent.reply_pending()
        self.assertEqual(channel.sent[-1]["text"], self.rules.brief["fallback_question"])

    def test_late_material_updates_the_folder_without_messages(self):
        channel = FakeChannel(self.store.journal_path, media={"m9": (JPEG, ".jpg")})
        agent = self.qualifying(channel)
        agent.ingest([self.event("Barbearia Navalha", "e3")])
        agent.reply_pending()
        agent.ingest([self.event("é isso", "e4")])
        agent.reply_pending()
        self.assertEqual(self.store.lead(self.lead["id"])["state"], "quote-requested")
        sent = len(channel.sent)
        channel.bubbles = [{"dir": "out", "text": "Perfeito, anotei tudo!", "id": "o9"},
                           {"dir": "in", "text": "", "id": "m9", "media": "image"}]
        self.clock.now = MONDAY + timedelta(hours=1)
        agent.ingest([self.event("Photo", "e5")])
        agent.reply_pending()
        self.assertEqual(len(channel.sent), sent)
        record = json.loads((dossier.client_dir(self.store.root, self.lead) / "ficha.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "orçamento com o dono")
        self.assertEqual(len(record["arquivos"]), 1)
        self.assertEqual(self.notes[-1]["reason"], "Cliente mandou mais material para o orçamento")

    def test_album_saves_every_photo(self):
        channel = FakeChannel(self.store.journal_path,
                              media={"m1": [(JPEG, ".jpg"), (JPEG + b"2", ".jpg"),
                                            (JPEG + b"3", ".jpg")]})
        agent = self.qualifying(channel)
        channel.bubbles = [{"dir": "out", "text": "Ótimo!", "id": "o1"},
                           {"dir": "in", "text": "", "id": "m1", "media": "image"}]
        agent.ingest([self.event("Photo", "e3")])
        agent.reply_pending()
        record = json.loads((dossier.client_dir(self.store.root, self.lead) / "ficha.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(len(record["arquivos"]), 3)

    def test_owner_resolve_resumes_the_collection_with_pending_messages(self):
        from tools.ytbot.commercial.whatsapp.sales.agent import owner_resolve
        channel = FakeChannel(self.store.journal_path)
        agent = self.qualifying(channel)
        self.store.update_lead(self.lead["id"], state="unconfirmed", awaiting=None)
        agent.ingest([self.event("Barbearia Navalha, corte e barba", "e3")])
        self.assertEqual(agent.reply_pending(), [])
        owner_resolve(self.store, self.lead["id"], "qualifying")
        sent = len(channel.sent)
        agent.reply_pending()
        self.assertGreater(len(channel.sent), sent)
        self.assertEqual(channel.sent[-1]["text"], self.rules.brief["fallback_question"])

    def test_owner_test_reset_sends_the_opening_again(self):
        channel = FakeChannel(self.store.journal_path)
        agent = self.agent(channel)
        agent.prospect()
        self.assertEqual(agent.prospect(), [])
        owner_reset(self.store, self.lead["id"])
        self.assertTrue(self.store.history_path(self.lead["id"])
                        .with_name(f"{self.lead['id']}.cycle0.jsonl").is_file())
        self.clock.now = MONDAY + timedelta(days=1)
        self.assertEqual(agent.prospect()[0]["state"], "opened")
        self.assertEqual(len(channel.sent), 16)

    def test_complete_ficha_collects_colors_visual_style_and_explains_domain(self):
        channel = FakeChannel(self.store.journal_path)
        model = FakeModel()
        agent = self.qualifying(channel, model)
        model.answers = [{
            "empresa": {"nome": "Padaria Pão Quente", "segmento": "Padaria"},
            "pedido": {"tipo": "site institucional", "servicos_ou_produtos": ["pães", "bolos"]},
            "contato_no_site": {"endereco": "Av. Brasil, 500", "horario": "6h às 20h",
                                "whatsapp": "(65) 90000-0011"},
            "identidade_visual": {"cores_principais": "marrom e creme",
                                  "estilo_visual": "aconchegante e limpo",
                                  "preferencia_fundo": "claro"},
            "faltando": ["domínio desejado"],
            "pedir_dominio": True,
            "cliente_terminou": False,
            "proxima_pergunta": "E sobre o domínio do site, qual nome você pensou?",
        }]
        agent.ingest([self.event("Padaria Pão Quente, marrom e creme, visual limpo", "e3")])
        agent.reply_pending()
        recent_sent = [item["text"] for item in channel.sent[-4:]]
        self.assertIn("https://registro.br/", recent_sent)
        self.assertTrue(any("R$ 40" in msg and "1 ano" in msg for msg in recent_sent))
        model.answers = [{
            "empresa": {"nome": "Padaria Pão Quente", "segmento": "Padaria"},
            "pedido": {"tipo": "site institucional", "servicos_ou_produtos": ["pães", "bolos"]},
            "contato_no_site": {"endereco": "Av. Brasil, 500", "horario": "6h às 20h",
                                "whatsapp": "(65) 90000-0011"},
            "identidade_visual": {"cores_principais": "marrom e creme",
                                  "estilo_visual": "aconchegante e limpo",
                                  "preferencia_fundo": "claro"},
            "dominio": {"ja_possui": "Não", "nome_desejado": "padariapaoquente.com.br",
                        "opcao_compra": "Zaflas compra (+R$ 40 na 1ª mensalidade por 1 ano)"},
            "resumo": "Site institucional limpo em marrom e creme; Zaflas compra o domínio.",
            "faltando": [], "pedir_dominio": False, "cliente_terminou": False,
            "proxima_pergunta": "",
        }]
        agent.ingest([self.event("Quero padariapaoquente.com.br e vocês compram", "e4")])
        agent.reply_pending()
        lead = self.store.lead(self.lead["id"])
        self.assertEqual(lead["state"], "quote-requested")
        ficha = (dossier.client_dir(self.store.root, lead) / "ficha.md").read_text("utf-8")
        self.assertIn("marrom e creme", ficha)
        self.assertIn("aconchegante e limpo", ficha)
        self.assertIn("padariapaoquente.com.br", ficha)
        self.assertIn("Zaflas compra", ficha)

    def test_refused_number_cannot_be_reset(self):
        self.store.add_dnc(self.lead["phone"], "refusal", MONDAY)
        with self.assertRaises(ValueError):
            owner_reset(self.store, self.lead["id"])


def agent_effective(history):
    from tools.ytbot.commercial.whatsapp.sales.context import effective
    return effective(history)


if __name__ == "__main__":
    unittest.main()
