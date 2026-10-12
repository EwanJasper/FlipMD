"""Resolve the app version from package metadata or the bundled project manifest."""

import re
from importlib import metadata
from pathlib import Path


def project_version(path):
    """Read the single project.version field, including on supported Python 3.10."""
    text = Path(path).read_text(encoding="utf-8")
    section = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    match = re.search(r'''(?m)^version\s*=\s*["'](\d+\.\d+\.\d+)["']\s*$''', section[1] if section else "")
    if not match:
        raise ValueError("pyproject.toml 缺少有效的三段式发布版本号。")
    return match[1]


def get_version():
    manifest = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        installed = metadata.version("pdf-to-markdown")
    except metadata.PackageNotFoundError:
        installed = None
    # An editable install can have stale metadata after a source version bump.
    # The source/bundled manifest remains authoritative when it is present.
    if manifest.is_file():
        return project_version(manifest)
    if installed:
        return installed
    raise RuntimeError("无法读取 FlipMD 版本：软件包元数据和项目清单均缺失。")
