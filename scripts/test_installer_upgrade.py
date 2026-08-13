"""Silent user-perspective tests for installation, upgrade, repair and rollback."""

import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import installer
import installer_core
import app_meta
import pack


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class InstallerCoreTest(unittest.TestCase):
    def test_release_metadata_is_shared(self):
        self.assertEqual(installer.APP_VERSION, app_meta.APP_VERSION)
        self.assertEqual(pack.get_version(), app_meta.APP_VERSION)
        self.assertIn(f"v{app_meta.APP_VERSION}", (ROOT / "README.md").read_text("utf-8"))
        spec = next(ROOT.glob("*.spec")).read_text("utf-8")
        self.assertIn(f"作业追踪器v{app_meta.APP_VERSION}", spec)

    def test_source_installer_self_test_is_headless(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "self-test.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "installer.py"), "--self-test-output", str(output)],
                cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = installer_core.load_json(output, {})
            self.assertTrue(payload["ok"])
            self.assertTrue(all(payload["resources"].values()))
            self.assertEqual(payload["rule_pack_subjects"], ["数字电子技术"])

    def desired_config(self, root):
        class_folder = root / "class"
        return installer_core.build_default_config(
            class_name="新安装班级",
            class_folder=class_folder,
            organized_dir=class_folder / "已收作业",
            experiment_dir=class_folder / "实验",
            scan_dirs=[root / "scan"],
            file_types=[".docx", ".pdf"],
            version="9.9.9",
            active_semester="2026-2027-1",
            class_aliases=["新班"],
        )

    def test_mode_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(installer_core.detect_install_mode(root), "new")
            (root / "server.py").write_text("old", encoding="utf-8")
            self.assertEqual(installer_core.detect_install_mode(root), "repair")
            (root / "data").mkdir()
            (root / "data" / "config.json").write_text("{}", encoding="utf-8")
            self.assertEqual(installer_core.detect_install_mode(root), "upgrade")
            with self.assertRaisesRegex(ValueError, "全新安装"):
                installer_core.detect_install_mode(root, "new")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "没有 data/config.json"):
                installer_core.detect_install_mode(Path(tmp), "upgrade")

    def test_upgrade_stops_on_corrupt_config_or_rule_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (data / "config.json").write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                installer_core.build_data_plan(
                    data, "upgrade", self.desired_config(root), installer_core.empty_rule_pack()
                )

            installer_core.atomic_write_json(data / "config.json", {"class_name": "旧班级"})
            installer_core.atomic_write_json(data / "ai_rules.json", installer_core.empty_rule_pack())
            (data / "ai_examples.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ai_examples.json"):
                installer_core.build_data_plan(
                    data, "upgrade", self.desired_config(root), installer_core.empty_rule_pack()
                )

            (data / "ai_examples.json").unlink()
            (data / "ai_rules.json").write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                installer_core.build_data_plan(
                    data, "upgrade", self.desired_config(root), installer_core.empty_rule_pack()
                )

    def test_upgrade_adds_missing_fields_without_changing_user_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            old = {
                "class_name": "用户原班级",
                "assignments": [{"id": "keep", "name": "用户作业", "due": "明天"}],
                "scan_dirs": ["D:/用户目录"],
                "custom_extension": {"keep": True},
                "ai_classifier": {"mode": "local_model", "sensitivity": 0.83},
            }
            installer_core.atomic_write_json(data / "config.json", old)
            plan = installer_core.build_data_plan(
                data, "upgrade", self.desired_config(root), installer_core.empty_rule_pack()
            )
            merged = plan["config"]
            self.assertEqual(merged["class_name"], "用户原班级")
            self.assertEqual(merged["assignments"], old["assignments"])
            self.assertEqual(merged["scan_dirs"], old["scan_dirs"])
            self.assertEqual(merged["custom_extension"], {"keep": True})
            self.assertEqual(merged["ai_classifier"]["mode"], "local_model")
            self.assertEqual(merged["ai_classifier"]["sensitivity"], 0.83)
            self.assertIn("priority", merged["ai_classifier"])
            self.assertIn("ai_external", merged)
            self.assertEqual(merged["version"], "9.9.9")

    def test_upgrade_preserves_runtime_data_and_rules_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            models = data / "models"
            models.mkdir(parents=True)
            protected = {
                "students.json": [{"name": "张三", "student_id": "001"}],
                "submissions.json": {"a": [{"student": "张三"}]},
                "watcher_state.json": {"known_files": {"x": 1}},
                "ai_examples.json": {"schema_version": 2, "items": [{"id": "e1"}]},
                "ai_secrets.json": {"api_key": "private-test-value"},
                "ai_external_history.json": {"items": [{"status": "success"}]},
            }
            installer_core.atomic_write_json(data / "config.json", {"class_name": "旧班级"})
            old_rules = installer_core.build_course_rule_pack(["旧课程"], {"semester": "旧学期"})
            installer_core.atomic_write_json(data / "ai_rules.json", old_rules)
            for name, payload in protected.items():
                installer_core.atomic_write_json(data / name, payload)
            (models / "bundle.json").write_text('{"model":"keep"}', encoding="utf-8")
            before = {path: file_digest(data / path) for path in protected}
            before["ai_rules.json"] = file_digest(data / "ai_rules.json")
            before["models/bundle.json"] = file_digest(models / "bundle.json")

            plan = installer_core.build_data_plan(
                data,
                "upgrade",
                self.desired_config(root),
                installer_core.build_course_rule_pack(["新课程"], {"semester": "新学期"}),
                apply_rules=False,
            )
            result = installer_core.apply_install_plan(
                ROOT, root, ["server.py", "installer_core.py"], plan
            )
            self.assertTrue(result["ok"])
            self.assertIsNone(plan["rules"])
            for relative, digest in before.items():
                self.assertEqual(file_digest(data / relative), digest, relative)

    def test_explicit_semester_pack_merge_keeps_old_course_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            installer_core.atomic_write_json(data / "config.json", {"class_name": "旧班级"})
            old_rules = installer_core.build_course_rule_pack(["旧课程"], {"semester": "旧学期"})
            installer_core.atomic_write_json(data / "ai_rules.json", old_rules)
            new_rules = installer_core.build_course_rule_pack(["新课程"], {"semester": "新学期"})
            plan = installer_core.build_data_plan(
                data, "upgrade", self.desired_config(root), new_rules, apply_rules=True
            )
            self.assertFalse(plan["rules"]["subjects"]["旧课程"]["active"])
            self.assertTrue(plan["rules"]["subjects"]["新课程"]["active"])

    def test_repair_changes_program_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            installer_core.atomic_write_json(data / "config.json", {"untouched": True})
            installer_core.atomic_write_json(data / "ai_secrets.json", {"api_key": "keep"})
            (root / "server.py").write_text("old", encoding="utf-8")
            before = {name: file_digest(data / name) for name in ("config.json", "ai_secrets.json")}
            plan = installer_core.build_data_plan(
                data, "repair", self.desired_config(root), installer_core.empty_rule_pack()
            )
            result = installer_core.apply_install_plan(ROOT, root, ["server.py"], plan)
            self.assertEqual(result["written"], [])
            for name, digest in before.items():
                self.assertEqual(file_digest(data / name), digest)

    def test_repair_can_replace_program_when_user_json_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (root / "server.py").write_text("old", encoding="utf-8")
            (data / "config.json").write_text("{broken", encoding="utf-8")
            (data / "ai_examples.json").write_text("{also-broken", encoding="utf-8")
            before = {
                name: file_digest(data / name)
                for name in ("config.json", "ai_examples.json")
            }
            plan = installer_core.build_data_plan(
                data, "repair", self.desired_config(root), installer_core.empty_rule_pack()
            )
            result = installer_core.apply_install_plan(ROOT, root, ["server.py"], plan)
            self.assertEqual(result["mode"], "repair")
            self.assertNotEqual((root / "server.py").read_text("utf-8"), "old")
            for name, digest in before.items():
                self.assertEqual(file_digest(data / name), digest)

    def test_failure_restores_program_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (root / "server.py").write_text("old-server", encoding="utf-8")
            installer_core.atomic_write_json(data / "config.json", {"old": True})
            server_before = file_digest(root / "server.py")
            config_before = file_digest(data / "config.json")
            plan = installer_core.build_data_plan(
                data, "upgrade", self.desired_config(root), installer_core.empty_rule_pack()
            )
            with self.assertRaisesRegex(RuntimeError, "injected"):
                installer_core.apply_install_plan(
                    ROOT, root, ["server.py", "installer_core.py"], plan, fail_after=2
                )
            self.assertEqual(file_digest(root / "server.py"), server_before)
            self.assertEqual(file_digest(data / "config.json"), config_before)
            self.assertFalse((root / "installer_core.py").exists())

    def test_failed_new_install_removes_only_its_new_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            install = parent / "new-target"
            plan = installer_core.build_data_plan(
                install / "data", "new", self.desired_config(install), installer_core.empty_rule_pack()
            )
            with self.assertRaises(FileNotFoundError):
                installer_core.apply_install_plan(
                    ROOT, install, ["server.py", "missing-required-resource.py"], plan
                )
            self.assertFalse(install.exists())
            self.assertTrue(parent.exists())

    def test_failed_install_in_existing_empty_target_leaves_no_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "existing-empty"
            install.mkdir()
            plan = installer_core.build_data_plan(
                install / "data", "new", self.desired_config(install), installer_core.empty_rule_pack()
            )
            with self.assertRaises(FileNotFoundError):
                installer_core.apply_install_plan(
                    ROOT, install, ["server.py", "missing-required-resource.py"], plan
                )
            self.assertTrue(install.is_dir())
            self.assertEqual(list(install.iterdir()), [])

    def test_new_install_initializes_rules_without_training_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "new-install"
            desired = self.desired_config(install)
            rules = installer_core.build_course_rule_pack(
                ["数字电子技术", "自动控制原理"],
                {"name": "自动化新学期", "semester": "2026-2027-1"},
            )
            plan = installer_core.build_data_plan(install / "data", "new", desired, rules)
            result = installer_core.apply_install_plan(
                ROOT, install,
                ["server.py", "app_meta.py", "ai_classifier.py", "external_ai.py",
                 "classifier_features.py", "classifier_trainer.py", "installer_core.py",
                 "dashboard.html", "dashboard_modern.html"],
                plan,
            )
            self.assertTrue(result["ok"])
            config = installer_core.load_json(install / "data" / "config.json", {})
            saved_rules = installer_core.load_json(install / "data" / "ai_rules.json", {})
            self.assertEqual(config["default_frontend"], "modern")
            self.assertEqual(config["ai_classifier"]["mode"], "rules")
            self.assertFalse(config["ai_external"]["enabled"])
            self.assertEqual(set(saved_rules["subjects"]), {"数字电子技术", "自动控制原理"})
            self.assertFalse((install / "data" / "ai_examples.json").exists())
            self.assertFalse((install / "data" / "models").exists())


