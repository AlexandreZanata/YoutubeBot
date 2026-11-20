import unittest

from sales_fixtures import FakeModel
from tools.ytbot.commercial.whatsapp.sales import rehearsal
from tools.ytbot.commercial.whatsapp.sales.rules import load


class RehearsalTests(unittest.TestCase):
    rules = load()

    def test_versioned_scenarios_load(self):
        scenarios = rehearsal.load_scenarios()
        self.assertGreaterEqual(len(scenarios), 20)
        self.assertTrue(all(turns for turns in scenarios.values()))

    def test_rehearsal_runs_the_real_agent_without_sending(self):
        transcripts = rehearsal.rehearse(self.rules, {
            "pronto": ["Quero fechar, como faço pra pagar a entrada?", "Oi?"],
            "recusa": ["Não, obrigado"],
        }, FakeModel())
        ready, refusal = transcripts
        self.assertEqual(ready["turns"][0]["state"], "buying")
        self.assertEqual(ready["handoffs"][0]["priority"], "hot")
        self.assertEqual(ready["turns"][1]["bot"], [])
        self.assertEqual(refusal["turns"][0]["state"], "needs-owner")
        self.assertIn("🔥 Atender agora", rehearsal.render(transcripts))


if __name__ == "__main__":
    unittest.main()
