import unittest
from datetime import datetime

from tools.ytbot.commercial.whatsapp.sales import notify


class HandoffNotificationTests(unittest.TestCase):
    def test_phones_are_formatted_for_the_owner(self):
        self.assertEqual(notify.format_phone("556696384527"), "+55 66 9638-4527")
        self.assertEqual(notify.format_phone("5565900000001"), "+55 65 90000-0001")
        self.assertEqual(notify.wa_link("5565900000001"), "https://wa.me/5565900000001")

    def test_notification_text_has_contact_reason_and_link(self):
        lead = {"id": "L1", "name": "Barbearia Teste", "phone": "5565900000001",
                "state": "needs-owner"}
        history = [{"dir": "out", "text": "Boa tarde", "state": "sent"},
                   {"dir": "in", "text": "Tá caro, faz por 300?"}]
        entry = notify.handoff_entry(lead, history, "Negociação de preço ou pagamento", "needed",
                                     "negotiation", "Tá caro, faz por 300?",
                                     datetime(2026, 11, 17, 15, 30))
        title, body = notify.message(entry)
        self.assertIn("Precisa de você", title)
        self.assertIn("Barbearia Teste · +55 65 90000-0001", body)
        self.assertIn("Negociação de preço ou pagamento", body)
        self.assertIn("https://wa.me/5565900000001", body)
        self.assertEqual(entry["recent"], ["Alexandre: Boa tarde", "Cliente: Tá caro, faz por 300?"])


if __name__ == "__main__":
    unittest.main()
