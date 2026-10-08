"""Explicit assignment uploads. Archives are opaque files, never extracted."""
import hashlib
from email import policy
from email.parser import BytesParser
from pathlib import Path
import re
import shutil
import threading
import uuid
from datetime import datetime

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_REQUEST_BYTES = 100 * 1024 * 1024
MAX_FILES = 50
_lock = threading.RLock()
_ID = re.compile(r"^[0-9a-f]{32}$")


def parse_upload_parts(body, content_type):
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
    if not message.is_multipart():
        raise ValueError("上传表单无效")
    parts = []
    for part in message.iter_parts():
        if part.is_multipart() or part.get_content_disposition() != 'form-data':
            raise ValueError("不支持嵌套上传表单")
        parts.append({"name": part.get_param('name', header='Content-Disposition') or '',
                      "filename": part.get_filename() or '', "data": part.get_payload(decode=True) or b''})
        if len(parts) > MAX_FILES + 10:
            raise ValueError("上传表单项目过多")
    return parts


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def student_ref(student):
    return hashlib.sha256((str(student.get("name", "")) + "\0" + str(student.get("student_id", ""))).encode()).hexdigest()[:20]


def safe_name(value):
    name = str(value or "").strip()
    if (not name or len(name) > 180 or name in (".", "..") or
            re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name.endswith((".", " ")) or
            re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I)):
        raise ValueError("文件名或归档目录名称无效")
    return name


def recognize(filename, students):
    """Return unique strong evidence only; initials and ties need confirmation."""
    stem = Path(filename).stem.casefold()
    candidates = []
    for student in students:
        name = str(student.get("name") or "")
        sid = str(student.get("student_id") or "").strip()
        pinyin = str(student.get("pinyin") or "").strip().casefold()
        reasons = []
        if sid and re.search(r"(?<![0-9])" + re.escape(sid.casefold()) + r"(?![0-9])", stem):
            reasons.append("学号匹配")
        if name and name.casefold() in stem:
            reasons.append("完整姓名匹配")
        if pinyin and re.search(r"(?<![a-z])" + re.escape(pinyin) + r"(?![a-z])", stem):
            reasons.append("拼音匹配，需确认")
        if reasons:
            candidates.append({"ref": student_ref(student), "name": name, "student_id": sid,
                               "reasons": reasons, "strong": any(r != "拼音匹配，需确认" for r in reasons)})
    strong = [c for c in candidates if c["strong"]]
    if len(strong) == 1 and sum(s.get("name") == strong[0]["name"] for s in students) == 1:
        return strong[0]["ref"], candidates, ""
    return "", candidates, "多个候选或同名学生，请确认" if len(strong) > 1 or strong else "未识别出唯一学生，请选择学生"


