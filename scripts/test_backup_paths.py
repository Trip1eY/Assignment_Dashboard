"""Backup configuration stays private and invalid paths fail closed."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py" if (ROOT / "py").is_dir() else ROOT))
from backup_paths import backup_directory


class BackupPathsTest(unittest.TestCase):
    def test_default_and_private_configuration(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ASSIGNMENT_DASHBOARD_BACKUP_DIR": ""}):
            root = Path(tmp)
            self.assertEqual(backup_directory(root), root / "backups")
            (root / "data").mkdir()
            target = root / "external" / "backups"
            (root / "data" / "backup_location.json").write_text(json.dumps({"directory": str(target)}), encoding="utf-8")
            self.assertEqual(backup_directory(root), target)
            self.assertFalse(target.exists())

    def test_environment_has_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "backup_location.json").write_text('{"directory":"invalid-relative"}', encoding="utf-8")
            with patch.dict(os.environ, {"ASSIGNMENT_DASHBOARD_BACKUP_DIR": str(root / "override")}):
                self.assertEqual(backup_directory(root), root / "override")

    def test_invalid_settings_do_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ASSIGNMENT_DASHBOARD_BACKUP_DIR": ""}):
            root = Path(tmp)
            (root / "data").mkdir()
            settings = root / "data" / "backup_location.json"
            for content in ('{"directory":"relative"}', '{"directory":""}', '{"directory":123}', 'broken-json'):
                settings.write_text(content, encoding="utf-8")
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    backup_directory(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
