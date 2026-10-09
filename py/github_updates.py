"""Bounded downloads from this project's public GitHub Releases, never arbitrary URLs."""
import copy
import hashlib
import html
import io
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "Trip1eY/Assignment_Dashboard"
MAX_UPDATE_BYTES = 96 * 1024 * 1024
_ALLOWED_HOSTS = {"github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
_cache = None
_cache_until = 0
_lock = threading.Lock()


def _allowed_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


class ReleaseRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise ValueError("更新下载重定向到非 GitHub 地址，已拒绝")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url, limit=2 * 1024 * 1024, timeout=10):
    if not _allowed_url(url):
        raise ValueError("更新地址不在允许范围")
    request = urllib.request.Request(url, headers={
        "User-Agent": "Assignment_Dashboard-Updater", "Accept": "application/json, text/html, */*"})
    opener = urllib.request.build_opener(ReleaseRedirectHandler())
    deadline = time.monotonic() + 60
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        if not _allowed_url(final_url):
            raise ValueError("更新下载地址不在允许范围")
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError("更新响应超出大小限制")
        chunks, total = [], 0
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("更新下载超时")
            chunk = response.read(min(256 * 1024, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("更新响应超出大小限制")
            chunks.append(chunk)
        return b"".join(chunks), final_url


def _valid_tag(tag):
    return bool(re.fullmatch(r"[vV]?[0-9][0-9A-Za-z._-]{0,63}", tag))


def _valid_name(name):
    return bool(re.fullmatch(r"dashboard_update_v[0-9A-Za-z._-]+\.zip", name))


def _asset_url(tag, name):
    if not _valid_tag(tag) or not _valid_name(name):
        raise ValueError("更新版本或文件名不合法")
    return f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"


def _web_release():
    raw, final = _fetch(f"https://github.com/{REPOSITORY}/releases/latest")
    prefix = f"/{REPOSITORY}/releases/tag/"
    path = urllib.parse.urlsplit(final).path
    if not path.startswith(prefix):
        raise ValueError("尚未找到最新正式 Release")
    tag = urllib.parse.unquote(path[len(prefix):])
    if not _valid_tag(tag):
        raise ValueError("Release 版本格式不正确")
    assets_html, _ = _fetch(f"https://github.com/{REPOSITORY}/releases/expanded_assets/{tag}")
    prefix = f"/{REPOSITORY}/releases/download/{tag}/"
    names = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', assets_html.decode("utf-8")):
        href = html.unescape(href)
        if href.startswith(prefix):
            name = urllib.parse.unquote(href[len(prefix):])
            if _valid_name(name) and name not in names:
                names.append(name)
    return {"tag_name": tag, "name": tag, "html_url": final, "body": "", "published_at": "",
            "assets": [{"name": name, "browser_download_url": _asset_url(tag, name), "size": 0} for name in names],
            "source": "github_web"}


def get_latest(force=False):
    global _cache, _cache_until
    with _lock:
        if not force and _cache is not None and time.monotonic() < _cache_until:
            return copy.deepcopy(_cache)
        try:
            raw, _ = _fetch(f"https://api.github.com/repos/{REPOSITORY}/releases/latest")
            release = json.loads(raw.decode("utf-8"))
            if (not isinstance(release, dict)
                    or not _valid_tag(str(release.get("tag_name") or ""))
                    or not isinstance(release.get("assets"), list)):
                raise ValueError("GitHub 更新信息格式无效")
            release["source"] = "github_api"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Public release pages remain usable when the unauthenticated API is rate-limited.
            release = _web_release()
        tag = str(release.get("tag_name") or "")
        if not _valid_tag(tag):
            raise ValueError("Release 版本格式不正确")
        assets = []
        for item in release.get("assets") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if not _valid_name(name):
                continue
            expected = _asset_url(tag, name)
            if item.get("browser_download_url") != expected:
                continue
            assets.append({"name": name, "size": item.get("size", 0),
                           "browser_download_url": expected, "digest": item.get("digest", "")})
        release["assets"] = assets
        _cache, _cache_until = copy.deepcopy(release), time.monotonic() + 300
        return copy.deepcopy(release)


def download_release(version, name):
    release = get_latest()
    tag = release["tag_name"]
    if str(version).lstrip("vV") != tag.lstrip("vV"):
        raise ValueError("最新版本已变化，请重新检查更新")
    asset = next((a for a in release["assets"] if a["name"] == name), None)
    if asset is None:
        raise ValueError("更新文件不属于最新 Release，请重新检查更新")
    size = int(asset.get("size") or 0)
    if size > MAX_UPDATE_BYTES:
        raise ValueError("更新包超出大小限制")
    data, _ = _fetch(_asset_url(tag, name), MAX_UPDATE_BYTES, timeout=15)
    if size and len(data) != size:
        raise ValueError("更新包下载不完整")
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:") and hashlib.sha256(data).hexdigest() != digest[7:]:
        raise ValueError("更新包校验失败")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
        if (not isinstance(manifest, dict)
                or str(manifest.get("version") or "").lstrip("vV") != tag.lstrip("vV")):
            raise ValueError("更新包版本与 Release 不一致")
    return data
