"""Launch the application installed from a verified EXE, isolated from user data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from PyInstaller.archive.readers import CArchiveReader
import test_installer_release as checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18869)
    args = parser.parse_args()
    checks.validate_binary(args.binary)
    case = checks.InstallerReleaseTest()
    case.setUp()
    process = None
    log = None
    try:
        with tempfile.TemporaryDirectory(prefix="dashboard-bundle-resources-") as resources:
            archive = CArchiveReader(str(args.binary))
            entries = {name.replace("\\", "/"): name for name in archive.toc}
            for name in checks.installer.INSTALL_FILES + ["announcement.json"]:
                path = Path(resources) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extract(entries[name]))
            case.module.get_resource_path = lambda name: str(Path(resources) / name)
            case.install()
            if case.wizard.errors:
                raise RuntimeError(case.wizard.errors)
        config_path = case.target / "data/config.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        cfg.update({"watch_enabled": False, "auto_organize": False, "preview_warmup_enabled": False})
        config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        log = (case.base / "runtime.log").open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, "-B", "-u", str(case.target / "py/server.py"),
                                    "--port", str(args.port), "--no-watch"], cwd=case.target,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, USERPROFILE=str(case.home), HOME=str(case.home)),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        base = f"http://127.0.0.1:{args.port}"
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError((case.base / "runtime.log").read_text(encoding="utf-8"))
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                    health = json.load(response)
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Installed server did not become ready")
        with urllib.request.urlopen(base + "/api/announcements", timeout=3) as response:
            announcements = json.load(response)
        if announcements["version"] != checks.installer.APP_VERSION or not announcements["announcements"]:
            raise AssertionError("Installed announcements missing or stale")
        for resource in ("assignment_imports.js", "course_rules_editor.js", "course_subjects.js"):
            with urllib.request.urlopen(base + "/static/" + resource, timeout=3) as response:
                if response.status != 200:
                    raise AssertionError(resource)
        if health["version"] != checks.installer.APP_VERSION or health["watching"]:
            raise AssertionError("Installed server version or isolation is incorrect")
        print("INSTALLED_RUNTIME_OK", {k: health[k] for k in ("version", "watching", "students", "assignments")}, flush=True)
        print("BROWSER_VALIDATION_READY", base + "/modern#manage", flush=True)
        input("Press Enter to stop isolated validation server.\n")
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if log:
            log.close()
        case.tearDown()


if __name__ == "__main__":
    main()
