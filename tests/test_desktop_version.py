"""Version contract across source, runtime and both platform build plans."""

import json
import plistlib
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from desktop import version
from desktop.service import Service
from scripts.build_desktop import build_plan, stamp_mac_version

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("target", ["darwin", "win32"])
def test_version_consistent_in_runtime_and_build(tmp_path, target):
    expected = version.project_version(ROOT / "pyproject.toml")
    service = Service(tmp_path / "state")
    try:
        assert service.bootstrap()["brand"]["version"] == expected
    finally:
        service.close()
    result = subprocess.run(
        [sys.executable, "scripts/build_desktop.py", "--target-platform", target, "--dry-run"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    plan = json.loads(result.stdout)
    assert plan["version"] == expected
    assert f"{ROOT / 'pyproject.toml'}:." in plan["command"]
    if target == "darwin":
        assert plan["info_plist"] == {"CFBundleShortVersionString": expected, "CFBundleVersion": expected}


def test_manifest_fallback_without_package_metadata(monkeypatch):
    def absent(name):
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(version.metadata, "version", absent)
    assert version.get_version() == version.project_version(ROOT / "pyproject.toml")


def test_editable_metadata_cannot_override_manifest(monkeypatch):
    monkeypatch.setattr(version.metadata, "version", lambda name: "0.0.0")
    assert version.get_version() == version.project_version(ROOT / "pyproject.toml")


def test_installed_package_without_source_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(version, "__file__", str(tmp_path / "desktop" / "version.py"))
    monkeypatch.setattr(version.metadata, "version", lambda name: "2.3.4")
    assert version.get_version() == "2.3.4"


def test_mac_stamp_preserves_other_plist_fields(tmp_path):
    contents = tmp_path / "FlipMD.app" / "Contents"
    contents.mkdir(parents=True)
    path = contents / "Info.plist"
    path.write_bytes(plistlib.dumps({"CFBundleIdentifier": "local.pdf2md.desktop", "CFBundleVersion": "0.0.0"}))
    expected = version.project_version(ROOT / "pyproject.toml")
    stamp_mac_version(contents.parent, expected)
    result = plistlib.loads(path.read_bytes())
    assert result["CFBundleIdentifier"] == "local.pdf2md.desktop"
    assert result["CFBundleVersion"] == result["CFBundleShortVersionString"] == expected


@pytest.mark.parametrize("release", ["0.4.0", "0.5.0"])
def test_mac_rebuild_targets_manifest_version_folder(tmp_path, release):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{release}"\n', encoding="utf-8")
    plan = build_plan(tmp_path, "darwin")
    command = plan["command"]
    assert command[command.index("--distpath") + 1] == str(tmp_path / "dist" / release)
    assert plan["output"] == str(tmp_path / "dist" / release / "FlipMD.app")
    assert build_plan(tmp_path, "darwin")["output"] == plan["output"]
    windows = build_plan(tmp_path, "win32")
    assert windows["output"] == str(tmp_path / "dist" / "windows" / "FlipMD" / "FlipMD.exe")
