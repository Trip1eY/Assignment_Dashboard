"""Installation-flow checks using source or the actual frozen installer bytecode."""
import argparse
import hashlib
import json
import marshal
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py"))
import installer


class RootQueue:
    def __init__(self):
        self.callbacks = []

    def after(self, _delay, callback):
        self.callbacks.append(callback)

    def drain(self):
        while self.callbacks:
            self.callbacks.pop(0)()


class InstallerReleaseTest(unittest.TestCase):
    module = installer

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dashboard-installer-validation-")
        self.base = Path(self.temp.name)
        self.target = self.base / "application"
        self.home = self.base / "home"
        parent = os.environ.get("ASSIGNMENT_DASHBOARD_BACKUP_DIR")
        self.external = tempfile.TemporaryDirectory(prefix="installer-test-", dir=parent) if parent else None
        self.backups = Path(self.external.name) if self.external else self.base / "rollback"
        self.env = patch.dict(os.environ, {"ASSIGNMENT_DASHBOARD_BACKUP_DIR": str(self.backups)})
        self.env.start()
        self.expand = patch.object(self.module.os.path, "expanduser", side_effect=lambda p: str(self.home) if p == "~" else p)
        self.expand.start()
        self.wizard = self.module.InstallerWizard.__new__(self.module.InstallerWizard)
        self.wizard.install_dir = str(self.target)
        self.wizard.root = RootQueue()
        self.wizard.btn_next = types.SimpleNamespace(configure=lambda **kwargs: None)
        self.wizard.logs, self.wizard.errors, self.wizard.progress = [], [], []
        self.wizard._log = lambda message, level="INFO": self.wizard.logs.append((level, message))
        self.wizard._set_progress = lambda value, text: self.wizard.progress.append(value)
        self.wizard._install_failed = lambda title, message: self.wizard.errors.append(message)
        self.wizard._python_cmd = sys.executable

    def tearDown(self):
        self.expand.stop()
        self.env.stop()
        self.temp.cleanup()
        if self.external:
            self.external.cleanup()

    def install(self, python_ok=True):
        self.wizard._do_install(str(self.target), "安装验证班", False, [".pdf"], "",
                                [str(self.target / "homework")], {"测试课": ["关键词"]}, python_ok)
        self.wizard.root.drain()

    def seed(self):
        data = self.target / "data"
        data.mkdir(parents=True)
        cfg = {"class_name": "保留班级", "version": "0.1.1", "port": 19991,
               "class_folder": str(self.base / "class"), "organized_dir": str(self.base / "organized"),
               "experiment_dir": str(self.base / "sync"), "scan_dirs": [str(self.base / "incoming")],
               "assignments": [{"id": "fixture", "name": "历史作业"}], "theme": "custom-fixture",
               "ai_classifier": {"mode": "hybrid", "sensitivity": 0.81}}
        (data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        values = {"students.json": '[{"name":"虚构学生"}]', "submissions.json": '{"fixture":{"ok":true}}',
                  "watcher_state.json": '{"known_files":{"fixture":true}}', "rules.json": '{"course":"保留课程"}'}
        for name, value in values.items():
            (data / name).write_text(value, encoding="utf-8")
        return cfg, {name: (data / name).read_bytes() for name in values}

    def test_fresh_install_complete_resources_and_version(self):
        self.install()
        self.assertEqual(self.wizard.errors, [])
        self.assertIn(100, self.wizard.progress)
        manifest = json.loads((self.target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], self.module.APP_VERSION)
        self.assertTrue(manifest["has_announcement"])
        for name in self.module.INSTALL_FILES:
            self.assertEqual((self.target / name).read_bytes(), Path(self.module.get_resource_path(name)).read_bytes(), name)
        config = json.loads((self.target / "data/config.json").read_text(encoding="utf-8"))
        self.assertNotIn(config["experiment_dir"], config["scan_dirs"])
        bat = (self.target / "启动作业追踪器.bat").read_text(encoding="utf-8")
        self.assertIn(sys.executable, bat)

    def test_upgrade_preserves_user_configuration_and_records(self):
        cfg, old = self.seed()
        self.install()
        self.assertEqual(self.wizard.errors, [])
        cfg["version"] = self.module.APP_VERSION
        self.assertEqual(cfg, json.loads((self.target / "data/config.json").read_text(encoding="utf-8")))
        for name, data in old.items():
            self.assertEqual(data, (self.target / "data" / name).read_bytes())

    def test_missing_resource_stops_before_target_is_created(self):
        original = self.module.get_resource_path
        with patch.object(self.module, "get_resource_path", side_effect=lambda name:
                          str(self.base / "missing") if name.endswith("github_updates.py") else original(name)):
            self.install()
        self.assertFalse(self.target.exists())
        self.assertIn("缺少必要文件", self.wizard.errors[0])

    def test_invalid_existing_configuration_is_not_overwritten(self):
        self.seed()
        config = self.target / "data/config.json"
        config.write_bytes(b"invalid JSON")
        self.install()
        self.assertTrue(self.wizard.errors)
        self.assertEqual(config.read_bytes(), b"invalid JSON")
        self.assertFalse((self.target / "py").exists())

    def test_copy_failure_rolls_back_existing_files_and_version(self):
        self.seed()
        config_before = (self.target / "data/config.json").read_bytes()
        program = self.target / "py/server.py"
        program.parent.mkdir()
        program.write_bytes(b"old-program-fixture")
        copy = self.wizard._copy_install_file
        count = 0

        def fail(journal, src, dst):
            nonlocal count
            count += 1
            if count == 5:
                raise OSError("模拟复制失败")
            return copy(journal, src, dst)

        with patch.object(self.wizard, "_copy_install_file", side_effect=fail):
            self.install()
        self.assertIn("模拟复制失败", self.wizard.errors[0])
        self.assertEqual(program.read_bytes(), b"old-program-fixture")
        self.assertEqual(config_before, (self.target / "data/config.json").read_bytes())
        self.assertFalse((self.target / "py/github_updates.py").exists())

    def test_failed_restore_retains_external_rollback_backup(self):
        self.target.mkdir()
        victim = self.target / "fixture.txt"
        victim.write_bytes(b"before")
        journal = self.wizard._new_install_journal(str(self.target))
        self.wizard._write_text_file(journal, str(victim), "after")
        with patch.object(self.module.shutil, "copy2", side_effect=OSError("restore failed")):
            self.wizard._rollback(str(self.target), journal)
        self.assertTrue(Path(journal["backup_dir"]).is_dir())
        self.assertTrue(any("保留回滚备份" in message for _, message in self.wizard.logs))

    def test_embedded_python_files_are_restored_after_later_failure(self):
        self.seed()
        executable = self.target / "python/python.exe"
        executable.parent.mkdir()
        executable.write_bytes(b"previous-python-fixture")

        def download(_url, path, _progress):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("python.exe", b"new-python-fixture")
                archive.writestr("new.dll", b"new-dll-fixture")

        with patch.object(self.module.urllib.request, "urlretrieve", side_effect=download), \
                patch.object(self.module.tempfile, "gettempdir", return_value=str(self.base)), \
                patch.object(self.wizard, "_copy_install_file", side_effect=OSError("later failure")):
            self.install(python_ok=False)
        self.assertTrue(self.wizard.errors)
        self.assertEqual(executable.read_bytes(), b"previous-python-fixture")
        self.assertFalse((self.target / "python/new.dll").exists())

    def test_python_38_is_rejected(self):
        versions = [types.SimpleNamespace(returncode=0, stdout="Python 3.8.10", stderr=""),
                    types.SimpleNamespace(returncode=0, stdout="Python 3.10.11", stderr="")]
        with patch.object(self.module.subprocess, "run", side_effect=versions), \
                patch.object(self.module.shutil, "which", return_value="C:/fixture/python3.exe"):
            self.assertEqual(self.wizard._find_python(), ("C:/fixture/python3.exe", "Python 3.10.11"))


def validate_binary(path):
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(path))
    entries = {name.replace("\\", "/"): name for name in archive.toc}
    for name in installer.INSTALL_FILES + ["announcement.json"]:
        data = archive.extract(entries[name])
        if hashlib.sha256(data).digest() != hashlib.sha256((ROOT / name).read_bytes()).digest():
            raise AssertionError(f"Bundled resource differs from current source: {name}")
    module = types.ModuleType("installer_binary_validation")
    module.__file__ = str(ROOT / "py/installer.py")
    exec(marshal.loads(archive.extract("installer")), module.__dict__)
    if module.APP_VERSION != installer.APP_VERSION:
        raise AssertionError("Frozen installer version is stale")
    module.get_resource_path = lambda name: str(ROOT / name)
    InstallerReleaseTest.module = module
    print(f"BINARY_RESOURCE_HASHES_OK {len(installer.INSTALL_FILES) + 1}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    if args.binary:
        validate_binary(args.binary)
    unittest.main(argv=[sys.argv[0]], verbosity=2)
