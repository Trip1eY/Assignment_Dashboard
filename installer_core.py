#!/usr/bin/env python3
"""Headless installation and upgrade planning for Assignment Dashboard."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path


INSTALL_MODES = {"auto", "new", "upgrade", "repair"}
INSTALL_SCHEMA_VERSION = 2
PROTECTED_RUNTIME_NAMES = {
    "students.json",
    "submissions.json",
    "watcher_state.json",
    "ai_examples.json",
    "ai_secrets.json",
    "ai_external_history.json",
}

DEFAULT_TYPES = {
    "实验报告": ["实验", "报告", "实验报告", "lab"],
    "课后题": ["习题", "作业题", "课后题", "练习"],
    "复习资料": ["复习", "题库", "试卷", "答案"],
    "课程设计": ["课程设计", "课设", "项目"],
    "课程论文": ["课程论文", "论文"],
}

DEFAULT_EXTERNAL_SETTINGS = {
    "enabled": False,
    "provider": "ollama",
    "endpoint": "http://localhost:11434/api/generate",
    "model": "qwen2.5:0.5b",
    "strategy": "uncertain",
    "suggestion_only": True,
    "timeout_seconds": 8,
    "minute_limit": 5,
    "daily_limit": 100,
    "min_confidence": 0.75,
}

DEFAULT_UI_THEME = {
    "active": "clean-blue",
    "style": "modern",
    "apply_to_classic": True,
    "publish_with_update": True,
    "force_publish_theme": False,
    "custom": {
        "primary": "#2563eb",
        "accent": "#10b981",
        "background": "#f8fafc",
        "surface": "#ffffff",
        "text": "#0f172a",
        "border": "#dbe3ef",
    },
}


def _clean_list(values, limit=100, item_limit=100):
    if isinstance(values, str):
        values = re.split(r"[\n,，;；、]+", values)
    result = []
    for value in values or []:
        text = str(value or "").strip()[:item_limit]
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def detect_install_mode(install_dir, requested="auto"):
    requested = str(requested or "auto").strip().lower()
    if requested not in INSTALL_MODES:
        raise ValueError(f"不支持的安装模式：{requested}")
    root = Path(install_dir)
    has_config = (root / "data" / "config.json").is_file()
    has_program = (root / "server.py").is_file()
    if requested == "new":
        if has_config:
            raise ValueError("目标目录已有用户配置，不能执行全新安装；请选择升级模式")
        return "new"
    if requested == "upgrade":
        if not has_config:
            raise ValueError("目标目录没有 data/config.json，无法执行升级")
        return "upgrade"
    if requested == "repair":
        if not has_program:
            raise ValueError("目标目录没有 server.py，无法执行修复")
        return "repair"
    if has_config:
        return "upgrade"
    if has_program:
        return "repair"
    return "new"


def merge_missing(existing, defaults):
    """Recursively add new defaults while preserving every existing value."""
    if not isinstance(existing, dict):
        return copy.deepcopy(defaults)
    result = copy.deepcopy(existing)
    for key, value in (defaults or {}).items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_missing(result[key], value)
    return result


def build_default_config(
    *,
    class_name,
    class_folder,
    organized_dir,
    experiment_dir,
    scan_dirs,
    file_types,
    version,
    active_semester="",
    class_aliases=None,
):
    return {
        "class_name": str(class_name or "课程班级").strip()[:80] or "课程班级",
        "class_folder": str(class_folder),
        "wechat_accounts": [],
        "watch_enabled": True,
        "auto_organize": True,
        "organized_dir": str(organized_dir),
        "experiment_enabled": False,
        "experiment_dir": str(experiment_dir),
        "assignments": [],
        "poll_interval": 5,
        "file_keywords": ["作业", "报告", "论文", "实验", "习题", "课设"],
        "scan_dirs": _clean_list(scan_dirs, 50, 500),
        "file_types": _clean_list(file_types, 100, 20),
        "templates": [],
        "ignored_files": [],
        "ignored_subjects": [],
        "ignored_assignments": [],
        "ui_theme": copy.deepcopy(DEFAULT_UI_THEME),
        "default_frontend": "modern",
        "lan_access_enabled": False,
        "lan_access_token": "",
        "preview_warmup_enabled": False,
        "preview_warmup_limit": 20,
        "preview_conversion_timeout": 45,
        "port": 18765,
        "auto_scan_interval": 30,
        "auto_generate_assignments_from_experiment": False,
        "ai_classifier": {
            "mode": "rules",
            "sensitivity": 0.70,
            "sensitivity_preset": "balanced",
            "active_semester": str(active_semester or "").strip()[:100],
            "priority": "rules_first",
            "auto_train": True,
            "class_aliases": _clean_list(class_aliases, 30, 80),
        },
        "ai_external": copy.deepcopy(DEFAULT_EXTERNAL_SETTINGS),
        "version": str(version or "0.0.0"),
        "installer_schema_version": INSTALL_SCHEMA_VERSION,
    }


def empty_rule_pack(profile=None):
    profile = profile if isinstance(profile, dict) else {}
    return {
        "schema_version": 1,
        "profile": {
            key: str(profile.get(key) or "").strip()[:100]
            for key in ("name", "major", "grade", "semester", "school")
        },
        "subjects": {},
        "types": copy.deepcopy(DEFAULT_TYPES),
    }


def build_course_rule_pack(courses, profile=None):
    result = empty_rule_pack(profile)
    for course in _clean_list(courses, 100, 80):
        result["subjects"][course] = {
            "active": True,
            "confirmed_aliases": [],
            "suggested_aliases": [],
            "keywords": [],
            "assignment_types": [],
            "source": "installer",
        }
    return result


def validate_rule_pack(payload, allowed_courses=None):
    try:
        import ai_classifier
    except Exception as exc:
        raise ValueError(f"专业包校验模块不可用：{type(exc).__name__}") from exc
    try:
        return ai_classifier.normalize_rule_pack(
            payload,
            allowed_subjects=_clean_list(allowed_courses, 100, 80) or None,
        )["rule_pack"]
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def merge_rule_pack_for_semester(current, incoming):
    incoming = validate_rule_pack(incoming)
    try:
        current = validate_rule_pack(current)
    except ValueError:
        current = empty_rule_pack()
    old_semester = str((current.get("profile") or {}).get("semester") or "").strip()
    new_semester = str((incoming.get("profile") or {}).get("semester") or "").strip()
    if new_semester and new_semester != old_semester:
        for item in current.get("subjects", {}).values():
            item["active"] = False
    try:
        import ai_classifier
        return ai_classifier.merge_rule_packs(current, incoming)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def build_data_plan(data_dir, mode, desired_config, desired_rules=None, apply_rules=False):
    data_dir = Path(data_dir)
    mode = detect_install_mode(data_dir.parent, mode)
    plan = {
        "mode": mode,
        "config": None,
        "rules": None,
        "initialize": {},
        "preserved": [],
    }
    if mode == "repair":
        plan["preserved"] = sorted(PROTECTED_RUNTIME_NAMES | {"config.json", "ai_rules.json", "models"})
        return plan

    config_path = data_dir / "config.json"
    if mode == "upgrade" and config_path.exists():
        existing = load_json(config_path, {})
        if not isinstance(existing, dict):
            raise ValueError("现有 data/config.json 不是有效 JSON 对象，已停止升级")
        for name in sorted(PROTECTED_RUNTIME_NAMES):
            protected_path = data_dir / name
            if not protected_path.exists():
                continue
            try:
                load_json(protected_path)
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                raise ValueError(f"现有 data/{name} 无法读取，已停止升级：{exc}") from exc
        config = merge_missing(existing, desired_config)
        config["version"] = desired_config.get("version", config.get("version", ""))
        config["installer_schema_version"] = INSTALL_SCHEMA_VERSION
    else:
        config = copy.deepcopy(desired_config)
    plan["config"] = config

    rules_path = data_dir / "ai_rules.json"
    if mode == "new":
        plan["rules"] = validate_rule_pack(desired_rules or empty_rule_pack())
    elif apply_rules:
        current = load_json(rules_path, empty_rule_pack())
        plan["rules"] = merge_rule_pack_for_semester(current, desired_rules or empty_rule_pack())
    elif rules_path.exists():
        # Do not rewrite a user's pack during a normal upgrade, but refuse to
        # advertise a successful upgrade when the preserved pack is unreadable.
        validate_rule_pack(load_json(rules_path, {}))
    else:
        plan["rules"] = empty_rule_pack()

    initial = {
        "students.json": [],
        "submissions.json": {},
        "watcher_state.json": {"known_files": {}},
    }
    for name, payload in initial.items():
        if not (data_dir / name).exists():
            plan["initialize"][name] = payload
        else:
            plan["preserved"].append(name)
    for name in PROTECTED_RUNTIME_NAMES - set(initial):
        if (data_dir / name).exists():
            plan["preserved"].append(name)
    if (data_dir / "models").exists():
        plan["preserved"].append("models")
    return plan


def professional_pack_prompt(profile, courses):
    try:
        import ai_classifier
        return ai_classifier.build_professional_pack_prompt(profile or {}, _clean_list(courses, 100, 80))
    except Exception:
        course_lines = "\n".join(f"- {item}" for item in _clean_list(courses, 100, 80))
        return (
            "请为以下正式课程生成 Assignment Dashboard schema_version=1 专业包 JSON。"
            "不得新增课程，只输出 JSON。\n正式课程：\n" + (course_lines or "- 请先填写课程")
        )


def ollama_status(timeout=0.35):
    """Fast, silent and non-blocking-enough detection; never installs anything."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8"))
        models = [str(item.get("name") or "") for item in payload.get("models", []) if isinstance(item, dict)]
        return {"available": True, "models": [item for item in models if item][:50]}
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return {"available": False, "models": []}