class AssignmentImporter:
    def __init__(self, root, owner):
        self.root = Path(root).resolve()
        self.owner = owner

    def _assignment(self, aid):
        cfg = self.owner.load_config_raw()
        assignment = next((a for a in cfg.get("assignments", []) if a.get("id") == aid), None)
        if not assignment:
            raise ValueError("目标作业已不存在，请返回作业列表")
        return cfg, assignment

    def _batch(self, bid):
        if not _ID.fullmatch(str(bid)):
            raise ValueError("导入批次无效")
        path = self.root / bid / "batch.json"
        batch = self.owner.load_json(path, {})
        if not batch or batch.get("id") != bid:
            raise ValueError("导入批次不存在")
        return batch

    def _save(self, batch):
        self.owner.save_json(self.root / batch["id"] / "batch.json", batch)

    def _source(self, batch, item):
        path = self.root / batch["id"] / item["id"] / safe_name(item["name"])
        if not path.resolve().is_relative_to(self.root) or not path.is_file():
            raise ValueError("暂存文件不存在，请重新上传")
        return path

    def _public(self, batch):
        items = []
        for item in batch["items"]:
            public = {key: value for key, value in item.items() if key != "student_ref"}
            public["batch_id"] = batch["id"]
            public["assignment_id"] = batch["assignment_id"]
            if item["status"] in ("pending", "error") and item.get("stored"):
                public["file_path"] = str(self._source(batch, item)) if (self.root / batch["id"] / item["id"] / item["name"]).is_file() else ""
            items.append(public)
        return {"ok": True, "batch_id": batch["id"], "items": items}

    def status(self, aid):
        with _lock:
            self._assignment(aid)
            batches = []
            for path in self.root.glob("*/batch.json"):
                batch = self.owner.load_json(path, {})
                if batch.get("assignment_id") == aid:
                    batches.append(batch)
            batches.sort(key=lambda b: b.get("created_at", ""), reverse=True)
            items = []
            for i, batch in enumerate(batches):
                rows = self._public(batch)["items"]
                items.extend(rows if i < 5 else [r for r in rows if r["status"] in ("pending", "error")])
            students = self.owner.load_students()
            return {"ok": True, "items": items, "students": [
                {"ref": student_ref(s), "name": s.get("name", ""), "student_id": s.get("student_id", ""),
                 "disabled": sum(t.get("name") == s.get("name") for t in students) != 1}
                for s in students if s.get("name")], "max_file_bytes": MAX_FILE_BYTES, "max_files": MAX_FILES}

    def upload(self, aid, parts, request_id=""):
        with _lock:
            cfg, assignment = self._assignment(aid)
            files = [p for p in parts if p.get("filename")]
            if not files or len(files) > MAX_FILES:
                raise ValueError(f"每次请选择 1 至 {MAX_FILES} 个文件")
            bid = request_id or uuid.uuid4().hex
            if not _ID.fullmatch(bid):
                raise ValueError("请求标识无效")
            if (self.root / bid / "batch.json").exists():
                previous = self._batch(bid)
                if previous["assignment_id"] != aid:
                    raise ValueError("导入请求与目标作业不一致")
                return self._public(previous)
            batch = {"id": bid, "assignment_id": aid, "created_at": datetime.now().isoformat(), "items": []}
            students = self.owner.load_students()
            extensions = self.owner.configured_file_types(cfg)
            for part in files:
                item = {"id": uuid.uuid4().hex, "name": str(part["filename"]), "size": len(part.get("data", b"")),
                        "status": "error", "message": "", "stored": False, "candidates": []}
                batch["items"].append(item)
                try:
                    name = safe_name(item["name"])
                    if Path(name).suffix.lower() not in extensions:
                        raise ValueError("此文件类型未启用，请在管理页检查文件类型")
                    if not 0 < item["size"] <= MAX_FILE_BYTES:
                        raise ValueError("文件为空或超过单文件 50 MB 限制")
                    source = self.root / bid / item["id"] / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(part["data"])
                    item["stored"] = True
                    item["status"] = "pending"
                    ref, candidates, reason = recognize(name, students)
                    item.update({"candidates": candidates, "message": reason, "student_ref": ref})
                    # Explicit target wins only after conflicting filename evidence is reviewed.
                    probe = {"name": name, "path": str(source), "size": item["size"]}
                    result = self.owner.classify_file_subject(probe, cfg.get("assignments", []), cfg, source_kind="manual_import")
                    subject = assignment.get("subject_group") or assignment.get("subject", "")
                    if result.get("status") == "subject_matched" and result.get("subject_group") != subject:
                        item["message"] = "文件名识别到其他课程，请确认是否归入当前作业"
                        ref = ""
                    else:
                        match = self.owner.classify_assignment_in_subject(name, subject, cfg.get("assignments", []), cfg)
                        if match.get("status") == "matched" and match.get("assignment_id") != aid:
                            item["message"] = "文件名识别到其他作业，请确认当前归属"
                            ref = ""
                    self._save(batch)  # Keep the file and review state durable before committing.
                    if ref:
                        self._commit(batch, item, ref)
                except Exception as exc:
                    item.update({"status": "error", "message": str(exc)[:180]})
                self._save(batch)
            return self._public(batch)

    def _commit(self, batch, item, ref):
        with self.owner._submission_mutation_lock:
            cfg, assignment = self._assignment(batch["assignment_id"])
            students = self.owner.load_students()
            student = next((s for s in students if student_ref(s) == ref), None)
            if not student:
                raise ValueError("学生名单已变化，请重新选择学生")
            if sum(s.get("name") == student.get("name") for s in students) != 1:
                raise ValueError("名单存在同名学生；当前统计按姓名关联，请先在名单中区分姓名，避免错误计数")
            source = self._source(batch, item)
            content_hash = digest(source)
            submissions = self.owner.load_submissions()
            records = submissions.setdefault(assignment["id"], [])
            for record in records:
                if record.get("student") != student["name"]:
                    continue
                old = (record.get("file") or {})
                existing = self.owner.is_allowed_file_path(record.get("organized_to") or old.get("path", ""))
                if existing and self.owner.file_size(existing) == item["size"] and digest(existing) == content_hash:
                    item.update({"status": "duplicate", "message": "内容已收录，未新增记录", "student": student["name"], "file_path": str(existing)})
                    return
            root = Path(cfg.get("organized_dir") or self.owner.ORGANIZED_DIR).resolve()
            subject = safe_name(assignment.get("subject_group") or assignment.get("subject") or "未命名课程")
            experiment = str(assignment.get("experiment") or "").strip()
            directory = root / subject
            if experiment:
                directory /= safe_name(experiment)
            directory /= safe_name(student["name"])
            if not directory.resolve().is_relative_to(root):
                raise ValueError("目标归档路径无效")
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / safe_name(item["name"])
            if target.exists():
                target = directory / f"{target.stem[:130]}_版本-{uuid.uuid4().hex[:12]}{target.suffix}"
            copied = False
            try:
                with source.open("rb") as src, target.open("xb") as dst:
                    copied = True
                    shutil.copyfileobj(src, dst)
                if digest(target) != content_hash:
                    raise OSError("归档文件校验失败")
                record = {"file": {"name": item["name"], "path": str(target), "size": item["size"]},
                          "student": student["name"], "student_id": student.get("student_id", ""),
                          "assignment_id": assignment["id"], "assignment_name": assignment.get("name", ""),
                          "subject_group": subject, "status": "manual_matched", "organized_to": str(target),
                          "source_kind": "assignment_import", "content_sha256": content_hash,
                          "detected_at": datetime.now().isoformat(), "import_item_id": item["id"],
                          "classification": {"stage": "manual_matched", "subject_group": subject,
                                             "assignment_id": assignment["id"], "source_kind": "assignment_import",
                                             "evidence": ["从作业详情导入，目标作业由用户确定"]}}
                records.append(record)
                self.owner.save_submissions(submissions)
            except Exception:
                if copied:
                    target.unlink(missing_ok=True)
                raise
            item.update({"status": "imported", "student": student["name"], "student_ref": ref,
                         "message": "已归档并记入提交", "file_path": str(target)})
            # Synchronization is secondary; a failure must not undo a valid submission.
            try:
                if cfg.get("experiment_enabled"):
                    sync_root = Path(cfg.get("experiment_dir") or self.owner.EXPERIMENT_BASE).resolve()
                    sync_dir = sync_root / subject
                    if experiment:
                        sync_dir /= safe_name(experiment)
                    if not sync_dir.resolve().is_relative_to(sync_root):
                        raise OSError("同步目录无效")
                    sync_dir.mkdir(parents=True, exist_ok=True)
                    sync_file = sync_dir / safe_name(self.owner._experiment_dest_name(target.name, student["name"]))
                    if sync_file.exists() and digest(sync_file) != content_hash:
                        sync_file = sync_dir / f"{sync_file.stem[:130]}_版本-{uuid.uuid4().hex[:12]}{sync_file.suffix}"
                    if not sync_file.exists():
                        with target.open("rb") as src, sync_file.open("xb") as dst:
                            shutil.copyfileobj(src, dst)
                    if digest(sync_file) != content_hash:
                        raise OSError("同步副本校验失败")
            except Exception:
                item["warning"] = "已入库，但同步文件夹写入失败；请检查同步位置"

    def resolve(self, bid, iid, ref="", discard=False):
        with _lock:
            batch = self._batch(bid)
            if not _ID.fullmatch(str(iid)):
                raise ValueError("文件标识无效")
            item = next((i for i in batch["items"] if i["id"] == iid), None)
            if not item:
                raise ValueError("文件不存在")
            if item["status"] not in ("pending", "error"):
                return self._public(batch)
            if discard:
                if item.get("stored"):
                    self._source(batch, item).unlink()
                item.update({"status": "discarded", "message": "已取消导入，不影响原文件", "stored": False})
            else:
                try:
                    self._commit(batch, item, ref or item.get("student_ref", ""))
                except Exception as exc:
                    item.update({"status": "error", "message": str(exc)[:180]})
            self._save(batch)
            return self._public(batch)
