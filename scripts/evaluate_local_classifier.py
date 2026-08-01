#!/usr/bin/env python3
"""Evaluate the local filename classifier without reading submitted file bodies."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_classifier
import classifier_trainer


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_students(value, mapping_dir):
    if isinstance(value, str) and value.strip():
        path = Path(value)
        if not path.is_absolute():
            path = mapping_dir / path
        value = load_json(path)
    if isinstance(value, dict):
        value = value.get("students") or value.get("items") or []
    return value if isinstance(value, list) else []


def load_rules(mapping, mapping_dir):
    payload = mapping.get("rules")
    path_value = str(mapping.get("rules_file") or "").strip()
    if path_value:
        path = Path(path_value)
        if not path.is_absolute():
            path = mapping_dir / path
        payload = load_json(path)
    if not isinstance(payload, dict):
        payload = ai_classifier.default_rule_pack()
    return ai_classifier.normalize_rule_pack(payload)["rule_pack"]


def normalize_relative(value):
    return str(value or "").replace("\\", "/").strip("/").casefold()


def scan_dataset(root, labels, limit):
    mappings = []
    for item in labels or []:
        prefix = normalize_relative(item.get("path"))
        subject = str(item.get("subject_group") or "").strip()
        if not prefix or not subject:
            continue
        mappings.append({
            "prefix": prefix,
            "subject_group": subject,
            "assignment_id": str(item.get("assignment_id") or "").strip(),
        })
    mappings.sort(key=lambda item: len(item["prefix"]), reverse=True)
    rows = []
    unmatched = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith(("~$", ".")):
            continue
        relative = path.relative_to(root).as_posix()
        normalized_relative = relative.casefold()
        matched = next((
            item for item in mappings
            if normalized_relative == item["prefix"]
            or normalized_relative.startswith(item["prefix"] + "/")
        ), None)
        if not matched:
            unmatched += 1
            continue
        rows.append({
            "raw_name": path.name,
            "relative_path": relative,
            "subject_group": matched["subject_group"],
            "assignment_id": matched["assignment_id"],
        })
        if len(rows) >= limit:
            break
    return rows, unmatched


def protected_terms(rules):
    values = []
    for subject, item in (rules.get("subjects") or {}).items():
        values.append(subject)
        values.extend(item.get("confirmed_aliases") or [])
        values.extend(item.get("keywords") or [])
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def prepare_rows(rows, mapping, rules, students):
    prepared = []
    diagnostics = Counter()
    removed_counts = Counter()
    preprocess_versions = Counter()
    terms = protected_terms(rules)
    for row in rows:
        parsed = ai_classifier.inspect_filename(
            row["raw_name"],
            students=students,
            class_name=str(mapping.get("class_name") or ""),
            class_aliases=mapping.get("class_aliases") or [],
            protected_terms=terms,
        )
        normalized = parsed.get("normalized_text", "")
        if not normalized:
            diagnostics["empty_normalized"] += 1
        elif len(normalized.replace(" ", "")) < 2:
            diagnostics["short_normalized"] += 1
        preprocess_versions[str(parsed.get("preprocess_version", 0))] += 1
        for kind, values in (parsed.get("removed") or {}).items():
            removed_counts[kind] += len(values or [])
        prepared.append({
            **row,
            "normalized_text": normalized,
            "removed": parsed.get("removed") or {},
            "preprocess_version": parsed.get("preprocess_version", 0),
            "weight": 1.0,
            "count": 1,
        })
    return prepared, {
        **dict(diagnostics),
        "removed": dict(removed_counts),
        "preprocess_versions": dict(preprocess_versions),
    }


def grouped_holdout(rows, label_field, minimum_train):
    grouped = defaultdict(list)
    for row in rows:
        label = str(row.get(label_field) or "").strip()
        fingerprint = classifier_trainer.example_fingerprint(row)
        if label and fingerprint:
            grouped[fingerprint].append(row)
    valid = []
    conflicts = 0
    for fingerprint, items in grouped.items():
        labels = {str(item.get(label_field) or "").strip() for item in items}
        if len(labels) != 1:
            conflicts += 1
            continue
        representative = dict(items[0])
        representative["count"] = len(items)
        representative["_fingerprint"] = fingerprint
        valid.append(representative)

    by_label = defaultdict(list)
    for item in valid:
        by_label[str(item.get(label_field) or "")].append(item)
    train_rows = []
    test_rows = []
    for label in sorted(by_label):
        items = sorted(by_label[label], key=lambda item: item["_fingerprint"])
        test_count = min(max(1, len(items) // 5), max(0, len(items) - minimum_train))
        test_rows.extend(items[:test_count])
        train_rows.extend(items[test_count:])
    return train_rows, test_rows, conflicts


def private_error(row, result, include_raw_names):
    item = {
        "fingerprint": classifier_trainer.example_fingerprint(row),
        "expected": row.get("subject_group", ""),
        "predicted": result.get("subject_group", ""),
        "status": result.get("status", ""),
        "confidence": result.get("confidence", 0.0),
        "margin": result.get("candidate_margin", 0.0),
        "blocker": result.get("auto_adopt_blocker", ""),
    }
    if include_raw_names:
        item.update({
            "raw_name": row.get("raw_name", ""),
            "relative_path": row.get("relative_path", ""),
            "normalized_text": row.get("normalized_text", ""),
        })
    return item


def evaluate_course_modes(train_rows, test_rows, assignments, rules, mapping,
                          students, include_raw_names):
    subjects = {
        item.get("subject_group") for item in train_rows if item.get("subject_group")
    }
    training_started = time.perf_counter()
    bundle = classifier_trainer.build_model_bundle(
        train_rows,
        assignments,
        subjects,
    )
    training_ms = (time.perf_counter() - training_started) * 1000
    settings = mapping.get("settings") if isinstance(mapping.get("settings"), dict) else {}
    sensitivity = float(settings.get("sensitivity", 0.70))
    results = {}
    durations = []
    for priority in ("rules_first", "balanced", "model_first"):
        counters = Counter()
        errors = []
        for row in test_rows:
            started = time.perf_counter()
            result = ai_classifier.classify_subject(
                row["raw_name"],
                assignments=assignments,
                rules=rules,
                students=students,
                sensitivity=sensitivity,
                class_name=str(mapping.get("class_name") or ""),
                class_aliases=mapping.get("class_aliases") or [],
                examples=train_rows,
                model_bundle=bundle,
                priority=priority,
            )
            durations.append((time.perf_counter() - started) * 1000)
            predicted = result.get("subject_group", "")
            expected = row.get("subject_group", "")
            if result.get("status") == "subject_matched":
                counters["auto_correct" if predicted == expected else "auto_wrong"] += 1
            else:
                counters["pending"] += 1
            candidates = result.get("subject_candidates") or []
            if candidates and candidates[0].get("subject_group") == expected:
                counters["top1_correct"] += 1
            if expected in {item.get("subject_group") for item in candidates[:2]}:
                counters["top2_correct"] += 1
            if predicted != expected or result.get("status") != "subject_matched":
                if len(errors) < 50:
                    errors.append(private_error(row, result, include_raw_names))
        total = len(test_rows)
        results[priority] = {
            "patterns": total,
            **dict(counters),
            "top1_accuracy": round(counters["top1_correct"] / total, 4) if total else 0.0,
            "top2_accuracy": round(counters["top2_correct"] / total, 4) if total else 0.0,
            "errors": errors,
        }
    durations.sort()
    performance = {
        "training_ms": round(training_ms, 3),
        "average_inference_ms": round(sum(durations) / len(durations), 3) if durations else 0.0,
        "p95_inference_ms": round(durations[min(len(durations) - 1, int(len(durations) * 0.95))], 3) if durations else 0.0,
    }
    return results, performance, bundle


def evaluate_assignment_models(rows):
    reports = {}
    for subject in sorted({item.get("subject_group") for item in rows if item.get("assignment_id")}):
        subject_rows = [item for item in rows if item.get("subject_group") == subject]
        train_rows, test_rows, conflicts = grouped_holdout(
            subject_rows,
            "assignment_id",
            classifier_trainer.ASSIGNMENT_MIN_PER_LABEL,
        )
        counts = Counter(item.get("assignment_id") for item in train_rows)
        eligible = {label for label, count in counts.items() if count >= classifier_trainer.ASSIGNMENT_MIN_PER_LABEL}
        model = classifier_trainer.train_complement_nb(
            train_rows,
            "assignment_id",
            eligible,
        ) if len(eligible) >= 2 else None
        correct = 0
        covered = 0
        for row in test_rows:
            if row.get("assignment_id") not in eligible or not model:
                continue
            predictions = classifier_trainer.predict_model(
                model,
                row.get("normalized_text", ""),
                Path(row.get("raw_name", "")).suffix.lstrip("."),
            )
            if predictions:
                covered += 1
                correct += predictions[0]["label"] == row.get("assignment_id")
        reports[subject] = {
            "test_patterns": len(test_rows),
            "covered_patterns": covered,
            "correct": correct,
            "accuracy": round(correct / covered, 4) if covered else None,
            "conflict_patterns": conflicts,
            "eligible_assignments": len(eligible),
        }
    return reports


def main():
    parser = argparse.ArgumentParser(description="评测作业文件名本地分类器")
    parser.add_argument("--root", required=True, help="仅扫描文件名的外部数据目录")
    parser.add_argument("--mapping", required=True, help="目录前缀与课程/作业标签映射 JSON")
    parser.add_argument("--output", help="可选 JSON 报告输出路径")
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--include-raw-names", action="store_true", help="调试时在错误明细中包含原始名称")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    mapping_path = Path(args.mapping).resolve()
    mapping = load_json(mapping_path)
    rules = load_rules(mapping, mapping_path.parent)
    students = load_students(mapping.get("students") or mapping.get("students_file"), mapping_path.parent)
    assignments = mapping.get("assignments") if isinstance(mapping.get("assignments"), list) else []
    rows, unmatched = scan_dataset(root, mapping.get("labels") or [], max(1, min(args.limit, 50000)))
    prepared, diagnostics = prepare_rows(rows, mapping, rules, students)
    train_rows, test_rows, course_conflicts = grouped_holdout(
        prepared,
        "subject_group",
        classifier_trainer.COURSE_MIN_PER_LABEL,
    )
    modes, performance, bundle = evaluate_course_modes(
        train_rows,
        test_rows,
        assignments,
        rules,
        mapping,
        students,
        args.include_raw_names,
    )
    report = {
        "privacy": {
            "file_bodies_read": False,
            "raw_names_included": bool(args.include_raw_names),
        },
        "dataset": {
            "matched_files": len(prepared),
            "unmatched_files": unmatched,
            "train_patterns": len(train_rows),
            "test_patterns": len(test_rows),
            "course_conflict_patterns": course_conflicts,
        },
        "preprocess": diagnostics,
        "course_modes": modes,
        "assignment_models": evaluate_assignment_models(prepared),
        "model": {
            "schema_version": bundle.get("schema_version"),
            "feature_version": bundle.get("feature_version"),
            "pattern_count": bundle.get("pattern_count", 0),
            "trainable_pattern_count": bundle.get("trainable_pattern_count", 0),
            "validation": (bundle.get("meta") or {}).get("course_validation", {}),
        },
        "performance": performance,
    }

    print(json.dumps({key: value for key, value in report.items() if key != "course_modes"}, ensure_ascii=False, indent=2))
    print("\n模式结果：")
    for name, result in modes.items():
        print(
            f"- {name}: Top-1 {result['top1_accuracy']:.1%}, "
            f"自动正确 {result.get('auto_correct', 0)}, "
            f"自动错误 {result.get('auto_wrong', 0)}, "
            f"待确认 {result.get('pending', 0)}"
        )
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n报告已写入：{output}")


if __name__ == "__main__":
    main()
