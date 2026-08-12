"""Pure-standard-library sample storage and local text model training."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from classifier_features import PREPROCESS_VERSION, extract_features, feature_set, text_similarity


MODEL_SCHEMA_VERSION = 2
EXAMPLES_SCHEMA_VERSION = 2
FEATURE_VERSION = 3
COURSE_MIN_PER_LABEL = 5
ASSIGNMENT_MIN_PER_LABEL = 3
AUTO_TRAIN_DELTA = 5
DEFAULT_TEMPERATURE = 0.18
TEMPERATURE_CANDIDATES = (0.12, 0.18, 0.25, 0.35, 0.50, 0.75, 1.0)
_storage_lock = threading.RLock()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _atomic_gzip_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        with gzip.open(temp_name, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def load_examples(path):
    path = Path(path)
    with _storage_lock:
        if not path.exists():
            return {"schema_version": EXAMPLES_SCHEMA_VERSION, "data_version": 0, "items": [], "migrations": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": EXAMPLES_SCHEMA_VERSION, "data_version": 0, "items": [], "migrations": {}}
    if isinstance(payload, list):
        payload = {"schema_version": EXAMPLES_SCHEMA_VERSION, "data_version": 0, "items": payload, "migrations": {}}
    if not isinstance(payload, dict):
        payload = {}
    items = payload.get("items")
    try:
        data_version = max(0, int(payload.get("data_version", 0)))
    except (TypeError, ValueError):
        data_version = 0
    return {
        "schema_version": EXAMPLES_SCHEMA_VERSION,
        "data_version": data_version,
        "items": items if isinstance(items, list) else [],
        "migrations": payload.get("migrations") if isinstance(payload.get("migrations"), dict) else {},
    }


def save_examples(path, payload, bump_version=False):
    try:
        data_version = max(0, int(payload.get("data_version", 0)))
    except (TypeError, ValueError):
        data_version = 0
    clean = {
        "schema_version": EXAMPLES_SCHEMA_VERSION,
        "data_version": data_version + (1 if bump_version else 0),
        "items": list(payload.get("items") or [])[-20000:],
        "migrations": dict(payload.get("migrations") or {}),
    }
    with _storage_lock:
        _atomic_json(path, clean)
    return clean


def _sample_key(item):
    return (
        str(item.get("raw_name") or "").casefold(),
        str(item.get("subject_group") or "").casefold(),
        str(item.get("assignment_id") or "").casefold(),
    )


def example_fingerprint(item):
    """Return a privacy-safe identity for one normalized filename pattern."""
    normalized = re.sub(
        r"\s+",
        " ",
        str((item or {}).get("normalized_text") or "").strip().casefold(),
    )
    extension = Path(str((item or {}).get("raw_name") or "")).suffix.lower().lstrip(".")
    if not normalized:
        return ""
    return hashlib.sha1(f"{normalized}\0{extension}".encode("utf-8")).hexdigest()


def example_confirmation_count(item):
    try:
        return max(1, int((item or {}).get("count", 1)))
    except (TypeError, ValueError):
        return 1


def example_weight(item):
    try:
        return max(0.1, min(2.0, float((item or {}).get("weight", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def aggregate_training_examples(examples, label_field, subject_group="", eligible_labels=None,
                                feature_cache=None):
    """Collapse repeated confirmations and exclude contradictory patterns."""
    eligible = None if eligible_labels is None else set(eligible_labels)
    by_fingerprint = defaultdict(list)
    confirmation_count = 0
    for source in examples or []:
        if subject_group and source.get("subject_group") != subject_group:
            continue
        label = str(source.get(label_field) or "").strip()
        if not label or (eligible is not None and label not in eligible):
            continue
        fingerprint = example_fingerprint(source)
        if not fingerprint:
            continue
        item = dict(source)
        item["_fingerprint"] = fingerprint
        item["_label"] = label
        item["count"] = example_confirmation_count(item)
        confirmation_count += item["count"]
        by_fingerprint[fingerprint].append(item)

    rows = []
    conflicts = []
    label_pattern_counts = Counter()
    label_confirmation_counts = Counter()
    for fingerprint, items in sorted(by_fingerprint.items()):
        labels = sorted({item["_label"] for item in items})
        total_confirmations = sum(item["count"] for item in items)
        if len(labels) != 1:
            conflicts.append({
                "fingerprint": fingerprint,
                "labels": labels,
                "confirmation_count": total_confirmations,
            })
            continue
        label = labels[0]
        representative = max(
            items,
            key=lambda item: (
                str(item.get("confirmed_at") or ""),
                str(item.get("id") or ""),
            ),
        )
        max_weight = max(example_weight(item) for item in items)
        effective_weight = min(
            2.0,
            max_weight * (1.0 + 0.25 * math.log2(max(1, total_confirmations))),
        )
        row = dict(representative)
        row["count"] = total_confirmations
        row["weight"] = round(effective_weight, 6)
        row["_fingerprint"] = fingerprint
        if feature_cache is not None and fingerprint in feature_cache:
            row["_features"] = feature_cache[fingerprint]
        else:
            row["_features"] = extract_features(
                row.get("normalized_text", ""),
                Path(str(row.get("raw_name") or "")).suffix.lstrip("."),
            )
            if feature_cache is not None:
                feature_cache[fingerprint] = row["_features"]
        row.pop("_label", None)
        rows.append(row)
        label_pattern_counts[label] += 1
        label_confirmation_counts[label] += total_confirmations

    return {
        "rows": rows,
        "pattern_count": len(by_fingerprint),
        "trainable_pattern_count": len(rows),
        "conflict_pattern_count": len(conflicts),
        "confirmation_count": confirmation_count,
        "label_pattern_counts": dict(label_pattern_counts),
        "label_confirmation_counts": dict(label_confirmation_counts),
        "conflicts": conflicts,
    }


def _normalize_example(example):
    item = dict(example or {})
    raw_name = Path(str(item.get("raw_name") or "")).name[:260]
    normalized = str(item.get("normalized_text") or "").strip()[:500]
    subject = str(item.get("subject_group") or "").strip()[:100]
    if not raw_name or not normalized or not subject:
        raise ValueError("训练样本缺少文件名、有效文本或课程")
    item.update({
        "id": str(item.get("id") or uuid.uuid4().hex),
        "raw_name": raw_name,
        "normalized_text": normalized,
        "subject_group": subject,
        "assignment_id": str(item.get("assignment_id") or "")[:100],
        "assignment_type": str(item.get("assignment_type") or "")[:100],
        "experiment": str(item.get("experiment") or "")[:100],
        "source": str(item.get("source") or "manual_confirmation")[:60],
        "weight": max(0.1, min(2.0, float(item.get("weight", 1.0)))),
        "confirmed_at": str(item.get("confirmed_at") or _now()),
        "preprocess_version": int(item.get("preprocess_version") or PREPROCESS_VERSION),
        "count": max(1, int(item.get("count", 1))),
        "normalized_source": (
            "manual"
            if str(item.get("normalized_source") or "").strip() == "manual"
            else "parser"
        ),
    })
    item["removed"] = item.get("removed") if isinstance(item.get("removed"), dict) else {}
    return item


def _upsert_payload_item(payload, example):
    item = _normalize_example(example)
    raw_name = item["raw_name"]
    subject = item["subject_group"]
    key = _sample_key(item)
    existing_index = next((index for index, current in enumerate(payload["items"]) if _sample_key(current) == key), None)
    if existing_index is None:
        existing_index = next((
            index for index, current in enumerate(payload["items"])
            if str(current.get("raw_name") or "").casefold() == raw_name.casefold()
            and str(current.get("subject_group") or "").casefold() == subject.casefold()
            and (
                not str(current.get("assignment_id") or "")
                or not item["assignment_id"]
            )
        ), None)
    if existing_index is None:
        # A later correction for the same file supersedes conflicting labels.
        before = len(payload["items"])
        payload["items"] = [
            current for current in payload["items"]
            if str(current.get("raw_name") or "").casefold() != raw_name.casefold()
            or (
                str(current.get("subject_group") or "").casefold() == subject.casefold()
                and str(current.get("assignment_id") or "").casefold() == item["assignment_id"].casefold()
            )
        ]
        payload["items"].append(item)
        action = "replaced" if len(payload["items"]) <= before else "added"
    else:
        current = dict(payload["items"][existing_index])
        item["id"] = current.get("id") or item["id"]
        item["count"] = int(current.get("count", 1)) + 1
        if not item["assignment_id"] and current.get("assignment_id"):
            item["assignment_id"] = current.get("assignment_id", "")
            item["assignment_type"] = current.get("assignment_type", "")
            item["experiment"] = current.get("experiment", "")
        payload["items"][existing_index] = item
        action = "merged"
    return item, action


def upsert_example(path, example):
    payload = load_examples(path)
    item, _action = _upsert_payload_item(payload, example)
    save_examples(path, payload, bump_version=True)
    return item


def upsert_examples_batch(path, examples):
    payload = load_examples(path)
    results = []
    actions = Counter()
    for example in examples or []:
        item, action = _upsert_payload_item(payload, example)
        results.append(item)
        actions[action] += 1
    if results:
        payload = save_examples(path, payload, bump_version=True)
    return {
        "items": results,
        "actions": dict(actions),
        "data_version": payload.get("data_version", 0),
    }


def delete_examples(path, ids):
    payload = load_examples(path)
    targets = {str(item) for item in ids or [] if str(item)}
    before = len(payload["items"])
    payload["items"] = [item for item in payload["items"] if str(item.get("id")) not in targets]
    deleted = before - len(payload["items"])
    if deleted:
        save_examples(path, payload, bump_version=True)
    return deleted


def update_example(path, example_id, updates):
    payload = load_examples(path)
    index = next(
        (index for index, item in enumerate(payload["items"]) if str(item.get("id")) == str(example_id)),
        None,
    )
    if index is None:
        raise KeyError("训练样本不存在")
    current = dict(payload["items"][index])
    merged = _normalize_example({
        **current,
        **dict(updates or {}),
        "id": current.get("id"),
        "count": current.get("count", 1),
        "confirmed_at": _now(),
    })
    next_items = []
    for position, item in enumerate(payload["items"]):
        if position == index:
            next_items.append(merged)
        elif str(item.get("raw_name") or "").casefold() != merged["raw_name"].casefold():
            next_items.append(item)
    payload["items"] = next_items
    save_examples(path, payload, bump_version=True)
    return merged


def replace_examples(path, items, migrations=None, bump_version=True):
    current = load_examples(path)
    return save_examples(path, {
        "data_version": current.get("data_version", 0),
        "items": list(items or []),
        "migrations": migrations or current.get("migrations", {}),
    }, bump_version=bump_version)


def migrate_subject_corrections(path, corrections, normalize_callback):
    payload = load_examples(path)
    if payload["migrations"].get("match_feedback_subject_corrections_v1"):
        return 0
    imported = 0
    for correction in corrections or []:
        raw_name = str(correction.get("token") or "").strip()
        subject = str(correction.get("to_subject") or "").strip()
        if not raw_name or not subject:
            continue
        parsed = normalize_callback(raw_name)
        if not parsed.get("normalized_text"):
            continue
        upsert_example(path, {
            **parsed,
            "subject_group": subject,
            "source": "migrated_subject_correction",
            "weight": 1.2,
            "confirmed_at": correction.get("updated_at") or _now(),
            "count": correction.get("count", 1),
        })
        imported += 1
    payload = load_examples(path)
    payload["migrations"]["match_feedback_subject_corrections_v1"] = {
        "completed_at": _now(),
        "imported": imported,
    }
    save_examples(path, payload)
    return imported


def similarity_predictions(text, examples, label_field="subject_group", subject_group="", limit=5):
    if not feature_set(text):
        return []
    best_by_label = {}
    for item in examples or []:
        if subject_group and item.get("subject_group") != subject_group:
            continue
        label = str(item.get(label_field) or "").strip()
        sample_text = str(item.get("normalized_text") or "").strip()
        if not label or not sample_text:
            continue
        score = text_similarity(text, sample_text)
        current = best_by_label.get(label)
        if current is None or score > current["confidence"]:
            best_by_label[label] = {
                "label": label,
                "confidence": round(score, 4),
                "example_id": item.get("id", ""),
                "raw_name": item.get("raw_name", ""),
            }
    return sorted(best_by_label.values(), key=lambda item: (-item["confidence"], item["label"]))[:limit]


def _softmax(values, temperature=DEFAULT_TEMPERATURE):
    if not values:
        return {}
    temperature = max(0.05, min(2.0, float(temperature or DEFAULT_TEMPERATURE)))
    peak = max(values.values())
    exps = {
        key: math.exp(max(-60.0, min(60.0, (value - peak) / temperature)))
        for key, value in values.items()
    }
    total = sum(exps.values()) or 1.0
    return {key: value / total for key, value in exps.items()}


def _train_complement_nb_rows(rows, label_field, eligible_labels=None, cancel_event=None):
    eligible = None if eligible_labels is None else set(eligible_labels)
    label_docs = Counter()
    label_feature_counts = defaultdict(Counter)
    global_counts = Counter()
    for item in rows or []:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("训练已取消")
        label = str(item.get(label_field) or "").strip()
        if not label or (eligible is not None and label not in eligible):
            continue
        features = item.get("_features") or extract_features(
            item.get("normalized_text", ""),
            Path(str(item.get("raw_name") or "")).suffix.lstrip("."),
        )
        if not features:
            continue
        weight = example_weight(item)
        label_docs[label] += weight
        for token, count in features.items():
            value = count * weight
            label_feature_counts[label][token] += value
            global_counts[token] += value
    labels = sorted(label_docs)
    if len(labels) < 2:
        return None

    vocabulary = {
        token for token, _count in global_counts.most_common(12000)
    }
    alpha = 1.0
    weights = {}
    defaults = {}
    total_docs = sum(label_docs.values()) or 1.0
    for label in labels:
        complement_total = sum(global_counts[token] - label_feature_counts[label].get(token, 0.0) for token in vocabulary)
        denominator = complement_total + alpha * max(1, len(vocabulary))
        defaults[label] = -math.log(alpha / denominator)
        class_weights = {}
        for token in vocabulary:
            complement = global_counts[token] - label_feature_counts[label].get(token, 0.0)
            class_weights[token] = -math.log((complement + alpha) / denominator)
        weights[label] = {
            token: round(value, 10)
            for token, value in class_weights.items()
        }
        defaults[label] = round(defaults[label], 10)

    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "kind": "complement_naive_bayes",
        "labels": labels,
        "weights": weights,
        "defaults": defaults,
        "priors": {label: label_docs[label] / total_docs for label in labels},
        "document_counts": {label: round(label_docs[label], 3) for label in labels},
        "temperature": DEFAULT_TEMPERATURE,
        "trained_at": _now(),
    }


def train_complement_nb(examples, label_field, eligible_labels=None, cancel_event=None):
    aggregated = aggregate_training_examples(
        examples,
        label_field,
        eligible_labels=eligible_labels,
    )
    return _train_complement_nb_rows(
        aggregated["rows"],
        label_field,
        eligible_labels,
        cancel_event,
    )


def _raw_model_scores_from_features(model, features):
    if not isinstance(model, dict) or not model.get("labels"):
        return {}
    if not features:
        return {}
    total_features = sum(features.values()) or 1
    raw_scores = {}
    for label in model.get("labels", []):
        label_weights = model.get("weights", {}).get(label, {})
        default = float(model.get("defaults", {}).get(label, 0.0))
        score = 0.0
        for token, count in features.items():
            score += count * float(label_weights.get(token, default))
        score /= total_features
        score += 0.02 * math.log(max(1e-9, float(model.get("priors", {}).get(label, 1e-9))))
        raw_scores[label] = score
    return raw_scores


def _raw_model_scores(model, text, extension=""):
    return _raw_model_scores_from_features(
        model,
        extract_features(text, extension),
    )


def predict_model(model, text, extension=""):
    raw_scores = _raw_model_scores(model, text, extension)
    if not raw_scores:
        return []
    probabilities = _softmax(
        raw_scores,
        model.get("temperature", DEFAULT_TEMPERATURE),
    )
    return [
        {"label": label, "confidence": round(probabilities[label], 4)}
        for label in sorted(probabilities, key=lambda key: (-probabilities[key], key))
    ]


def _validation_result(examples, label_field, eligible_labels, cancel_event=None):
    grouped = defaultdict(list)
    for item in examples:
        label = str(item.get(label_field) or "").strip()
        if label in eligible_labels:
            grouped[label].append(item)
    validation_labels = {
        label for label, items in grouped.items() if len(items) >= 8
    }
    if len(validation_labels) < 2:
        return {
            "status": "insufficient",
            "samples": 0,
            "eligible_labels": len(grouped),
            "validated_labels": len(validation_labels),
        }
    grouped = {
        label: items for label, items in grouped.items()
        if label in validation_labels
    }

    train_rows = []
    test_rows = []
    for label, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: item.get("_fingerprint") or example_fingerprint(item),
        )
        for index, item in enumerate(ordered):
            (test_rows if index % 5 == 0 else train_rows).append(item)
    model = _train_complement_nb_rows(
        train_rows,
        label_field,
        eligible_labels,
        cancel_event,
    )
    if not model or not test_rows:
        return {"status": "insufficient", "samples": 0}

    scored_rows = []
    for item in test_rows:
        raw_scores = _raw_model_scores_from_features(
            model,
            item.get("_features") or extract_features(
                item.get("normalized_text", ""),
                Path(str(item.get("raw_name") or "")).suffix.lstrip("."),
            ),
        )
        if raw_scores:
            scored_rows.append((str(item.get(label_field) or ""), raw_scores))
    if not scored_rows:
        return {"status": "insufficient", "samples": 0}

    def negative_log_likelihood(temperature):
        total = 0.0
        for expected, raw_scores in scored_rows:
            probabilities = _softmax(raw_scores, temperature)
            total -= math.log(max(1e-12, probabilities.get(expected, 0.0)))
        return total / len(scored_rows)

    temperature = min(
        TEMPERATURE_CANDIDATES,
        key=lambda value: (negative_log_likelihood(value), value),
    )
    model["temperature"] = temperature
    correct = 0
    for item in test_rows:
        raw_scores = _raw_model_scores_from_features(
            model,
            item.get("_features") or extract_features(
                item.get("normalized_text", ""),
                Path(str(item.get("raw_name") or "")).suffix.lstrip("."),
            ),
        )
        prediction = _softmax(raw_scores, model.get("temperature", DEFAULT_TEMPERATURE))
        predicted_label = max(prediction, key=prediction.get) if prediction else ""
        if predicted_label == item.get(label_field):
            correct += 1
    return {
        "status": "ready",
        "samples": len(test_rows),
        "patterns": len(test_rows),
        "accuracy": round(correct / len(test_rows), 4),
        "temperature": temperature,
        "split_strategy": "fingerprint_stratified_hash",
        "eligible_labels": len(eligible_labels),
        "validated_labels": len(validation_labels),
    }


def summarize_training_data(examples, assignments, active_subjects):
    examples = list(examples or [])
    if active_subjects is None:
        active_subjects = {
            str(item.get("subject_group") or "").strip()
            for item in examples
            if str(item.get("subject_group") or "").strip()
        }
    else:
        active_subjects = set(active_subjects)
    active_examples = [
        item for item in examples
        if str(item.get("subject_group") or "").strip() in active_subjects
    ]
    feature_cache = {}
    course = aggregate_training_examples(
        examples,
        "subject_group",
        eligible_labels=active_subjects,
        feature_cache=feature_cache,
    )
    active_assignments = {
        str(item.get("id")): item for item in assignments or []
        if item.get("id") and item.get("active", True)
    }
    assignment = {}
    subjects = sorted({
        item.get("subject_group")
        for item in examples
        if item.get("subject_group") in active_subjects
    })
    for subject in subjects:
        subject_assignment_ids = {
            assignment_id
            for assignment_id, item in active_assignments.items()
            if item.get("subject_group") == subject
        }
        assignment[subject] = aggregate_training_examples(
            examples,
            "assignment_id",
            subject_group=subject,
            eligible_labels=subject_assignment_ids,
            feature_cache=feature_cache,
        )

    signature_rows = []
    for row in course["rows"]:
        signature_rows.append((
            "course",
            row.get("_fingerprint", ""),
            str(row.get("subject_group") or ""),
            round(float(row.get("weight", 1.0)), 6),
        ))
    for subject, details in assignment.items():
        for row in details["rows"]:
            signature_rows.append((
                "assignment",
                subject,
                row.get("_fingerprint", ""),
                str(row.get("assignment_id") or ""),
                round(float(row.get("weight", 1.0)), 6),
            ))
    signature_payload = {
        "schema": MODEL_SCHEMA_VERSION,
        "feature": FEATURE_VERSION,
        "rows": sorted(signature_rows),
        "course_conflicts": sorted(
            (item["fingerprint"], tuple(item["labels"]))
            for item in course["conflicts"]
        ),
        "assignment_conflicts": sorted(
            (subject, item["fingerprint"], tuple(item["labels"]))
            for subject, details in assignment.items()
            for item in details["conflicts"]
        ),
    }
    training_signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "sample_record_count": len(active_examples),
        "confirmation_count": sum(example_confirmation_count(item) for item in active_examples),
        "all_sample_record_count": len(examples),
        "all_confirmation_count": sum(example_confirmation_count(item) for item in examples),
        "course": course,
        "assignment": assignment,
        "training_signature": training_signature,
    }


def build_model_bundle(examples, assignments, active_subjects, cancel_event=None, progress=None,
                       data_version=0):
    examples = list(examples or [])
    summary = summarize_training_data(examples, assignments, active_subjects)
    course_data = summary["course"]
    course_counts = Counter(course_data["label_pattern_counts"])
    if progress:
        progress("course_model", 15)
    course_labels = sorted(
        label for label, count in course_counts.items()
        if count >= COURSE_MIN_PER_LABEL
    )
    course_model = _train_complement_nb_rows(
        course_data["rows"], "subject_group", course_labels, cancel_event
    ) if len(course_labels) >= 2 else None
    course_validation = _validation_result(
        course_data["rows"], "subject_group", set(course_labels), cancel_event
    ) if course_model else {"status": "insufficient", "samples": 0}
    if course_model and course_validation.get("status") == "ready":
        course_model["temperature"] = course_validation["temperature"]

    if progress:
        progress("assignment_models", 45)
    assignment_models = {}
    assignment_meta = {}
    subjects = sorted(summary["assignment"])
    for index, subject in enumerate(subjects):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("训练已取消")
        subject_data = summary["assignment"][subject]
        subject_rows = subject_data["rows"]
        counts = Counter(subject_data["label_pattern_counts"])
        labels = sorted(label for label, count in counts.items() if count >= ASSIGNMENT_MIN_PER_LABEL)
        model = _train_complement_nb_rows(
            subject_rows, "assignment_id", labels, cancel_event
        ) if len(labels) >= 2 else None
        validation = _validation_result(
            subject_rows, "assignment_id", set(labels), cancel_event
        ) if model else {"status": "insufficient", "samples": 0}
        if model and validation.get("status") == "ready":
            model["temperature"] = validation["temperature"]
        if model:
            assignment_models[subject] = model
        assignment_meta[subject] = {
            "labels": labels,
            "sample_counts": dict(counts),
            "pattern_counts": dict(counts),
            "confirmation_counts": subject_data["label_confirmation_counts"],
            "pattern_count": subject_data["pattern_count"],
            "trainable_pattern_count": subject_data["trainable_pattern_count"],
            "conflict_pattern_count": subject_data["conflict_pattern_count"],
            "validation": validation,
        }
        if progress and subjects:
            progress("assignment_models", 45 + int(40 * (index + 1) / len(subjects)))

    if progress:
        progress("finalizing", 90)
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "trained_at": _now(),
        "sample_count": summary["confirmation_count"],
        "sample_record_count": summary["sample_record_count"],
        "pattern_count": course_data["pattern_count"],
        "trainable_pattern_count": course_data["trainable_pattern_count"],
        "conflict_pattern_count": course_data["conflict_pattern_count"],
        "training_signature": summary["training_signature"],
        "data_version": max(0, int(data_version or 0)),
        "course_model": course_model,
        "assignment_models": assignment_models,
        "meta": {
            "course_labels": course_labels,
            "course_sample_counts": dict(course_counts),
            "course_pattern_counts": dict(course_counts),
            "course_confirmation_counts": course_data["label_confirmation_counts"],
            "course_validation": course_validation,
            "assignment": assignment_meta,
        },
    }


def _valid_trained_model(model):
    if model is None:
        return True
    if not isinstance(model, dict):
        return False
    labels = model.get("labels")
    if (
        model.get("schema_version") != MODEL_SCHEMA_VERSION
        or model.get("feature_version") != FEATURE_VERSION
        or model.get("kind") != "complement_naive_bayes"
        or not isinstance(labels, list)
        or len(labels) < 2
    ):
        return False
    weights = model.get("weights")
    defaults = model.get("defaults")
    priors = model.get("priors")
    if not all(isinstance(item, dict) for item in (weights, defaults, priors)):
        return False
    try:
        temperature = float(model.get("temperature", 0.0))
    except (TypeError, ValueError):
        return False
    if not 0.05 <= temperature <= 2.0:
        return False
    return all(
        isinstance(label, str)
        and label
        and isinstance(weights.get(label), dict)
        and label in defaults
        and label in priors
        for label in labels
    )


def _valid_model_bundle(bundle):
    if not isinstance(bundle, dict):
        return False
    if (
        bundle.get("schema_version") != MODEL_SCHEMA_VERSION
        or bundle.get("feature_version") != FEATURE_VERSION
        or not isinstance(bundle.get("meta"), dict)
        or not isinstance(bundle.get("assignment_models"), dict)
    ):
        return False
    try:
        if int(bundle.get("sample_count", -1)) < 0:
            return False
        if int(bundle.get("data_version", 0)) < 0:
            return False
    except (TypeError, ValueError):
        return False
    if not isinstance(bundle.get("training_signature"), str) or not bundle["training_signature"]:
        return False
    if not _valid_trained_model(bundle.get("course_model")):
        return False
    return all(
        isinstance(subject, str)
        and subject
        and _valid_trained_model(model)
        for subject, model in bundle["assignment_models"].items()
    )


def _read_model_bundle(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            bundle = json.load(handle)
        return bundle if _valid_model_bundle(bundle) else {}
    except Exception:
        return {}


def save_model_bundle(model_dir, bundle):
    if not _valid_model_bundle(bundle):
        raise ValueError("模型完整性检查失败")
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = model_dir / "model_bundle.json.gz"
    backup_path = model_dir / "model_bundle.json.gz.bak"
    if bundle_path.exists() and _read_model_bundle(bundle_path):
        shutil.copy2(bundle_path, backup_path)
    _atomic_gzip_json(bundle_path, bundle)
    if not _read_model_bundle(bundle_path):
        if backup_path.exists() and _read_model_bundle(backup_path):
            shutil.copy2(backup_path, bundle_path)
        raise OSError("模型写入后的完整性检查失败")
    _atomic_json(model_dir / "model_meta.json", {
        "schema_version": bundle.get("schema_version"),
        "feature_version": bundle.get("feature_version"),
        "trained_at": bundle.get("trained_at"),
        "sample_count": bundle.get("sample_count", 0),
        "sample_record_count": bundle.get("sample_record_count", 0),
        "pattern_count": bundle.get("pattern_count", 0),
        "trainable_pattern_count": bundle.get("trainable_pattern_count", 0),
        "conflict_pattern_count": bundle.get("conflict_pattern_count", 0),
        "training_signature": bundle.get("training_signature", ""),
        "data_version": bundle.get("data_version", 0),
        **(bundle.get("meta") or {}),
    })
    return bundle_path


def load_model_bundle(model_dir):
    path = Path(model_dir) / "model_bundle.json.gz"
    if not path.exists():
        return {}
    bundle = _read_model_bundle(path)
    if bundle:
        return bundle
    backup = Path(str(path) + ".bak")
    return _read_model_bundle(backup) if backup.exists() else {}


def reset_models(model_dir):
    model_dir = Path(model_dir)
    removed = 0
    if not model_dir.exists():
        return removed
    for path in model_dir.iterdir():
        if path.is_file() and path.name.startswith(("model_bundle", "model_meta")):
            path.unlink(missing_ok=True)
            removed += 1
    return removed
