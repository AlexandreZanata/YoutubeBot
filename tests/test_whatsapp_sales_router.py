import io
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path

from tools.ytbot.commercial.whatsapp.sales import llm
from tools.ytbot.commercial.whatsapp.sales.rules import load

KEY = "oc_sk_fixture_not_a_real_key"


def model(model_id, price, json_mode=True, training=False, api="chat-completions"):
    return {"id": model_id, "cost": {"text": {"input": {"price": price}, "output": {"price": price}}},
            "capabilities": {"structured_output": json_mode}, "api": {api: {}},
            "go": {"training": training, "zdr": not training}}


CATALOG = {"object": "list", "data": [
    model("longcat-2.5-free", 0, json_mode=None),
    model("beam-free", 0),
    model("iceman-contributor-free", 0, json_mode=None, training=True),
    model("glm-5.3", 1.4),
    model("deepseek-v4.1-flash", 0.15),
    model("muse-spark-1.3-contributor", 0.1, training=True, api="responses"),
]}


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeProvider:
    """Catalog plus a scripted behavior per model: ok, timeout, credits, nojson, garbage."""

    def __init__(self, behavior=None, catalog=CATALOG):
        self.behavior = behavior or {}
        self.catalog = catalog
        self.calls = []

    def __call__(self, request, timeout):
        if request.full_url.endswith("/models"):
            return Response(json.dumps(self.catalog).encode())
        body = json.loads(request.data)
        name = body["model"]
        self.calls.append((name, "response_format" in body))
        how = self.behavior.get(name, "ok")
        if how == "timeout":
            raise socket.timeout("timed out")
        if how == "credits":
            raise urllib.error.HTTPError(request.full_url, 429, "limit", {},
                                         io.BytesIO(b'{"error":{"type":"rate_limit","message":"quota exceeded"}}'))
        if how == "nojson" and "response_format" in body:
            raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, io.BytesIO(
                b'{"error":{"type":"invalid_request_error","message":"Structured `response_format` is not enabled"}}'))
        if how == "auth":
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO(b"{}"))
        content = "olá, tudo bem?" if how == "garbage" else '{"pong": true}'
        return Response(json.dumps({"model": name, "choices": [{"message": {"content": content}}],
                                    "usage": {"opencode": {"allowance": 0}}}).encode())


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ModelRouterTests(unittest.TestCase):
    settings = load().llm

    def router(self, provider, clock=None, settings=None):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        return llm.ModelRouter(settings or self.settings, KEY, provider,
                               cache_path=Path(self.directory.name) / "models.json",
                               clock=clock or Clock())

    def answer(self, router):
        return router.complete([{"role": "user", "content": "oi"}], "s").model

    def test_free_models_come_from_the_catalog_and_rotate(self):
        provider = FakeProvider()
        router = self.router(provider)
        self.assertEqual(router.free_models(), [])
        used = [self.answer(router) for _ in range(3)]
        self.assertEqual(router.free_models(),
                         ["longcat-2.5-free", "beam-free", "iceman-contributor-free"])
        self.assertEqual(used, ["longcat-2.5-free", "beam-free", "iceman-contributor-free"])
        self.assertNotIn("glm-5.3", [name for name, _ in provider.calls])

    def test_a_new_free_model_is_used_automatically(self):
        catalog = {"data": CATALOG["data"] + [model("nova-free", 0)]}
        router = self.router(FakeProvider(catalog=catalog))
        self.assertIn("nova-free", router.free_models() or (router.refresh(force=True)
                                                           or router.free_models()))

    def test_timeout_moves_on_and_pauses_the_model(self):
        clock = Clock()
        provider = FakeProvider({"longcat-2.5-free": "timeout"})
        router = self.router(provider, clock)
        self.assertEqual(self.answer(router), "beam-free")
        self.assertTrue(router.cooling("longcat-2.5-free"))
        provider.calls.clear()
        self.answer(router)
        self.assertNotIn("longcat-2.5-free", [name for name, _ in provider.calls])
        clock.now += self.settings["cooldown_seconds"] + 1
        self.assertFalse(router.cooling("longcat-2.5-free"))

    def test_without_free_credits_the_paid_fallback_answers_in_order(self):
        provider = FakeProvider({"longcat-2.5-free": "credits", "beam-free": "credits",
                                 "iceman-contributor-free": "credits"})
        router = self.router(provider)
        self.assertEqual(self.answer(router), "deepseek-v4.1-flash")
        self.assertEqual(router.status()[0]["reason"], "no-credits")
        provider.behavior["deepseek-v4.1-flash"] = "timeout"
        router._cooldown.pop("deepseek-v4.1-flash", None)
        self.assertEqual(self.answer(router), "muse-spark-1.3-contributor")

    def test_models_without_json_mode_are_called_without_it(self):
        provider = FakeProvider({"longcat-2.5-free": "nojson"})
        router = self.router(provider)
        router.catalog = llm.parse_catalog({"data": [model("longcat-2.5-free", 0)]})
        router._fetched = 1e12
        self.assertEqual(self.answer(router), "longcat-2.5-free")
        self.assertEqual(provider.calls[-2:], [("longcat-2.5-free", True),
                                               ("longcat-2.5-free", False)])
        self.answer(router)
        self.assertEqual(provider.calls[-1], ("longcat-2.5-free", False))

    def test_a_reply_that_is_not_json_goes_to_the_next_model(self):
        router = self.router(FakeProvider())
        router.refresh(force=True)
        router.probe = lambda: []
        provider = FakeProvider({"longcat-2.5-free": "garbage"})
        router._opener = provider
        self.assertEqual(self.answer(router), "beam-free")

    def test_probe_pauses_dead_free_models_before_any_conversation(self):
        provider = FakeProvider({"beam-free": "timeout"})
        router = self.router(provider)
        router.refresh(force=True)
        self.assertTrue(router.cooling("beam-free"))
        self.assertFalse(router.cooling("longcat-2.5-free"))
        self.assertEqual(json.loads((Path(self.directory.name) / "models.json").read_text())
                         ["data"][0]["id"], "longcat-2.5-free")

    def test_excluded_free_models_are_never_called(self):
        settings = {**self.settings, "exclude": ["iceman-contributor-free"]}
        provider = FakeProvider()
        router = self.router(provider, settings=settings)
        for _ in range(4):
            self.answer(router)
        self.assertNotIn("iceman-contributor-free", [name for name, _ in provider.calls])

    def test_bad_key_stops_at_once(self):
        router = self.router(FakeProvider({"longcat-2.5-free": "auth"}))
        router.catalog = llm.parse_catalog(CATALOG)
        router._fetched = 1e12
        with self.assertRaises(llm.LlmError) as caught:
            self.answer(router)
        self.assertEqual(caught.exception.kind, "auth")
        self.assertNotIn(KEY, str(caught.exception))

    def test_every_model_failing_is_reported(self):
        behavior = {name: "timeout" for name in ("longcat-2.5-free", "beam-free",
                                                 "iceman-contributor-free", "deepseek-v4.1-flash",
                                                 "muse-spark-1.3-contributor")}
        router = self.router(FakeProvider(behavior))
        with self.assertRaises(llm.LlmError) as caught:
            self.answer(router)
        self.assertEqual(caught.exception.kind, "exhausted")

    def test_catalog_marks_privacy_flags(self):
        free = {item.id: item for item in llm.parse_catalog(CATALOG) if item.free}
        self.assertTrue(free["iceman-contributor-free"].training)
        self.assertFalse(free["longcat-2.5-free"].training)
        self.assertNotIn("muse-spark-1.3-contributor", free)


if __name__ == "__main__":
    unittest.main()
