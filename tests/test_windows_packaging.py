"""Checks executable locally; these do not claim native Windows UI validation."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from desktop import selftest
from desktop.windows import valid_runtime_version, webview2_installed


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("0.0.0.0", False), ("broken", False), ("120.0.0.0", True), ("153.0.8010.0", True)],
)
def test_webview2_version_validation(value, expected):
    assert valid_runtime_version(value) is expected


@pytest.mark.parametrize("location", [(1, 32), (2, 32), (2, 64), None])
def test_runtime_detects_user_and_machine_registry_views(monkeypatch, location):
    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def open_key(hive, path, reserved, flags):
        if (hive, flags) != location:
            raise FileNotFoundError(path)
        return Key()

    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_32KEY=32,
        KEY_WOW64_64KEY=64, KEY_READ=0, OpenKey=open_key,
        QueryValueEx=lambda key, name: ("153.0.8010.0", 1),
    ))
    assert webview2_installed() is (location is not None)


def test_bundle_selftest_converts_real_fixtures_and_reports(tmp_path):
    # The Windows renderer branch requires a Windows runner with WebView2.
    if sys.platform == "win32":
        pytest.skip("Windows bundle verification runs after the installer provisions WebView2.")
    report = tmp_path / "self-test.json"
    assert selftest.run(report) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["ok"] is True and result["ui_tested"] is False
    assert "PDF conversion / PDFium" in result["checks"]
    assert "SQLite history restart" in result["checks"]


def test_selftest_failure_is_explicit(tmp_path, monkeypatch):
    def missing_fixture(*args):
        raise FileNotFoundError("missing bundle fixture")

    monkeypatch.setattr(selftest.shutil, "copyfile", missing_fixture)
    # Keep this failure-path check independent of Windows runtime availability.
    monkeypatch.setattr(selftest.sys, "platform", "darwin")
    report = tmp_path / "failed.json"
    assert selftest.run(report) == 1
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["ok"] is False and "missing bundle fixture" in result["error"]


def test_build_refuses_cross_compilation():
    target = "win32" if sys.platform != "win32" else "darwin"
    result = subprocess.run(
        [sys.executable, "scripts/build_desktop.py", "--target-platform", target],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0
    assert "需要在目标系统上运行构建" in result.stderr
