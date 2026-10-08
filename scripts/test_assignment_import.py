"""Isolated upload/confirmation regressions; never writes production data."""
import argparse
import concurrent.futures
import io
import json
from pathlib import Path
import sys
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py" if (ROOT / "py").is_dir() else ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import server
from test_course_rules_editor import DisposableServer
from assignment_import import recognize, student_ref


def fixture(port=0):
    service = DisposableServer(port)
    root = Path(service.temp.name)
    cfg = server.load_config_raw()
    cfg.update({"organized_dir": str(root / "class" / "collected"), "auto_organize": False,
                "assignments": [{"id": "import-a", "name": "示例电路第一次报告", "subject_group": "示例电路", "subject": "示例电路",
                                 "experiment": "第一次", "active": True, "keywords": ["示例电路", "第一次"]},
                                {"id": "import-b", "name": "示例控制第二次报告", "subject_group": "示例控制", "subject": "示例控制",
                                 "experiment": "第二次", "active": True, "keywords": ["示例控制", "第二次"]}]})
    server.save_config(cfg)
    server.save_students([{"name": "张三", "student_id": "20260001", "pinyin": "zs"},
                          {"name": "李四", "student_id": "20260002", "pinyin": "ls"}])
    return service


def upload(service, files, aid="import-a", request_id=None):
    boundary = "----Import" + uuid.uuid4().hex
    chunks = []
    for name, value in (("assignment_id", aid), ("request_id", request_id or uuid.uuid4().hex)):
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, content in files:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(service.base + "/api/assignment-import/upload", data=b"".join(chunks),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Origin": service.base})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


class AssignmentImportTest(unittest.TestCase):
    def setUp(self):
        self.service = fixture()

    def tearDown(self):
        self.service.close()

    def resolve(self, item, name="李四", discard=False):
        student = next(s for s in server.load_students() if s["name"] == name)
        return self.service.request('/api/assignment-import/resolve', {"batch_id": item["batch_id"], "item_id": item["id"],
                                                                     "student_ref": student_ref(student), "discard": discard})

    def test_success_and_detail_counts_even_when_auto_organize_disabled(self):
        rows = upload(self.service, [("张三_report.docx", b"report one"), ("20260002.pdf", b"%PDF sample")])["items"]
        self.assertEqual([r["status"] for r in rows], ["imported", "imported"])
        detail = self.service.request('/api/assignment/import-a')
        self.assertEqual(detail["submitted_count"], 2)
        self.assertTrue(all(Path(r["file_path"]).is_file() for r in rows))

    def test_unknown_and_ambiguous_wait_for_confirmation(self):
        rows = upload(self.service, [("report.docx", b"unknown"), ("张三_李四.docx", b"ambiguous")])["items"]
        self.assertEqual([r["status"] for r in rows], ["pending", "pending"])
        self.assertEqual(self.service.request('/api/assignment/import-a')["submitted_count"], 0)
        result = self.resolve(rows[0])
        self.assertEqual(result["items"][0]["status"], "imported")
        self.assertEqual(self.service.request('/api/assignment/import-a')["submitted_count"], 1)

    def test_duplicate_hash_and_same_size_new_version(self):
        first = upload(self.service, [("张三.docx", b"AAAA")])["items"][0]
        duplicate = upload(self.service, [("张三_renamed.docx", b"AAAA")])["items"][0]
        version = upload(self.service, [("张三.docx", b"BBBB")])["items"][0]
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(version["status"], "imported")
        self.assertNotEqual(first["file_path"], version["file_path"])
        self.assertEqual(Path(first["file_path"]).read_bytes(), b"AAAA")
        self.assertEqual(len(server.load_submissions()["import-a"]), 2)
        detail = self.service.request('/api/assignment/import-a')
        self.assertEqual(detail["submitted_count"], 1)
        self.assertEqual(len(detail["submitted"][0]["files"]), 2)

    def test_watched_original_does_not_duplicate_or_reclassify_import(self):
        item = upload(self.service, [("张三_report.docx", b"watch later")])["items"][0]
        source = Path(self.service.temp.name) / 'watched' / '张三_report.docx'
        source.parent.mkdir()
        source.write_bytes(b"watch later")
        info = {"name": source.name, "path": str(source), "size": source.stat().st_size}
        record = server.process_new_file_atomic(info, server.load_students(), server.load_config_raw()['assignments'])
        self.assertEqual(record['source_kind'], 'assignment_import')
        self.assertEqual(sum(len(rows) for rows in server.load_submissions().values()), 1)

    def test_archives_are_opaque_and_never_extracted(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('../do-not-extract.txt', 'opaque')
        item = upload(self.service, [("张三.zip", data.getvalue())])["items"][0]
        self.assertEqual(item["status"], "imported")
        self.assertEqual(Path(item["file_path"]).read_bytes(), data.getvalue())
        self.assertFalse(list(Path(self.service.temp.name).rglob('do-not-extract.txt')))

    def test_bad_names_empty_files_and_extensions_rejected(self):
        rows = upload(self.service, [("../escape.docx", b"x"), ("张三.exe", b"x"), ("李四.docx", b"")])["items"]
        self.assertTrue(all(r["status"] == "error" and not r["stored"] for r in rows))
        self.assertFalse(server.load_submissions())

    def test_quoted_filename_delimiters_and_partial_batch(self):
        rows = upload(self.service, [("张三;报告.docx", b"valid file"), ("李四.exe", b"rejected")])["items"]
        self.assertEqual([r['status'] for r in rows], ['imported', 'error'])
        self.assertEqual(rows[0]['name'], '张三;报告.docx')
        self.assertEqual(self.service.request('/api/assignment/import-a')['submitted_count'], 1)

    def test_pending_survives_refresh_and_can_discard(self):
        item = upload(self.service, [("unknown.docx", b"unknown")])["items"][0]
        self.assertEqual(self.service.request('/api/assignment-import/status?assignment_id=import-a')["items"][0]["status"], "pending")
        path = Path(item["file_path"])
        self.assertTrue(server.is_allowed_file_path(str(path)))
        self.assertEqual(self.resolve(item, discard=True)["items"][0]["status"], "discarded")
        self.assertFalse(path.exists())

    def test_conflicting_course_requires_explicit_confirmation(self):
        item = upload(self.service, [("张三_示例控制第二次报告.docx", b"wrong course")])["items"][0]
        self.assertEqual(item["status"], "pending")
        result = self.resolve(item, name="张三")
        self.assertEqual(result["items"][0]["status"], "imported")
        self.assertEqual(self.service.request('/api/assignment/import-a')["submitted_count"], 1)
        self.assertEqual(self.service.request('/api/assignment/import-b')["submitted_count"], 0)

    def test_identical_request_id_is_idempotent(self):
        rid = uuid.uuid4().hex
        first = upload(self.service, [("张三.docx", b"one")], request_id=rid)
        second = upload(self.service, [("张三.docx", b"one")], request_id=rid)
        self.assertEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(len(server.load_submissions()["import-a"]), 1)

    def test_storage_failure_never_counts_submitted_and_can_retry(self):
        with patch.object(server, 'save_submissions', side_effect=OSError('fixture storage failure')):
            item = upload(self.service, [("张三.docx", b"failed save")])["items"][0]
        self.assertEqual(item["status"], "error")
        self.assertEqual(self.service.request('/api/assignment/import-a')["submitted_count"], 0)
        self.assertFalse(list((Path(self.service.temp.name) / 'class' / 'collected').rglob('*.docx')))
        self.assertEqual(self.resolve(item, name="张三")["items"][0]["status"], "imported")

    def test_concurrent_imports_preserve_both_students(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(upload, self.service, [(name + '.docx', name.encode())]) for name in ('张三', '李四')]
            self.assertTrue(all(f.result()['items'][0]['status'] == 'imported' for f in futures))
        self.assertEqual(self.service.request('/api/assignment/import-a')["submitted_count"], 2)

    def test_initials_and_same_name_are_not_automatic(self):
        students = server.load_students()
        self.assertFalse(recognize('zs_report.docx', students)[0])
        self.assertFalse(recognize('张三.docx', students + [{"name":"张三", "student_id":"other"}])[0])

    def test_sync_failure_is_separate_from_success(self):
        cfg = server.load_config_raw()
        invalid = Path(self.service.temp.name) / 'sync-blocker'
        invalid.write_text('not a directory')
        cfg.update({"experiment_enabled": True, "experiment_dir": str(invalid)})
        server.save_config(cfg)
        item = upload(self.service, [("张三.docx", b"valid archive")])["items"][0]
        self.assertEqual(item["status"], "imported")
        self.assertIn('warning', item)
        self.assertEqual(self.service.request('/api/assignment/import-a')["submitted_count"], 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=18868)
    args, rest = parser.parse_known_args()
    if args.serve:
        service = fixture(args.port)
        print('IMPORT_FIXTURE_READY ' + service.base, flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            service.close()
    else:
        unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
