"""Course-save integration checks and a disposable UI validation server."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py" if (ROOT / "py").is_dir() else ROOT))
import server


def sample_rules():
    pack = {"schema_version": 1, "profile": {"semester": "验证学期"}, "types": {"报告": ["report"]}, "subjects": {}}
    for name, alias in (("示例电路", "示电"), ("示例控制", "示控")):
        pack["subjects"][name] = {"active": True, "confirmed_aliases": [alias], "suggested_aliases": [name + "建议", name + "忽略"],
                                  "keywords": [name + "知识点", name + "器件"], "assignment_types": ["报告"], "source": "fixture"}
    return pack


class QuietHandler(server.APIHandler):
    def log_message(self, *_args):
        pass


class DisposableServer:
    def __init__(self, port=0):
        self.temp = tempfile.TemporaryDirectory(prefix="dashboard-course-editor-")
        root = Path(self.temp.name)
        paths = {"DATA_DIR": root, "CONFIG_PATH": root / "config.json", "STUDENTS_PATH": root / "students.json",
                 "SUBMISSIONS_PATH": root / "submissions.json", "AI_RULES_PATH": root / "rules.json",
                 "AI_EXAMPLES_PATH": root / "examples.json", "AI_MODELS_DIR": root / "models",
                 "WATCHER_STATE_FILE": root / "watcher.json", "LOCK_PATH": root / "server.lock",
                 "ORGANIZED_DIR": root / "organized", "EXPERIMENT_BASE": root / "sync"}
        self.patcher = patch.multiple(server, watcher=SimpleNamespace(running=False, known_files=set()),
                                      sync_current_wechat_scan_dirs=lambda cfg=None: cfg or server.load_config_raw(),
                                      get_watch_dirs=lambda: [], **paths)
        self.patcher.start()
        cfg = server.default_config()
        cfg.update({"class_name": "课程编辑隔离验证", "class_folder": str(root / "class"), "organized_dir": str(root / "organized"),
                    "experiment_dir": str(root / "sync"), "experiment_enabled": False, "scan_dirs": [], "assignments": [],
                    "wechat_accounts": [], "watch_enabled": False, "default_frontend": "modern"})
        cfg["ai_classifier"]["auto_train"] = False
        server.save_json(server.CONFIG_PATH, cfg)
        server.save_json(server.STUDENTS_PATH, [])
        server.save_json(server.SUBMISSIONS_PATH, {})
        server.save_ai_rules(sample_rules())
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.patcher.stop()
        self.temp.cleanup()

    def request(self, path, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": "application/json", "Origin": self.base})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def rules(self):
        return self.request("/api/ai/rules")["rule_pack"]

    def update(self, changes):
        return self.request("/api/ai/rules/update-courses", {"changes": changes})


class CourseSaveTest(unittest.TestCase):
    def setUp(self):
        self.service = DisposableServer()

    def tearDown(self):
        self.service.close()

    def test_single_course_preserves_other_courses_and_metadata(self):
        before = self.service.rules()
        reply = self.service.update([{"name": "示例电路", "expected": before["subjects"]["示例电路"], "course": {"keywords": ["新知识点"]}}])
        self.assertTrue(reply["ok"])
        after = self.service.rules()
        self.assertEqual(after["subjects"]["示例控制"], before["subjects"]["示例控制"])
        self.assertEqual(after["profile"], before["profile"])
        self.assertEqual(after["types"], before["types"])
        self.assertEqual(after["subjects"]["示例电路"]["assignment_types"], ["报告"])
        self.assertEqual(after["subjects"]["示例电路"]["source"], "fixture")

    def test_stale_same_course_rejected_without_writing(self):
        old = self.service.rules()["subjects"]["示例电路"]
        self.assertTrue(self.service.update([{"name": "示例电路", "expected": old, "course": {"keywords": ["第一次修改"]}}])["ok"])
        reply = self.service.update([{"name": "示例电路", "expected": old, "course": {"keywords": ["过期修改"]}}])
        self.assertFalse(reply["ok"])
        self.assertEqual(self.service.rules()["subjects"]["示例电路"]["keywords"], ["第一次修改"])

    def test_independent_edits_merge_from_same_snapshot(self):
        old = self.service.rules()["subjects"]
        outcomes = []
        threads = [threading.Thread(target=lambda name=name: outcomes.append(self.service.update([
            {"name": name, "expected": old[name], "course": {"keywords": [name + "并发修改"]}}
        ]))) for name in old]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(reply["ok"] for reply in outcomes))
        for name in old:
            self.assertEqual(self.service.rules()["subjects"][name]["keywords"], [name + "并发修改"])

    def test_collision_rolls_back_entire_batch(self):
        before = self.service.rules()
        reply = self.service.update([
            {"name": "示例电路", "expected": before["subjects"]["示例电路"], "course": {"keywords": ["不能写入"]}},
            {"name": "示例控制", "expected": before["subjects"]["示例控制"], "course": {"confirmed_aliases": ["示电"]}},
        ])
        self.assertFalse(reply["ok"])
        self.assertEqual(self.service.rules(), before)

    def test_add_delete_and_confirm_suggestion(self):
        original = self.service.rules()["subjects"]["示例电路"]
        self.assertTrue(self.service.update([{"name": "新课程", "expected": None, "course": {"keywords": ["GPIO"]}}])["ok"])
        self.assertTrue(self.service.update([{"name": "示例电路", "expected": original,
                                            "course": {"confirmed_aliases": ["示电", "示例电路建议"], "suggested_aliases": []}}])["ok"])
        current = self.service.rules()["subjects"]["新课程"]
        self.assertTrue(self.service.update([{"name": "新课程", "expected": current, "delete": True}])["ok"])
        self.assertNotIn("新课程", self.service.rules()["subjects"])
        self.assertIn("示例电路建议", self.service.rules()["subjects"]["示例电路"]["confirmed_aliases"])

    def test_invalid_length_and_missing_expected_do_not_write(self):
        before = self.service.rules()
        for change in ({"name": "示例电路", "course": {"keywords": ["x"]}},
                       {"name": "示例电路", "expected": before["subjects"]["示例电路"], "course": {"keywords": ["x" * 81]}}):
            self.assertFalse(self.service.update([change])["ok"])
        self.assertEqual(self.service.rules(), before)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=18866)
    args = parser.parse_args()
    if args.serve:
        service = DisposableServer(args.port)
        print(f"ISOLATED_UI_READY {service.base}/dashboard_modern.html#brain", flush=True)
        try:
            service.thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            service.close()
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)
