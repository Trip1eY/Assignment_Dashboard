#!/usr/bin/env python3
"""Optional external-model adapter for assignment filename classification."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


PROVIDERS = {"ollama", "openai_compatible"}
DEFAULT_SETTINGS = {
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
MAX_RESPONSE_BYTES = 256 * 1024


class ExternalAIError(RuntimeError):
    def __init__(self, message, category="request_failed"):
        super().__init__(message)
        self.category = category


def _clean_text(value, limit=200):
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def normalize_settings(value=None):
    result = dict(DEFAULT_SETTINGS)
    supplied = value if isinstance(value, dict) else {}
    result.update(supplied)
    if result.get("provider") not in PROVIDERS:
        result["provider"] = "ollama"
    result["enabled"] = bool(result.get("enabled", False))
    result["strategy"] = (
        result.get("strategy") if result.get("strategy") in {"manual", "uncertain"}
        else "uncertain"
    )
    result["suggestion_only"] = bool(result.get("suggestion_only", True))
    defaults = DEFAULT_SETTINGS
    endpoint = _clean_text(supplied.get("endpoint"), 500)
    if not endpoint:
        endpoint = (
            defaults["endpoint"] if result["provider"] == "ollama"
            else "https://api.openai.com/v1/chat/completions"
        )
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ValueError("外部模型地址必须是有效的 HTTP(S) 地址，且不能包含账号信息")
    result["endpoint"] = endpoint
    result["model"] = _clean_text(result.get("model"), 120)
    if not result["model"]:
        raise ValueError("模型名称不能为空")
    for key, low, high in (
        ("timeout_seconds", 2, 60),
        ("minute_limit", 1, 60),
        ("daily_limit", 1, 5000),
    ):
        try:
            result[key] = max(low, min(high, int(result.get(key, defaults[key]))))
        except (TypeError, ValueError):
            result[key] = defaults[key]
    try:
        result["min_confidence"] = max(
            0.50, min(0.99, float(result.get("min_confidence", 0.75)))
        )
    except (TypeError, ValueError):
        result["min_confidence"] = 0.75
    return {key: result[key] for key in DEFAULT_SETTINGS}


def mask_key(api_key):
    value = str(api_key or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}{'*' * min(24, len(value) - 6)}{value[-3:]}"


def _json_fragment(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _end = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise ExternalAIError("模型未返回有效 JSON", "invalid_json")


def build_prompt(context):
    normalized = _clean_text(context.get("normalized_text"), 500)
    extension = _clean_text(context.get("extension"), 20)
    courses = context.get("courses") if isinstance(context.get("courses"), list) else []
    assignments = context.get("assignments") if isinstance(context.get("assignments"), list) else []
    safe_courses = [_clean_text(item, 80) for item in courses[:100] if _clean_text(item, 80)]
    safe_assignments = [
        {
            "id": _clean_text(item.get("id"), 100),
            "course": _clean_text(item.get("subject_group"), 80),
            "name": _clean_text(item.get("name") or item.get("experiment"), 120),
        }
        for item in assignments[:300] if isinstance(item, dict) and item.get("id")
    ]
    payload = {
        "normalized_filename": normalized,
        "extension": extension,
        "allowed_courses": safe_courses,
        "allowed_assignments": safe_assignments,
    }
    return (
        "你是大学作业文件名分类器。只根据给定的脱敏文件名，从允许范围中选择课程和作业。"
        "禁止创造新课程或新作业；不确定时字段留空。只输出 JSON，不要解释。\n"
        "输出格式：{\"subject_group\":\"\",\"assignment_id\":\"\","
        "\"type\":\"\",\"experiment\":\"\",\"confidence\":0.0,"
        "\"reason\":\"\",\"subject_candidates\":[{\"label\":\"\",\"confidence\":0.0}],"
        "\"assignment_candidates\":[{\"label\":\"\",\"confidence\":0.0}]}\n输入："
        + json.dumps(payload, ensure_ascii=False)
    )


def _request_json(url, body, headers, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        category = "authentication" if exc.code in {401, 403} else "rate_limited" if exc.code == 429 else "http_error"
        exc.close()
        raise ExternalAIError(f"外部模型返回 HTTP {exc.code}", category) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        category = "timeout" if isinstance(reason, TimeoutError) else "connection"
        raise ExternalAIError(f"无法连接外部模型：{reason}", category) from exc
    except TimeoutError as exc:
        raise ExternalAIError("外部模型请求超时", "timeout") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ExternalAIError("外部模型响应过大", "response_too_large")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalAIError("外部服务响应不是有效 JSON", "invalid_response") from exc


def validate_result(value, context):
    if not isinstance(value, dict):
        raise ExternalAIError("模型 JSON 必须是对象", "invalid_schema")
    courses = {_clean_text(item, 80) for item in context.get("courses", [])}
    assignments = {
        _clean_text(item.get("id"), 100): item
        for item in context.get("assignments", []) if isinstance(item, dict) and item.get("id")
    }
    subject = _clean_text(value.get("subject_group"), 80)
    assignment_id = _clean_text(value.get("assignment_id"), 100)
    if subject and subject not in courses:
        raise ExternalAIError("模型返回了当前课程树之外的课程", "unknown_subject")
    if assignment_id:
        assignment = assignments.get(assignment_id)
        if not assignment:
            raise ExternalAIError("模型返回了当前作业树之外的作业", "unknown_assignment")
        assignment_subject = _clean_text(assignment.get("subject_group"), 80)
        if subject and assignment_subject != subject:
            raise ExternalAIError("模型返回的课程与作业不一致", "tree_conflict")
        subject = subject or assignment_subject
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    def candidates(raw_items, allowed):
        result = []
        seen = set()
        for raw in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(raw, dict):
                continue
            label = _clean_text(raw.get("label"), 100)
            if not label or label not in allowed or label in seen:
                continue
            try:
                score = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
            except (TypeError, ValueError):
                score = 0.0
            result.append({"label": label, "confidence": round(score, 4)})
            seen.add(label)
        return sorted(result, key=lambda item: (-item["confidence"], item["label"]))[:5]

    subject_candidates = candidates(value.get("subject_candidates"), courses)
    assignment_candidates = candidates(value.get("assignment_candidates"), set(assignments))
    if subject and subject not in {item["label"] for item in subject_candidates}:
        subject_candidates.append({"label": subject, "confidence": round(confidence, 4)})
        subject_candidates.sort(key=lambda item: (-item["confidence"], item["label"]))
    if assignment_id and assignment_id not in {item["label"] for item in assignment_candidates}:
        assignment_candidates.append({"label": assignment_id, "confidence": round(confidence, 4)})
        assignment_candidates.sort(key=lambda item: (-item["confidence"], item["label"]))
    return {
        "subject_group": subject,
        "assignment_id": assignment_id,
        "type": _clean_text(value.get("type"), 80),
        "experiment": _clean_text(value.get("experiment"), 100),
        "confidence": round(confidence, 4),
        "reason": _clean_text(value.get("reason"), 160),
        "subject_candidates": subject_candidates,
        "assignment_candidates": assignment_candidates,
    }


def classify(context, settings, api_key="", opener=None):
    settings = normalize_settings(settings)
    prompt = build_prompt(context)
    headers = {}
    if settings["provider"] == "ollama":
        body = {
            "model": settings["model"],
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
    else:
        if not str(api_key or "").strip():
            raise ExternalAIError("尚未配置 API Key", "missing_key")
        headers["Authorization"] = f"Bearer {str(api_key).strip()}"
        body = {
            "model": settings["model"],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "只输出符合要求的 JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
    request_json = opener or _request_json
    response = request_json(
        settings["endpoint"], body, headers, settings["timeout_seconds"]
    )
    if settings["provider"] == "ollama":
        content = response.get("response", "") if isinstance(response, dict) else ""
    else:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalAIError("云端响应缺少模型输出", "invalid_response") from exc
    return validate_result(_json_fragment(content), context)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def usage_counts(items, now=None):
    now = float(now if now is not None else time.time())
    minute = 0
    day = 0
    for item in items or []:
        if item.get("counted", True) is False:
            continue
        try:
            stamp = datetime.fromisoformat(str(item.get("time") or "").replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        if now - stamp <= 60:
            minute += 1
        if now - stamp <= 86400:
            day += 1
    return minute, day


def enforce_rate_limit(items, settings, now=None):
    minute, day = usage_counts(items, now)
    if minute >= settings["minute_limit"]:
        raise ExternalAIError("已达到每分钟调用上限", "minute_limit")
    if day >= settings["daily_limit"]:
        raise ExternalAIError("已达到今日调用上限", "daily_limit")
    return minute, day
