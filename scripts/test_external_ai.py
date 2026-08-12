import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import external_ai
import server


class FakeModelHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization", ""),
            "body": body,
        })
        if self.path == "/unauthorized":
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/limited":
            self.send_response(429)
            self.end_headers()
            return
        if self.path == "/bad-json":
            payload = {"response": "not json"}
        elif self.path == "/unknown":
            payload = {"response": json.dumps({
                "subject_group": "不存在课程", "confidence": 0.99,
            }, ensure_ascii=False)}
        else:
            result = {
                "subject_group": "数字电子技术",
                "assignment_id": "d1",
                "confidence": 0.92,
                "reason": "GPIO 与课程实验相符",
                "subject_candidates": [
                    {"label": "数字电子技术", "confidence": 0.92},
                    {"label": "自动控制原理", "confidence": 0.05},
                ],
                "assignment_candidates": [
                    {"label": "d1", "confidence": 0.92},
                    {"label": "d2", "confidence": 0.04},
                ],
            }
            if self.path == "/openai":
                payload = {"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}
            else:
                payload = {"response": json.dumps(result, ensure_ascii=False)}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def context():
    return {
        "normalized_text": "GPIO实验报告",
        "extension": "docx",
        "courses": ["数字电子技术", "自动控制原理"],
        "assignments": [
            {"id": "d1", "subject_group": "数字电子技术", "name": "GPIO实验"},
            {"id": "d2", "subject_group": "数字电子技术", "name": "触发器实验"},
        ],
    }


class ExternalAIAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        FakeModelHandler.requests.clear()

    def test_ollama_protocol_and_tree_validation(self):
        result = external_ai.classify(context(), {
            "provider": "ollama", "endpoint": self.base + "/ollama", "model": "tiny",
        })
        self.assertEqual(result["subject_group"], "数字电子技术")
        self.assertEqual(result["assignment_id"], "d1")
        request = FakeModelHandler.requests[-1]
        self.assertFalse(request["authorization"])
        self.assertEqual(request["body"]["format"], "json")

    def test_openai_compatible_protocol_uses_bearer_key(self):
        result = external_ai.classify(context(), {
            "provider": "openai_compatible",
            "endpoint": self.base + "/openai",
            "model": "cloud-tiny",
        }, "test-secret-key")
        self.assertEqual(result["confidence"], 0.92)
        request = FakeModelHandler.requests[-1]
        self.assertEqual(request["authorization"], "Bearer test-secret-key")
        self.assertEqual(request["body"]["response_format"], {"type": "json_object"})

    def test_bad_json_and_unknown_course_are_rejected(self):
        for path, category in (("/bad-json", "invalid_json"), ("/unknown", "unknown_subject")):
            with self.subTest(path=path):
                with self.assertRaises(external_ai.ExternalAIError) as caught:
                    external_ai.classify(context(), {
                        "provider": "ollama", "endpoint": self.base + path, "model": "tiny",
                    })
                self.assertEqual(caught.exception.category, category)

    def test_http_auth_and_rate_limit_errors_are_categorized(self):
        for path, category in (("/unauthorized", "authentication"), ("/limited", "rate_limited")):
            with self.subTest(path=path):
                with self.assertRaises(external_ai.ExternalAIError) as caught:
                    external_ai.classify(context(), {
                        "provider": "ollama", "endpoint": self.base + path, "model": "tiny",
                    })
                self.assertEqual(caught.exception.category, category)

    def test_settings_discard_secret_and_rate_limits_apply(self):
        settings = external_ai.normalize_settings({"api_key": "must-not-survive"})
        self.assertNotIn("api_key", settings)
        event = {"time": external_ai.utc_now()}
        with self.assertRaises(external_ai.ExternalAIError) as caught:
            external_ai.enforce_rate_limit([event], {**settings, "minute_limit": 1})
        self.assertEqual(caught.exception.category, "minute_limit")
        self.assertEqual(external_ai.usage_counts([
            event, {"time": external_ai.utc_now(), "counted": False},
        ]), (1, 1))

    def test_cloud_provider_gets_cloud_default_endpoint(self):
        settings = external_ai.normalize_settings({
            "provider": "openai_compatible", "model": "cloud-tiny",
        })
        self.assertEqual(settings["endpoint"], "https://api.openai.com/v1/chat/completions")


class ExternalAIServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (
            server.CONFIG_PATH,
            server.STUDENTS_PATH,
            server.AI_RULES_PATH,
            server.AI_SECRETS_PATH,
            server.AI_EXTERNAL_HISTORY_PATH,
        )
        server.CONFIG_PATH = root / "config.json"
        server.STUDENTS_PATH = root / "students.json"
        server.AI_RULES_PATH = root / "ai_rules.json"
        server.AI_SECRETS_PATH = root / "ai_secrets.json"
        server.AI_EXTERNAL_HISTORY_PATH = root / "external_history.json"
        self.cfg = server.default_config()
        self.cfg["class_name"] = "电国241"
        self.cfg["assignments"] = [{
            "id": "d1", "name": "GPIO实验", "subject_group": "数字电子技术", "active": True,
        }]
        self.cfg["ai_external"].update({
            "enabled": True,
            "provider": "ollama",
            "endpoint": self.base + "/ollama",
            "model": "tiny",
            "suggestion_only": True,
        })
        server.save_config(self.cfg)
        server.save_students([{"name": "张三", "student_id": "20240001"}])
        server.save_ai_rules({
            "schema_version": 1,
            "profile": {},
            "subjects": {
                "数字电子技术": {"active": True, "confirmed_aliases": ["数电"], "suggested_aliases": [], "keywords": ["GPIO"], "assignment_types": [], "source": "test"},
            },
            "types": {},
        })

    def tearDown(self):
        (
            server.CONFIG_PATH,
            server.STUDENTS_PATH,
            server.AI_RULES_PATH,
            server.AI_SECRETS_PATH,
            server.AI_EXTERNAL_HISTORY_PATH,
        ) = self.original
        self.temp.cleanup()

    def test_secret_is_separate_and_never_returned(self):
        server.save_external_ai_secret("super-secret-key")
        public = server.public_external_ai_settings(self.cfg)
        self.assertTrue(public["key_configured"])
        self.assertNotEqual(public["key_masked"], "super-secret-key")
        self.assertNotIn("super-secret-key", server.CONFIG_PATH.read_text("utf-8"))
        self.assertEqual(server.load_external_ai_secrets()["api_key"], "super-secret-key")

    def test_generic_config_save_strips_injected_api_key(self):
        cfg = server.load_config_raw()
        cfg["ai_external"]["api_key"] = "must-not-enter-config"
        server.save_config(cfg)
        saved = server.CONFIG_PATH.read_text("utf-8")
        self.assertNotIn("must-not-enter-config", saved)
        self.assertNotIn("api_key", json.loads(saved)["ai_external"])

    def test_privacy_context_removes_student_and_path(self):
        value = server.external_ai_context(
            r"D:\private\电国241_20240001张三_GPIO实验报告.docx",
            self.cfg,
            server.load_ai_rules(),
            self.cfg["assignments"],
        )
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertNotIn("张三", encoded)
        self.assertNotIn("20240001", encoded)
        self.assertNotIn("D:\\private", encoded)
        self.assertIn("gpio", value["normalized_text"].casefold())

    def test_suggestion_only_does_not_override_local_result(self):
        local = {"status": "unmatched", "subject_group": "", "subject_candidates": []}
        called = server.call_external_ai(
            "20240001张三_GPIO实验报告.docx",
            self.cfg,
            server.load_ai_rules(),
            self.cfg["assignments"],
        )
        merged = server.apply_external_ai_result(local, called, self.cfg)
        self.assertEqual(merged["status"], "unmatched")
        self.assertFalse(merged["external_ai"]["adopted"])
        history_text = json.dumps(server.load_external_ai_history(), ensure_ascii=False)
        self.assertNotIn("张三", history_text)
        self.assertNotIn("GPIO", history_text)

    def test_high_confidence_can_be_adopted_after_tree_validation(self):
        self.cfg["ai_external"]["suggestion_only"] = False
        local = {"status": "unmatched", "subject_group": "", "subject_candidates": [], "evidence": []}
        payload = {
            "called": True, "ok": True, "provider": "ollama", "model": "tiny",
            "result": {
                "subject_group": "数字电子技术", "assignment_id": "d1", "confidence": 0.92,
                "subject_candidates": [
                    {"label": "数字电子技术", "confidence": 0.92},
                ],
                "assignment_candidates": [{"label": "d1", "confidence": 0.92}],
            },
        }
        merged = server.apply_external_ai_result(local, payload, self.cfg)
        self.assertEqual(merged["subject_group"], "数字电子技术")
        self.assertTrue(merged["external_ai"]["adopted"])

    def test_full_workflow_reuses_one_external_call_for_subject_and_assignment(self):
        self.cfg["ai_external"]["suggestion_only"] = False
        server.save_config(self.cfg)
        FakeModelHandler.requests.clear()
        subject = server.classify_file_subject(
            {"name": "20240001张三_神秘控制板报告.docx"},
            self.cfg["assignments"],
            self.cfg,
        )
        self.assertEqual(subject["subject_group"], "数字电子技术")
        assignment = server.classify_assignment_in_subject(
            "20240001张三_神秘控制板报告.docx",
            subject["subject_group"],
            self.cfg["assignments"],
            self.cfg,
            external_payload=subject.get("external_ai"),
        )
        self.assertEqual(assignment["assignment_id"], "d1")
        self.assertEqual(len(FakeModelHandler.requests), 1)

    def test_classifier_off_never_calls_external_model(self):
        self.cfg["ai_classifier"]["mode"] = "off"
        FakeModelHandler.requests.clear()
        result = server.classify_file_subject(
            {"name": "20240001张三_完全未知报告.docx"},
            self.cfg["assignments"],
            self.cfg,
        )
        self.assertEqual(result["status"], "unmatched")
        self.assertEqual(FakeModelHandler.requests, [])

    def test_history_flow_can_suppress_external_model(self):
        FakeModelHandler.requests.clear()
        result = server.classify_file_subject(
            {"name": "20240001张三_完全未知报告.docx"},
            self.cfg["assignments"],
            self.cfg,
            source_kind="public_backfill",
            allow_external=False,
        )
        self.assertEqual(result["status"], "unmatched")
        self.assertEqual(result["external_ai"]["trigger"], "external_suppressed")
        self.assertEqual(FakeModelHandler.requests, [])

    def test_unexpected_adapter_error_falls_back_and_releases_lock(self):
        original = external_ai.classify
        external_ai.classify = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            failed = server.call_external_ai(
                "20240001张三_GPIO实验报告.docx",
                self.cfg,
                server.load_ai_rules(),
                self.cfg["assignments"],
            )
        finally:
            external_ai.classify = original
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error_category"], "internal_error")
        self.assertNotIn("boom", failed["message"])
        recovered = server.call_external_ai(
            "20240001张三_GPIO实验报告.docx",
            self.cfg,
            server.load_ai_rules(),
            self.cfg["assignments"],
        )
        self.assertTrue(recovered["ok"])

    def test_http_settings_and_connection_test_keep_key_private(self):
        class LocalHandler(server.APIHandler):
            def _request_is_local(self):
                return True

            def log_message(self, _format, *_args):
                pass

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def request(path, method="GET", data=None):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
            req = urllib.request.Request(
                base + path,
                data=raw,
                method=method,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            saved = request("/api/ai/external/settings", "POST", {
                "enabled": True,
                "provider": "openai_compatible",
                "endpoint": self.base + "/openai",
                "model": "cloud-tiny",
                "api_key": "http-test-secret",
                "suggestion_only": True,
            })
            self.assertTrue(saved["ok"])
            self.assertTrue(saved["settings"]["key_configured"])
            self.assertNotIn("http-test-secret", json.dumps(saved))
            tested = request("/api/ai/external/test", "POST", {
                "file_name": "数电GPIO实验报告.docx",
            })
            self.assertTrue(tested["ok"])
            self.assertEqual(tested["result"]["result"]["subject_group"], "数字电子技术")
            self.assertNotIn("http-test-secret", json.dumps(tested))
            self.assertNotIn("http-test-secret", server.CONFIG_PATH.read_text("utf-8"))

            rejected = request("/api/ai/external/settings", "POST", {
                "enabled": True,
                "provider": "openai_compatible",
                "endpoint": self.base + "/openai",
                "model": "cloud-tiny",
                "clear_key": True,
            })
            self.assertFalse(rejected["ok"])
            self.assertEqual(server.load_external_ai_secrets()["api_key"], "http-test-secret")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
