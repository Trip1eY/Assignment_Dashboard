"""Resolve an optional external backup location without a silent local fallback."""
import json
import os
from pathlib import Path


def backup_directory(base_dir):
    base = Path(base_dir)
    location = os.environ.get("ASSIGNMENT_DASHBOARD_BACKUP_DIR", "").strip()
    settings = base / "data" / "backup_location.json"
    if not location and settings.exists():
        payload = json.loads(settings.read_text(encoding="utf-8"))
        location = payload.get("directory", "")
        if not isinstance(location, str) or not location.strip():
            raise ValueError("备份位置配置无效，未回退到本机")
    if not location:
        return base / "backups"
    target = Path(location.strip()).expanduser()
    if not target.is_absolute():
        raise ValueError("备份位置必须是绝对路径，未回退到本机")
    return target
