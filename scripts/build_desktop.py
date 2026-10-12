"""Build a desktop bundle on the target OS (not a cross compiler).

uv run --python 3.12 --frozen --extra desktop --with pyinstaller==6.22.3 python scripts/build_desktop.py
"""

from __future__ import annotations

import argparse
import json
import platform
import plistlib
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desktop.version import project_version  # noqa: E402


def build_command(root, target):
    if target not in ("darwin", "win32"):
        raise ValueError("仅支持 macOS 和 Windows 构建。")
    dist = root / "dist" / "windows" if target == "win32" else root / "dist" / project_version(root / "pyproject.toml")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name",
        "FlipMD",
        "--paths",
        str(root),
        "--distpath",
        str(dist),
        "--workpath",
        str(root / "build" / "desktop"),
        "--specpath",
        str(root / "build"),
        "--add-data",
        f"{root / 'desktop' / 'web'}:desktop/web",
        "--add-data",
        f"{root / 'tests' / 'samples' / 'simple_test.pdf'}:desktop/samples",
        "--add-data",
        f"{root / 'LICENSE'}:.",
        "--add-data",
        f"{root / 'pyproject.toml'}:.",
        "--icon",
        str(root / "desktop" / "web" / "assets" / "flipmd-symbol-v3-blue.png"),
        "--collect-data",
        "webview",
        "--collect-data",
        "pdfminer",
        "--collect-all",
        "pypdfium2_raw",
    ]
    if target == "darwin":
        command.extend(["--osx-bundle-identifier", "local.pdf2md.desktop",
                        "--hidden-import", "webview.platforms.cocoa"])
    else:
        command.extend(["--hidden-import", "webview.platforms.winforms",
                        "--hidden-import", "webview.platforms.edgechromium",
                        "--hidden-import", "clr", "--hidden-import", "_cffi_backend",
                        "--collect-all", "pythonnet", "--collect-all", "clr_loader"])
    for module in (
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "gi",
        "tkinter",
        "webview.platforms.qt",
        "webview.platforms.gtk",
        "pytest",
    ):
        command.extend(["--exclude-module", module])
    command.append(str(root / "desktop" / "__main__.py"))
    return command


def build_plan(root, target):
    version = project_version(root / "pyproject.toml")
    command = build_command(root, target)
    dist = Path(command[command.index("--distpath") + 1])
    output = dist / "FlipMD" / "FlipMD.exe" if target == "win32" else dist / "FlipMD.app"
    return {
        "command": command,
        "output": str(output),
        "version": version,
        "info_plist": {"CFBundleShortVersionString": version, "CFBundleVersion": version}
        if target == "darwin" else None,
    }


def stamp_mac_version(bundle, version):
    path = bundle / "Contents" / "Info.plist"
    with path.open("rb") as stream:
        info = plistlib.load(stream)
    info.update(CFBundleShortVersionString=version, CFBundleVersion=version)
    with path.open("wb") as stream:
        plistlib.dump(info, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-platform", choices=("darwin", "win32"), default=sys.platform)
    parser.add_argument("--dry-run", action="store_true", help="只打印构建参数，不生成安装包")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    plan = build_plan(root, args.target_platform)
    command = plan["command"]
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if args.target_platform != sys.platform:
        raise SystemExit("需要在目标系统上运行构建：macOS 不能用此脚本生成 Windows exe。")
    if sys.platform == "win32" and (struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64")):
        raise SystemExit("当前 Windows 构建需要 x64 版本的 Python 3.12。")
    subprocess.run(command, cwd=root, check=True)
    output = Path(plan["output"])
    if not output.exists():
        raise SystemExit(f"未生成预期产物：{output}")
    if sys.platform == "darwin":
        stamp_mac_version(output, plan["version"])
        # Changing Info.plist invalidates PyInstaller's ad-hoc bundle signature.
        subprocess.run(["codesign", "--force", "--sign", "-", str(output)], check=True)
    print(output)


if __name__ == "__main__":
    main()