@unittest.skipUnless(sys.platform == "win32", "Tk installer UI is Windows-only")
class InstallerHiddenUITest(unittest.TestCase):
    def test_each_wizard_page_builds_without_user_interaction(self):
        code = r'''
import installer
import installer_core
installer_core.ollama_status = lambda timeout=0.35: {"available": False, "models": []}
wizard = installer.InstallerWizard()
wizard.root.withdraw()
wizard._check_environment = lambda: None
wizard._execute_install = lambda: None
for step in range(7):
    wizard._show_step(step)
    wizard.root.update()
    assert wizard.content_frame.winfo_children(), step
wizard.root.destroy()
print("HIDDEN_UI_OK")
'''
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HIDDEN_UI_OK", result.stdout)

    def test_wizard_performs_isolated_new_install_and_creates_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            install = sandbox / "installed-app"
            wizard = installer.InstallerWizard()
            wizard.root.withdraw()
            wizard.install_dir = str(install)
            wizard.active_semester = "2026-2027-1"
            wizard.class_aliases = ["测试班"]
            wizard.open_brain_after_install = False
            wizard._log = lambda *args, **kwargs: None
            wizard._set_progress = lambda *args, **kwargs: None
            rules = installer_core.build_course_rule_pack(["数字电子技术"])
            try:
                with mock.patch.object(installer.os.path, "expanduser", side_effect=lambda value: str(sandbox) if value == "~" else value):
                    wizard._do_install(
                        str(install), "安装测试班", False, [".docx"],
                        [str(sandbox / "incoming")], rules, True, "new", False,
                    )
                wizard.root.update()
                self.assertTrue(wizard.install_succeeded)
                self.assertTrue((install / "server.py").is_file())
                self.assertTrue((install / "installer_core.py").is_file())
                self.assertTrue((install / "启动作业追踪器.bat").is_file())
                config = installer_core.load_json(install / "data" / "config.json", {})
                self.assertEqual(config["class_name"], "安装测试班")
                self.assertEqual(config["default_frontend"], "modern")
                self.assertFalse((install / "data" / "ai_examples.json").exists())
                self.assertFalse((install / "data" / "models").exists())
            finally:
                wizard.root.destroy()

    def test_wizard_upgrade_preserves_user_data_and_custom_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            install = sandbox / "old-install"
            data = install / "data"
            data.mkdir(parents=True)
            old_config = {
                "class_name": "旧安装班级",
                "class_folder": str(sandbox / "class"),
                "organized_dir": str(sandbox / "class" / "已收作业"),
                "experiment_dir": str(sandbox / "class" / "实验"),
                "scan_dirs": [],
                "assignments": [{"id": "keep", "name": "保留作业", "active": True}],
                "custom_user_setting": {"keep": True},
                "version": "0.1.1",
            }
            rules = installer_core.build_course_rule_pack(["旧课程"])
            installer_core.atomic_write_json(data / "config.json", old_config)
            installer_core.atomic_write_json(data / "ai_rules.json", rules)
            installer_core.atomic_write_json(data / "students.json", [{"name": "保留学生"}])
            installer_core.atomic_write_json(data / "submissions.json", {"keep": []})
            installer_core.atomic_write_json(data / "ai_secrets.json", {"api_key": "keep-private"})
            protected = {
                name: file_digest(data / name)
                for name in ("ai_rules.json", "students.json", "submissions.json", "ai_secrets.json")
            }

            wizard = installer.InstallerWizard()
            wizard.root.withdraw()
            wizard.install_dir = str(install)
            wizard.active_semester = ""
            wizard.class_aliases = []
            wizard.open_brain_after_install = False
            wizard._log = lambda *args, **kwargs: None
            wizard._set_progress = lambda *args, **kwargs: None
            try:
                wizard._do_install(
                    str(install), "不应覆盖", False, [".docx"], [],
                    installer_core.build_course_rule_pack(["不应导入"]),
                    True, "upgrade", False,
                )
                wizard.root.update()
                self.assertTrue(wizard.install_succeeded)
                upgraded = installer_core.load_json(data / "config.json", {})
                self.assertEqual(upgraded["class_name"], "旧安装班级")
                self.assertEqual(upgraded["assignments"], old_config["assignments"])
                self.assertEqual(upgraded["custom_user_setting"], {"keep": True})
                self.assertEqual(upgraded["version"], app_meta.APP_VERSION)
                for name, digest in protected.items():
                    self.assertEqual(file_digest(data / name), digest, name)
            finally:
                wizard.root.destroy()


