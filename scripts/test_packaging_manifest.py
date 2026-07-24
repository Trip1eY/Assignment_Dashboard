"""Regression tests for files required by installers and update packages."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = {
    "server.py",
    "ai_classifier.py",
    "restart_helper.py",
    "dashboard.html",
    "dashboard_modern.html",
}


def literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path.name}")


def spec_data_files(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "Analysis":
            continue
        datas = next(keyword.value for keyword in node.keywords if keyword.arg == "datas")
        return {source for source, _destination in ast.literal_eval(datas)}
    raise AssertionError(f"Analysis(datas=...) not found in {path.name}")


class PackagingManifestTest(unittest.TestCase):
    def test_installer_contains_runtime_files(self):
        install_files = set(literal_assignment(ROOT / "installer.py", "INSTALL_FILES"))
        self.assertTrue(RUNTIME_FILES <= install_files)
        self.assertTrue(install_files <= spec_data_files(ROOT / "微信作业追踪器_安装向导.spec"))

    def test_update_package_contains_runtime_files(self):
        config = literal_assignment(ROOT / "pack.py", "PACK_CONFIG")
        self.assertTrue(RUNTIME_FILES <= set(config["include_files"]))

    def test_update_backup_contains_runtime_files(self):
        backup_files = set(literal_assignment(ROOT / "repair_update.py", "COMMON_BACKUP_FILES"))
        self.assertTrue(RUNTIME_FILES <= backup_files)


if __name__ == "__main__":
    unittest.main(verbosity=2)
