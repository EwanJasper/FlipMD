"""跨平台启动脚本

用 uv 或 python 直接启动 GUI，替代原 Windows 专属的 .bat / .vbs。
在 Windows / macOS / Linux 上均可运行。

用法：
    uv run python launch.py            # 控制台模式（显示日志，便于排障）
    python launch.py                   # 无 uv 时直接用当前 python
    python launch.py --no-console      # Windows 无控制台窗口（等价原 .vbs）

各平台双击启动：
    Windows:  双击「启动工具.bat」
    macOS/Linux: chmod +x launch.sh && ./launch.sh
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _find_uv() -> str | None:
    """检测 uv 是否在 PATH 上，返回路径或 None"""
    return shutil.which("uv")


def _pythonw() -> str | None:
    """Windows 下查找 pythonw.exe（无控制台窗口的 python），返回路径或 None"""
    if sys.platform != "win32":
        return None
    exe = sys.executable
    # python.exe -> pythonw.exe（同目录）
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return candidate if os.path.exists(candidate) else None


def main() -> None:
    # 解析参数
    no_console = "--no-console" in sys.argv

    # 切换到项目根目录（launch.py 所在目录），等价 .bat 的 cd /d "%~dp0"
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    uv = _find_uv()

    if no_console and sys.platform == "win32":
        # 无控制台窗口模式：用 pythonw 启动，等价原 .vbs
        pythonw = _pythonw()
        if pythonw is None:
            print("未找到 pythonw.exe，无法以无控制台模式启动，回退到控制台模式")
            no_console = False
        else:
            # pythonw 不需要 uv run（uv run 会创建子进程带控制台）
            # 直接用 pythonw 跑 main.py
            subprocess.run([pythonw, "main.py"])
            return

    if uv:
        # 有 uv：用 uv run（自动使用项目虚拟环境）
        subprocess.run(["uv", "run", "python", "main.py"])
    else:
        # 无 uv：降级为当前 python 直接运行
        print("未检测到 uv，使用当前 Python 直接启动。")
        print("建议安装 uv 以自动管理依赖：https://docs.astral.sh/uv/")
        print()
        subprocess.run([sys.executable, "main.py"])


if __name__ == "__main__":
    main()