class SilentUpgradeRuntimeTest(unittest.TestCase):
    def test_running_old_server_is_stopped_before_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "running-install"
            data = install / "data"
            desired = installer_core.build_default_config(
                class_name="运行测试班", class_folder=install / "class",
                organized_dir=install / "class" / "已收作业",
                experiment_dir=install / "class" / "实验", scan_dirs=[],
                file_types=[".docx"], version=app_meta.APP_VERSION,
            )
            plan = installer_core.build_data_plan(
                data, "new", desired, installer_core.build_course_rule_pack(["数字电子技术"])
            )
            installer_core.apply_install_plan(
                ROOT, install,
                ["server.py", "app_meta.py", "ai_classifier.py", "external_ai.py",
                 "classifier_features.py", "classifier_trainer.py", "installer_core.py",
                 "dashboard.html", "dashboard_modern.html"], plan,
            )
            port = free_port()
            process = subprocess.Popen(
                [sys.executable, str(install / "server.py"), "--port", str(port), "--no-watch"],
                cwd=install, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.time() + 15
                while not (data / "server.lock").exists():
                    if process.poll() is not None:
                        self.fail("测试服务启动失败")
                    if time.time() >= deadline:
                        self.fail("测试服务未生成锁文件")
                    time.sleep(0.1)
                stopped = installer_core.stop_running_install(install, timeout=8)
                self.assertTrue(stopped["running"])
                self.assertTrue(stopped["stopped"])
                process.wait(timeout=5)
                self.assertFalse((data / "server.lock").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)

    def test_old_install_upgrades_and_all_main_user_surfaces_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "Assignment Dashboard 用户安装"
            data = install / "data"
            models = data / "models"
            models.mkdir(parents=True)
            assignment = {
                "id": "m1", "name": "第一次实验", "subject_group": "数字电子技术",
                "experiment": "第一次实验", "keywords": ["GPIO"], "active": True,
            }
            old_config = {
                "class_name": "电国测试班",
                "class_folder": str(install / "class"),
                "organized_dir": str(install / "class" / "已收作业"),
                "experiment_dir": str(install / "class" / "实验"),
                "scan_dirs": [str(install / "incoming")],
                "watch_enabled": False,
                "assignments": [assignment],
                "ai_classifier": {"mode": "rules", "sensitivity": 0.7},
                "custom_user_setting": "must-survive",
                "version": "0.1.1",
            }
            students = [{"name": "测试学生", "student_id": "20260001"}]
            submissions = {"m1": [{"student": "测试学生", "status": "matched"}]}
            rules = installer_core.build_course_rule_pack(
                ["数字电子技术"], {"name": "测试包", "semester": "2026-2027-1"}
            )
            rules["subjects"]["数字电子技术"]["confirmed_aliases"] = ["数电"]
            rules["subjects"]["数字电子技术"]["keywords"] = ["GPIO", "触发器"]
            fixtures = {
                "config.json": old_config,
                "students.json": students,
                "submissions.json": submissions,
                "watcher_state.json": {"known_files": {}},
                "ai_rules.json": rules,
                "ai_examples.json": {"schema_version": 2, "data_version": 1, "items": [], "migrations": {}},
                "ai_secrets.json": {"api_key": "runtime-private-value"},
                "ai_external_history.json": {"items": []},
            }
            for name, payload in fixtures.items():
                installer_core.atomic_write_json(data / name, payload)
            (models / "keep.bin").write_bytes(b"user-model")
            protected_names = [
                "students.json", "submissions.json", "watcher_state.json", "ai_rules.json",
                "ai_examples.json", "ai_secrets.json", "ai_external_history.json", "models/keep.bin",
            ]
            before = {name: file_digest(data / name) for name in protected_names}

            desired = installer_core.build_default_config(
                class_name="不应覆盖的向导班级",
                class_folder=install / "new-class",
                organized_dir=install / "new-class" / "已收作业",
                experiment_dir=install / "new-class" / "实验",
                scan_dirs=[install / "new-scan"],
                file_types=[".pdf", ".docx"],
                version=installer.APP_VERSION,
                active_semester="新学期",
                class_aliases=["不应覆盖"],
            )
            plan = installer_core.build_data_plan(
                data, "auto", desired,
                installer_core.build_course_rule_pack(["不应自动导入的课程"]),
                apply_rules=False,
            )
            runtime_files = [
                "server.py", "app_meta.py", "ai_classifier.py", "external_ai.py", "classifier_features.py",
                "classifier_trainer.py", "installer_core.py", "restart_helper.py",
                "dashboard.html", "dashboard_modern.html", "pack.py", "repair_update.py",
            ]
            result = installer_core.apply_install_plan(ROOT, install, runtime_files, plan)
            self.assertEqual(result["mode"], "upgrade")
            for name, digest in before.items():
                self.assertEqual(file_digest(data / name), digest, name)

            upgraded = installer_core.load_json(data / "config.json", {})
            self.assertEqual(upgraded["class_name"], "电国测试班")
            self.assertEqual(upgraded["assignments"], [assignment])
            self.assertEqual(upgraded["custom_user_setting"], "must-survive")
            self.assertIn("ai_external", upgraded)
            self.assertEqual(upgraded["ai_classifier"]["mode"], "rules")
            self.assertIn("priority", upgraded["ai_classifier"])

            port = free_port()
            process = subprocess.Popen(
                [sys.executable, str(install / "server.py"), "--port", str(port), "--no-watch"],
                cwd=install,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            base = f"http://127.0.0.1:{port}"

            def request(path, data_value=None):
                raw = json.dumps(data_value, ensure_ascii=False).encode("utf-8") if data_value is not None else None
                req = urllib.request.Request(
                    base + path, data=raw,
                    method="POST" if data_value is not None else "GET",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    body = response.read()
                    if "application/json" in response.headers.get("Content-Type", ""):
                        return json.loads(body.decode("utf-8"))
                    return body.decode("utf-8")

            try:
                deadline = time.time() + 15
                while True:
                    if process.poll() is not None:
                        self.fail(f"升级后服务提前退出，代码 {process.returncode}")
                    try:
                        health = request("/api/health")
                        break
                    except Exception:
                        if time.time() >= deadline:
                            self.fail("升级后服务未在 15 秒内启动")
                        time.sleep(0.15)
                self.assertIsInstance(health, dict)
                modern_html = request("/modern")
                self.assertIn("课程作业运营台", modern_html)
                self.assertIn('id="page-brain"', modern_html)
                self.assertEqual(request("/api/students"), students)
                self.assertEqual(request("/api/submissions"), submissions)
                api_config = request("/api/config")
                self.assertEqual(api_config["class_name"], "电国测试班")
                self.assertNotIn("api_key", json.dumps(api_config))
                brain = request("/api/ai/brain")
                self.assertIn("model", brain)
                self.assertIn("external", brain)
                model_status = request("/api/ai/model/status")
                self.assertIn("state", model_status["model"])
                examples = request("/api/ai/examples")
                self.assertIn("items", examples)
                external = request("/api/ai/external/status")
                self.assertTrue(external["status"]["available"])
                self.assertNotIn("runtime-private-value", json.dumps(external))
                classified = request("/api/assignment/classify", {"file_name": "数电GPIO第一次实验.docx"})
                self.assertTrue(classified["ok"])
                self.assertEqual(classified["result"]["subject_group"], "数字电子技术")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for name, digest in before.items():
                if name == "ai_examples.json":
                    continue
                self.assertEqual(file_digest(data / name), digest, f"runtime changed {name}")
            migrated_examples = installer_core.load_json(data / "ai_examples.json", {})
            self.assertEqual(migrated_examples["items"], fixtures["ai_examples.json"]["items"])
            self.assertEqual(
                migrated_examples["data_version"], fixtures["ai_examples.json"]["data_version"]
            )
            self.assertIn(
                "match_feedback_subject_corrections_v1", migrated_examples["migrations"]
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
