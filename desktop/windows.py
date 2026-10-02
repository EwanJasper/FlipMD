"""Windows startup prerequisite check; importing this module is cross platform."""

import re

WEBVIEW2_KEY = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def valid_runtime_version(value):
    return isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", value) is not None and any(
        int(part) for part in value.split(".")
    )


def webview2_installed():
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, WEBVIEW2_KEY, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, "pv")
                    if valid_runtime_version(value):
                        return True
            except OSError:
                continue
    return False


def require_webview2():
    if not webview2_installed():
        raise RuntimeError(
            "FlipMD 需要 Microsoft Edge WebView2 Runtime。\n"
            "请联网重新运行 FlipMD 安装程序，或从微软官网下载并安装：\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/consumer/"
        )
