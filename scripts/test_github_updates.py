"""Bounded GitHub release downloads, fallback, and same-origin API contracts."""
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py"))
import github_updates as updates
from test_course_rules_editor import DisposableServer


def package(version="0.1.3"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"version": version}))
    return buffer.getvalue()


def release(data=None):
    name = "dashboard_update_v0.1.3_windows.zip"
    return {"tag_name": "v0.1.3", "name": "fixture", "assets": [
        {"name": name, "size": len(data) if data else 0, "browser_download_url": updates._asset_url("v0.1.3", name),
         "digest": "sha256:" + hashlib.sha256(data).hexdigest() if data else ""}]}


class GithubUpdatesTest(unittest.TestCase):
    def setUp(self):
        updates._cache, updates._cache_until = None, 0

    def test_api_response_is_cached_and_returned_as_independent_copy(self):
        response = release()
        with patch.object(updates, "_fetch", return_value=(json.dumps(response).encode(), "")) as fetch:
            first = updates.get_latest()
            first["assets"].clear()
            self.assertEqual(len(updates.get_latest()["assets"]), 1)
            self.assertEqual(fetch.call_count, 1)

    def test_rate_limit_uses_public_webpage_fallback(self):
        prefix = f"/{updates.REPOSITORY}/releases"
        responses = [urllib.error.HTTPError("https://api.github.com", 403, "limited", {}, None),
                     (b"public page", f"https://github.com{prefix}/tag/v0.1.3"),
                     (f'<a href="{prefix}/download/v0.1.3/dashboard_update_v0.1.3_windows.zip">zip</a>'.encode(), "https://github.com")]
        with patch.object(updates, "_fetch", side_effect=responses):
            result = updates.get_latest()
        self.assertEqual(result["source"], "github_web")
        self.assertEqual(result["assets"][0]["name"], "dashboard_update_v0.1.3_windows.zip")

    def test_malformed_api_falls_back_without_internal_error(self):
        for malformed in ([], {"tag_name": None}, {"tag_name": "v0.1.3", "assets": "invalid"}):
            with patch.object(updates, "_fetch", return_value=(json.dumps(malformed).encode(), "")), \
                    patch.object(updates, "_web_release", return_value=release()):
                self.assertEqual(updates.get_latest(force=True)["tag_name"], "v0.1.3")

    def test_only_expected_repository_assets_are_kept(self):
        result = release()
        result["assets"].extend([None, {"name": "installer.exe"}, {
            "name": "dashboard_update_v0.1.3_other.zip", "browser_download_url": "https://github.com/other/project/file"}])
        with patch.object(updates, "_fetch", return_value=(json.dumps(result).encode(), "")):
            self.assertEqual(len(updates.get_latest()["assets"]), 1)

    def test_download_validates_size_digest_and_manifest(self):
        data = package()
        with patch.object(updates, "get_latest", return_value=release(data)), \
                patch.object(updates, "_fetch", return_value=(data, "")):
            self.assertEqual(updates.download_release("0.1.3", "dashboard_update_v0.1.3_windows.zip"), data)

    def test_changed_version_unknown_asset_and_large_size_are_rejected_before_download(self):
        result = release()
        with patch.object(updates, "get_latest", return_value=result), patch.object(updates, "_fetch") as fetch:
            for version, name in (("0.1.2", result["assets"][0]["name"]), ("0.1.3", "../file.zip")):
                with self.assertRaises(ValueError):
                    updates.download_release(version, name)
            result["assets"][0]["size"] = updates.MAX_UPDATE_BYTES + 1
            with self.assertRaises(ValueError):
                updates.download_release("0.1.3", result["assets"][0]["name"])
            fetch.assert_not_called()

    def test_corrupt_size_digest_and_manifest_are_rejected(self):
        data = package()
        for result, payload in ((release(data), data + b"extra"), (release(data), b"x" * len(data)),
                                (release(), package("0.1.2"))):
            with patch.object(updates, "get_latest", return_value=result), \
                    patch.object(updates, "_fetch", return_value=(payload, "")):
                with self.assertRaises(ValueError):
                    updates.download_release("0.1.3", result["assets"][0]["name"])

    def test_unsafe_urls_and_redirects_are_rejected(self):
        for url in ("http://github.com", "https://127.0.0.1", "https://github.com.evil.test",
                    "https://user@github.com", "https://github.com:8443", "https://github.com:invalid"):
            self.assertFalse(updates._allowed_url(url))
        handler = updates.ReleaseRedirectHandler()
        request = urllib.request.Request("https://github.com")
        with self.assertRaises(ValueError):
            handler.redirect_request(request, None, 302, "", {}, "http://127.0.0.1/private")

    def test_stream_limit_is_enforced_without_content_length(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):
                return "https://github.com"
        opener = type("Opener", (), {"open": lambda *_args, **_kwargs: Response(b"too-large")})()
        with patch.object(updates.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(ValueError):
                updates._fetch("https://github.com", limit=3)


class GithubUpdateEndpointTest(unittest.TestCase):
    def setUp(self):
        self.service = DisposableServer()
        self.data = package()
        self.latest = release(self.data)

    def tearDown(self):
        self.service.close()

    def test_check_returns_local_download_url(self):
        with patch.object(updates, "get_latest", return_value=self.latest):
            reply = self.service.request("/api/update/check")
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["asset"]["download_url"].startswith("/api/update/download?"))

    def test_download_returns_zip_without_installing_it(self):
        before = Path(self.service.temp.name).joinpath("config.json").read_bytes()
        with patch.object(updates, "download_release", return_value=self.data) as download:
            request = urllib.request.Request(self.service.base + "/api/update/download?version=0.1.3&name=fixture",
                                             headers={"Origin": self.service.base})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.headers["Content-Type"], "application/zip")
                self.assertEqual(response.read(), self.data)
            download.assert_called_once_with("0.1.3", "fixture")
        self.assertEqual(before, Path(self.service.temp.name).joinpath("config.json").read_bytes())

    def test_foreign_origin_is_rejected_before_network_access(self):
        with patch.object(updates, "download_release") as download:
            request = urllib.request.Request(self.service.base + "/api/update/download",
                                             headers={"Origin": "https://evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
            download.assert_not_called()

    def test_network_error_returns_readable_message(self):
        with patch.object(updates, "download_release", side_effect=OSError("fixture unavailable")):
            try:
                self.service.request("/api/update/download?version=0.1.3&name=fixture")
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 502)
                self.assertIn("fixture unavailable", json.load(error)["msg"])
            else:
                self.fail("expected 502")


if __name__ == "__main__":
    unittest.main(verbosity=2)