def _process_is_running(pid):
    if not pid:
        return False
    if os.name == "nt":
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return str(int(pid)) in result.stdout
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def stop_running_install(install_dir, timeout=8.0):
    """Ask the existing local server to stop before replacing program files."""
    import time
    import urllib.error
    import urllib.request

    lock_path = Path(install_dir) / "data" / "server.lock"
    if not lock_path.exists():
        return {"running": False, "stopped": True}
    try:
        lock = load_json(lock_path, {})
        pid = int(lock.get("pid") or 0)
        port = int(lock.get("port") or 18765)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"running": False, "stopped": True}
    if not _process_is_running(pid):
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"running": False, "stopped": True}

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/server/shutdown",
        data=b"{}", method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read(4096)
    except (OSError, urllib.error.URLError):
        raise RuntimeError(
            f"检测到作业追踪器仍在运行（PID {pid}），但无法安全请求关闭。请先关闭旧服务再重试。"
        )
    deadline = time.time() + max(1.0, float(timeout))
    while time.time() < deadline:
        if not _process_is_running(pid):
            return {"running": True, "stopped": True, "pid": pid}
        time.sleep(0.15)
    raise RuntimeError(f"旧服务（PID {pid}）未在限定时间内退出，升级已停止")


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


class InstallTransaction:
    """One install-wide rollback journal shared by GUI and silent installs."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        root_existed = self.root.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        self.backup_dir = Path(tempfile.mkdtemp(prefix="assignment_dashboard_install_rollback_"))
        self.files = {}
        self.created_dirs = [] if root_existed else [self.root]
        self.closed = False

    def ensure_dir(self, path):
        path = Path(path).resolve()
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if not existed and path not in self.created_dirs:
            self.created_dirs.append(path)
        return path

    def remember(self, path):
        path = Path(path).resolve()
        if path in self.files:
            return path
        self.ensure_dir(path.parent)
        if path.exists():
            backup = self.backup_dir / f"{uuid.uuid4().hex}_{path.name}"
            shutil.copy2(path, backup)
            self.files[path] = backup
        else:
            self.files[path] = None
        return path

    def copy_file(self, source, target):
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(f"安装资源缺失：{source.name}")
        target = self.remember(target)
        temp = target.with_name(target.name + f".{os.getpid()}.installing")
        try:
            shutil.copy2(source, temp)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def write_json(self, target, payload):
        target = self.remember(target)
        atomic_write_json(target, payload)

    def write_text(self, target, content):
        target = self.remember(target)
        temp = target.with_name(target.name + f".{os.getpid()}.installing")
        try:
            with temp.open("w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def rollback(self):
        errors = []
        for path, backup in reversed(list(self.files.items())):
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, path)
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        for path in reversed(self.created_dirs):
            try:
                if path.exists():
                    shutil.rmtree(path)
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            raise RuntimeError("安装回滚未完整完成：" + "; ".join(errors[:5]))

    def close(self):
        if not self.closed:
            shutil.rmtree(self.backup_dir, ignore_errors=True)
            self.closed = True


def apply_install_plan(
    source_dir,
    install_dir,
    program_files,
    data_plan,
    *,
    fail_after=None,
):
    """Apply a tested install plan atomically enough for upgrades and repairs.

    Existing files are copied to a temporary rollback directory before writes.
    Runtime data not named by ``data_plan`` is never enumerated or modified.
    """
    source_dir = Path(source_dir).resolve()
    install_dir = Path(install_dir).resolve()
    transaction = InstallTransaction(install_dir)
    operations = 0

    def check_failure():
        nonlocal operations
        operations += 1
        if fail_after is not None and operations >= int(fail_after):
            raise RuntimeError("injected install failure")

    try:
        copied = []
        for name in program_files:
            relative = Path(str(name))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"程序文件路径无效：{name}")
            source = source_dir / relative
            if not source.is_file():
                raise FileNotFoundError(f"安装资源缺失：{relative.as_posix()}")
            target = install_dir / relative
            transaction.copy_file(source, target)
            copied.append(relative.as_posix())
            check_failure()

        written = []
        data_dir = install_dir / "data"
        if data_plan.get("config") is not None:
            target = data_dir / "config.json"
            transaction.write_json(target, data_plan["config"])
            written.append("data/config.json")
            check_failure()
        if data_plan.get("rules") is not None:
            target = data_dir / "ai_rules.json"
            transaction.write_json(target, data_plan["rules"])
            written.append("data/ai_rules.json")
            check_failure()
        for name, payload in data_plan.get("initialize", {}).items():
            target = data_dir / name
            if target.exists():
                continue
            transaction.write_json(target, payload)
            written.append(f"data/{name}")
            check_failure()
        return {
            "ok": True,
            "mode": data_plan.get("mode"),
            "copied": copied,
            "written": written,
            "preserved": list(data_plan.get("preserved", [])),
        }
    except Exception as exc:
        try:
            transaction.rollback()
        except Exception as rollback_exc:
            raise RuntimeError(f"{exc}；{rollback_exc}") from exc
        raise
    finally:
        transaction.close()
