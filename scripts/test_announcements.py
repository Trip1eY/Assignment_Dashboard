"""Announcement package regression checks; fixtures use temporary directories only."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py" if (ROOT / "py").is_dir() else ROOT))
import pack
import server


class AnnouncementPackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patcher = patch.object(pack, "BASE_DIR", str(self.root))
        self.patcher.start()
        self.source = self.root / "announcement.json"

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def write_fixture(self, data):
        self.source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def archive(self, **kwargs):
        return pack.create_update_package(version="0.1.2", file_list=[], **kwargs)

    def test_new_package_version_preserves_source_and_history(self):
        self.write_fixture({"version": "0.1.1", "announcements": [
            {"id": "fixture", "title": "测试公告", "version": "0.1.1", "content": "内容"}]})
        before = self.source.read_bytes()
        archive = self.archive()
        self.assertTrue(Path(archive).name.startswith("dashboard_update_v0.1.2_"))
        with zipfile.ZipFile(archive) as zf:
            ann = json.loads(zf.read("announcement.json"))
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["version"], ann["version"])
        self.assertEqual("0.1.2", ann["version"])
        self.assertEqual("0.1.1", ann["announcements"][0]["version"])
        self.assertTrue(manifest["has_announcement"])
        self.assertEqual(before, self.source.read_bytes())

    def test_explicit_announcement_is_not_duplicated(self):
        self.write_fixture({"announcements": []})
        archive = pack.create_update_package(version="0.1.2", file_list=["announcement.json"])
        with zipfile.ZipFile(archive) as zf:
            self.assertEqual(1, zf.namelist().count("announcement.json"))

    def test_missing_announcement(self):
        with zipfile.ZipFile(self.archive()) as zf:
            self.assertNotIn("announcement.json", zf.namelist())
            self.assertFalse(json.loads(zf.read("manifest.json"))["has_announcement"])

    def test_excluded_announcement(self):
        self.write_fixture({"announcements": []})
        with patch.dict(pack.PACK_CONFIG, exclude_patterns=["announcement.json"]):
            with zipfile.ZipFile(self.archive()) as zf:
                self.assertNotIn("announcement.json", zf.namelist())
                self.assertFalse(json.loads(zf.read("manifest.json"))["has_announcement"])

    def test_malformed_announcement_rejected_before_archive_created(self):
        for invalid in ([], {}, {"announcements": {}}, {"announcements": ["bad"]}):
            with self.subTest(invalid=invalid):
                self.write_fixture(invalid)
                with self.assertRaises(ValueError):
                    self.archive()
                self.assertFalse((self.root / pack.PACK_CONFIG["output_dir"]).exists())
        self.source.write_text("{bad", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            self.archive()

    def test_utf8_bom(self):
        self.source.write_text('{"version":"old","announcements":[]}', encoding="utf-8-sig")
        with zipfile.ZipFile(self.archive()) as zf:
            self.assertEqual("0.1.2", json.loads(zf.read("announcement.json"))["version"])

    def test_browser_package_round_trip(self):
        class Response:
            def __init__(self):
                self.wfile = io.BytesIO()
                self.headers = {}
            def send_response(self, status):
                self.status = status
            def send_header(self, name, value):
                self.headers[name] = value
            def end_headers(self):
                pass
            def _json(self, value):
                raise AssertionError(value)
        response = Response()
        items = [{"id": "fixture", "title": "新版公告", "content": "内容", "version": "0.1.2"}]
        with patch.object(server, "BASE_DIR", self.root):
            server.APIHandler._build_update_package(response, {"version": "0.1.2", "announcements": items})
        self.assertEqual(200, response.status)
        with zipfile.ZipFile(io.BytesIO(response.wfile.getvalue())) as zf:
            self.assertEqual(items, json.loads(zf.read("announcement.json"))["announcements"])
            self.assertEqual("0.1.2", json.loads(zf.read("announcement.json"))["version"])
            self.assertEqual("0.1.2", json.loads(zf.read("manifest.json"))["version"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
