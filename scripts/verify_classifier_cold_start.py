#!/usr/bin/env python3
"""Run an isolated end-to-end cold-start verification for the local classifier."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_classifier
import classifier_trainer
import server


COURSE_A = "嵌入式系统"
COURSE_B = "机器视觉"
OLD_COURSE = "大学英语"


def professional_pack():
    return {
        "schema_version": 1,
        "profile": {
            "name": "冷启动验收包",
            "major": "自动化",
            "grade": "测试",
            "semester": "2099-2100-1",
            "school": "",
        },
        "subjects": {
            COURSE_A: {
                "active": True,
                "confirmed_aliases": ["嵌入式"],
                "suggested_aliases": [],
                "keywords": ["GPIO", "实时系统"],
                "assignment_types": ["实验报告"],
                "source": "cold_start_test",
            },
            COURSE_B: {
                "active": True,
                "confirmed_aliases": ["视觉识别"],
                "suggested_aliases": [],
                "keywords": ["图像分割", "目标检测"],
                "assignment_types": ["课程设计"],
                "source": "cold_start_test",
            },
        },
        "types": {},
    }


def old_rule_pack():
    return {
        "schema_version": 1,
        "profile": {"name": "旧学期", "semester": "2098-2099-2"},
        "subjects": {
            OLD_COURSE: {
                "active": True,
                "confirmed_aliases": ["英语", "嵌入式"],
                "suggested_aliases": [],
                "keywords": ["翻译", "阅读"],
                "assignment_types": [],
                "source": "cold_start_test",
            },
        },
        "types": {},
    }


def base_config():
    cfg = server.default_config()
    cfg["class_name"] = "测试班"
    cfg["assignments"] = [{
        "id": "old-english",
        "name": "旧学期英语报告",
        "subject_group": OLD_COURSE,
        "active": True,
        "keywords": ["英语"],
    }]
    cfg["ai_classifier"].update({
        "mode": "local_model",
        "priority": "rules_first",
        "sensitivity": 0.70,
        "auto_train": True,
        "active_semester": "2098-2099-2",
    })
    cfg["match_feedback"] = {
        "subject_corrections": [{
            "token": "旧学期特殊翻译",
            "to_subject": OLD_COURSE,
        }]
    }
    return cfg


def classify(filename, cfg, rules):
    active_subjects = server._active_ai_subjects(cfg, rules)
    return ai_classifier.classify_subject(
        filename,
        assignments=[
            item for item in cfg.get("assignments", [])
            if str(item.get("subject_group") or item.get("subject") or "").strip()
            in active_subjects
        ],
        rules=rules,
        students=[],
        sensitivity=server.ai_settings(cfg)["sensitivity"],
        class_name=cfg.get("class_name", ""),
        examples=server.load_ai_examples(),
        model_bundle=server.usable_ai_model_bundle(cfg, rules),
        priority=server.ai_settings(cfg)["priority"],
    )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def wait_for_model(cfg, rules, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = server.ai_model_status(cfg, rules)
        if status.get("cold_start", {}).get("stage") == "model_ready":
            return status
        if status.get("state") == "failed":
            raise AssertionError(f"后台训练失败：{status.get('error', '')}")
        time.sleep(0.05)
    raise AssertionError("自动训练未在期限内完成")


def run_verification():
    original_paths = (
        server.CONFIG_PATH,
        server.STUDENTS_PATH,
        server.AI_RULES_PATH,
        server.AI_EXAMPLES_PATH,
        server.AI_MODELS_DIR,
    )
    original_delay = server.AI_AUTO_TRAIN_DELAY_SECONDS
    original_model_cache = dict(server._ai_model_cache)
    original_summary_cache = dict(server._ai_training_summary_cache)
    original_training_state = dict(server._ai_training_state)
    original_timer = server._ai_auto_train_timer
    started = time.perf_counter()
    checkpoints = []
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server.CONFIG_PATH = root / "config.json"
            server.STUDENTS_PATH = root / "students.json"
            server.AI_RULES_PATH = root / "ai_rules.json"
            server.AI_EXAMPLES_PATH = root / "ai_examples.json"
            server.AI_MODELS_DIR = root / "models"
            server.AI_AUTO_TRAIN_DELAY_SECONDS = 0.05
            server._ai_model_cache.update({"mtime": None, "bundle": {}})
            server._ai_training_summary_cache.update({"key": None, "summary": {}})
            server._ai_training_state.update({
                "state": "idle", "phase": "", "progress": 0,
                "started_at": "", "finished_at": "", "error": "",
            })
            server.save_students([])
            cfg = base_config()
            server.save_config(cfg)
            server.save_ai_rules(old_rule_pack())
            old_example = server.record_ai_example(
                "旧学期英语阅读训练.docx",
                OLD_COURSE,
                cfg=cfg,
            )
            require(old_example is not None, "旧学期样本准备失败")

            imported = server.import_ai_rule_pack({
                "rule_pack": professional_pack(),
                "preview": False,
                "mode": "merge",
                "activate_semester": True,
                "allowed_subjects": [COURSE_A, COURSE_B],
            }, cfg)
            require(imported["ok"], "专业包导入失败")
            require(imported["semester_switched"], "未识别为新学期切换")
            require(imported["active_subjects"] == [COURSE_A, COURSE_B], "当前课程范围不正确")
            rules = imported["rule_pack"]
            cfg = server.load_config_raw()
            require(not rules["subjects"][OLD_COURSE]["active"], "旧课程仍处于启用状态")
            checkpoints.append("semester_scope")

            zero_sample = classify("嵌入式_GPIO实验报告.docx", cfg, rules)
            require(zero_sample.get("subject_group") == COURSE_A, "零样本规则冷启动失败")
            require(zero_sample.get("source") == "rules", "零样本结果未来自规则")
            old_result = classify("大学英语翻译作业.docx", cfg, rules)
            require(old_result.get("subject_group") != OLD_COURSE, "旧课程污染新学期候选")
            old_feedback_result = classify("旧学期特殊翻译.docx", cfg, rules)
            require(
                old_feedback_result.get("subject_group") != OLD_COURSE,
                "旧学期人工修正污染新课程范围",
            )
            workflow_old_result = server.classify_file_subject(
                {"name": "大学英语翻译作业.docx"},
                cfg["assignments"],
                cfg,
            )
            require(
                workflow_old_result.get("subject_group") != OLD_COURSE,
                "旧版分类回退重新激活了旧课程",
            )
            active_assignments, _assignment_index, _subjects = server._ai_assignment_indexes(cfg)
            require(not active_assignments, "历史预热仍包含旧学期作业")
            status = server.ai_model_status(cfg, rules)
            require(status["cold_start"]["stage"] == "rules_ready", "规则冷启动状态不正确")
            require(status["confirmation_count"] == 0, "旧样本被计入当前学期成熟度")
            require(status["inactive_confirmation_count"] >= 1, "旧样本保留状态不正确")
            require(len(server.load_ai_examples()) >= 1, "切换学期时错误删除了旧样本")
            checkpoints.append("rules_without_samples")

            before_memory = classify("星河控制板综合设计报告.docx", cfg, rules)
            require(before_memory.get("status") != "subject_matched", "未确认名称被提前自动采用")
            server.record_ai_example(
                "星河控制板综合设计.docx",
                COURSE_A,
                source="subject_confirmation",
                cfg=cfg,
            )
            after_memory = classify("星河控制板综合设计报告.docx", cfg, rules)
            require(after_memory.get("subject_group") == COURSE_A, "首次确认未改善相似文件")
            require(after_memory.get("similarity_score", 0) > 0, "首次确认未进入相似记忆")
            status = server.ai_model_status(cfg, rules)
            require(status["cold_start"]["stage"] == "memory_learning", "记忆增强状态不正确")
            checkpoints.append("first_confirmation_memory")

            course_a_samples = [
                "微光传感节点实验.docx",
                "苍穹通信终端报告.docx",
                "脉冲采集装置设计.docx",
                "矩阵控制板实验.docx",
            ]
            course_b_samples = [
                "纹理定位项目.docx",
                "像素检测任务.docx",
                "轮廓识别系统.docx",
                "目标追踪报告.docx",
                "视觉标定实验.docx",
            ]
            for filename in course_a_samples:
                server.record_ai_example(filename, COURSE_A, cfg=cfg)
            for filename in course_b_samples:
                server.record_ai_example(filename, COURSE_B, cfg=cfg)

            status = wait_for_model(cfg, rules)
            require(status["trainable"], "达到门槛后未标记为可训练")
            require(status["cold_start"]["model_ready"], "模型冷启动未完成")
            require(set(server.usable_ai_model_bundle(cfg, rules)["course_model"]["labels"]) == {COURSE_A, COURSE_B}, "模型标签范围不正确")
            checkpoints.append("automatic_training")

            model_result = classify("轮廓定位识别课程报告.docx", cfg, rules)
            require(model_result.get("model_score", 0) > 0, "训练后模型未参与推理")
            require(OLD_COURSE not in {
                item.get("subject_group")
                for item in model_result.get("subject_candidates", [])
            }, "模型候选包含旧学期课程")
            checkpoints.append("model_inference")

            return {
                "ok": True,
                "checkpoints": checkpoints,
                "cold_start_stage": status["cold_start"]["stage"],
                "active_subjects": imported["active_subjects"],
                "patterns": status["trainable_pattern_count"],
                "model_labels": server.usable_ai_model_bundle(cfg, rules)["course_model"]["labels"],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
    finally:
        if server._ai_auto_train_timer:
            server._ai_auto_train_timer.cancel()
        if server._ai_training_thread and server._ai_training_thread.is_alive():
            server._ai_training_thread.join(timeout=2.0)
        (
            server.CONFIG_PATH,
            server.STUDENTS_PATH,
            server.AI_RULES_PATH,
            server.AI_EXAMPLES_PATH,
            server.AI_MODELS_DIR,
        ) = original_paths
        server.AI_AUTO_TRAIN_DELAY_SECONDS = original_delay
        server._ai_auto_train_timer = original_timer
        server._ai_model_cache.clear()
        server._ai_model_cache.update(original_model_cache)
        server._ai_training_summary_cache.clear()
        server._ai_training_summary_cache.update(original_summary_cache)
        server._ai_training_state.clear()
        server._ai_training_state.update(original_training_state)


if __name__ == "__main__":
    print(json.dumps(run_verification(), ensure_ascii=False, indent=2))
