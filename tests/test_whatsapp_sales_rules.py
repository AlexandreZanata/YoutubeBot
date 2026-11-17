import copy
import tomllib
import unittest
from datetime import datetime

from sales_fixtures import MONDAY, ZONE
from tools.ytbot.commercial.whatsapp.sales import rules as sales_rules


class SalesRulesTests(unittest.TestCase):
    def setUp(self):
        self.rules = sales_rules.load()
        self.raw = tomllib.loads(sales_rules.RULES_PATH.read_text(encoding="utf-8"))

    def test_opening_is_the_owner_script_with_one_link_per_message(self):
        self.assertEqual(self.rules.opening_messages(MONDAY), [
            "Bom dia",
            "Tudo bem?",
            "Sou o Alexandre da empresa Zaflas Inova Simples, nossa empresa cria sistemas, "
            "sites e aplicativos. Eu vi que no Google Maps vocês não têm site.",
            "Nós temos alguns exemplos de sistemas e sites que nós criamos:",
            "https://sorrifit.com",
            "https://zaflas.com.br",
            "https://musicalizese.com.br",
            "https://abastevo.com.br",
        ])

    def test_opening_intervals_are_the_owner_values(self):
        self.assertEqual(self.rules.opening_delays(), [4, 2, 8, 8, 4, 4, 4, 4])

    def test_opening_delays_must_match_the_messages(self):
        raw = copy.deepcopy(self.raw)
        raw["opening"]["delays"] = [4, 2]
        with self.assertRaises(sales_rules.RulesError):
            sales_rules.build(raw)

    def test_greeting_follows_the_local_hour(self):
        self.assertEqual(self.rules.greeting(MONDAY.replace(hour=14)), "Boa tarde")
        self.assertEqual(self.rules.greeting(MONDAY.replace(hour=19)), "Boa noite")

    def test_owner_prices_and_deadline_are_the_only_allowed_values(self):
        self.assertTrue({"500.00", "250.00", "39.90", "45.00"} <= self.rules.allowed_money)
        self.assertIn("15", self.rules.allowed_numbers)
        self.assertNotIn("300.00", self.rules.allowed_money)

    def test_system_request_answer_is_the_owner_text(self):
        intent = self.rules.intent("system_request")
        self.assertTrue(intent.fixed)
        self.assertEqual(intent.messages[0], "Sim, nós podemos fazer isso.")
        self.assertIn("aplicativos e sistemas são feitos sob medida", intent.messages[1])
        self.assertEqual(intent.messages[-1], "Você gostaria que eu fizesse um orçamento?")

    def test_site_prices_are_stated_as_site_only(self):
        facts = " ".join(self.rules.raw["facts"]["sistemas"])
        self.assertIn("NÃO custam R$ 500", facts)
        self.assertIn("SOMENTE para o site institucional",
                      " ".join(self.rules.raw["facts"]["site_institucional"]))

    def test_daily_opening_limit_is_ten(self):
        self.assertEqual(self.rules.limits["daily_openings"], 10)

    def test_opening_window_is_weekday_business_hours(self):
        self.assertTrue(self.rules.in_window(MONDAY, "opening"))
        self.assertFalse(self.rules.in_window(MONDAY.replace(hour=18), "opening"))
        saturday = datetime(2026, 11, 21, 10, 0, tzinfo=ZONE)
        self.assertFalse(self.rules.in_window(saturday, "opening"))
        self.assertTrue(self.rules.in_window(saturday, "reply"))

    def test_running_bot_reloads_an_edited_rules_file_and_ignores_a_broken_one(self):
        import tempfile
        from pathlib import Path
        from tools.ytbot.commercial.whatsapp.sales.commands import reload_if_changed

        class Agent:
            rules = None

            def use_rules(self, rules):
                self.rules = rules

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.toml"
            text = sales_rules.RULES_PATH.read_text(encoding="utf-8")
            path.write_text(text.replace("daily_openings = 10", "daily_openings = 5"),
                            encoding="utf-8")
            agent = Agent()
            seen = reload_if_changed(agent, path, 0.0)
            self.assertEqual(agent.rules.limits["daily_openings"], 5)
            path.write_text("broken = [", encoding="utf-8")
            import os
            os.utime(path, (seen + 5, seen + 5))
            reload_if_changed(agent, path, seen)
            self.assertEqual(agent.rules.limits["daily_openings"], 5)

    def test_only_the_owner_fallback_models_are_accepted(self):
        self.assertEqual(self.rules.llm["fallback"],
                         ["deepseek-v4.1-flash", "muse-spark-1.3-contributor"])
        raw = copy.deepcopy(self.raw)
        raw["llm"]["fallback"] = ["glm-5.3"]
        with self.assertRaises(sales_rules.RulesError):
            sales_rules.build(raw)
        raw = copy.deepcopy(self.raw)
        raw["llm"]["models_url"] = "https://example.com/v1/models"
        with self.assertRaises(sales_rules.RulesError):
            sales_rules.build(raw)

    def test_refusal_must_block(self):
        raw = copy.deepcopy(self.raw)
        next(item for item in raw["intents"] if item["id"] == "refusal")["action"] = "reply"
        with self.assertRaises(sales_rules.RulesError):
            sales_rules.build(raw)

    def test_daily_limit_is_bounded(self):
        raw = copy.deepcopy(self.raw)
        raw["limits"]["daily_openings"] = 500
        with self.assertRaises(sales_rules.RulesError):
            sales_rules.build(raw)

    def test_money_values_parse_brazilian_formats(self):
        self.assertEqual(sales_rules.money_values("R$ 39,90 ou R$500 ou 1.500 reais"),
                         {"39.90", "500.00", "1500.00"})


if __name__ == "__main__":
    unittest.main()
