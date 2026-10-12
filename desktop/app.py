"""Native window and narrowly scoped dialog/clipboard bridge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from config import CONFIG_DIR
from desktop.service import Service


class InstanceLock:
    """One process per history directory, without stale lock files after a crash."""

    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self._file = (directory / "instance.lock").open("a+b")
        self._file.write(b"0")
        self._file.flush()
        self._file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            raise RuntimeError("FlipMD 已在运行。请使用已打开的窗口。") from exc

    def close(self):
        self._file.close()


class DesktopAPI:
    def __init__(self, service):
        self._service = service
        self._window = None

    def bootstrap(self):
        return self._service.bootstrap()

    def choose_files(self, folder=False):
        import webview

        selected = self._window.create_file_dialog(
            webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
            allow_multiple=not folder,
            file_types=() if folder else ("PDF 和 Word (*.pdf;*.docx)",),
        )
        if not selected:
            return []
        if folder:
            selected = sorted(
                str(path)
                for path in Path(selected[0]).iterdir()
                if path.is_file() and path.suffix.lower() in (".pdf", ".docx")
            )
            if not selected:
                raise ValueError("这个文件夹的当前层没有 PDF 或 DOCX 文件。")
        return self._service.register_files(selected)

    def choose_output(self):
        import webview

        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return selected[0] if selected else None

    def save_settings(self, settings):
        return self._service.save_settings(settings)

    def start_job(self, file_ids, options, output_dir="", format="md", mode="convert", title="合并文档"):
        return self._service.start_job(file_ids, options, output_dir, format, mode, title)

    def list_jobs(self):
        return self._service.list_jobs()

    def stop_job(self, job_id):
        return self._service.stop_job(job_id)

    def delete_job(self, job_id):
        return self._service.delete_job(job_id)

    def get_result(self, item_id):
        return self._service.get_result(item_id)

    def preview_source(self, source_id, page=1):
        return self._service.preview_source(source_id, page)

    def export_result(self, item_id, format="md"):
        import webview

        if format not in ("md", "html"):
            raise ValueError("输出格式无效。")
        item, _ = self._service.store.item(item_id)
        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=Path(item["name"]).stem + "." + format,
            file_types=(f"{format.upper()} (*.{format})",),
        )
        if not selected:
            return None
        target = Path(selected if isinstance(selected, str) else selected[0])
        if target.suffix.lower() != "." + format:
            raise ValueError(f"保存文件名请以 .{format} 结尾。")
        return self._service.export_to(item_id, target, format)

    def export_log(self, item_id):
        import webview

        item, result = self._service.store.item(item_id)
        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=Path(item["name"]).stem + "-log.txt",
            file_types=("日志文本 (*.txt)",),
        )
        if not selected:
            return None
        target = Path(selected if isinstance(selected, str) else selected[0])
        if target.suffix.lower() != ".txt":
            raise ValueError("日志文件请以 .txt 结尾。")
        target.write_text(result.get("logs", item.get("error", "")), encoding="utf-8")
        return str(target)

    def copy_text(self, text):
        import pyperclip

        if not isinstance(text, str):
            raise ValueError("复制内容格式无效。")
        pyperclip.copy(text)
        return True

    def reveal_result(self, item_id):
        item, _ = self._service.store.item(item_id)
        if not item["output_path"] or not Path(item["output_path"]).is_file():
            raise ValueError("结果文件已移动或尚未导出。可从任务历史重新导出。")
        path = Path(item["output_path"]).resolve()
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", "-R", str(path)], check=True)
        elif sys.platform == "win32":
            os.startfile(str(path.parent))
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=True)
        return True

    def _drop(self, event):
        paths = [entry.get("pywebviewFullPath") for entry in event.get("dataTransfer", {}).get("files", [])]
        paths = [path for path in paths if path]
        try:
            if not paths:
                raise ValueError("无法读取拖入文件，请使用“选择文件”。")
            files = self._service.register_files(paths)
            self._window.run_js(f"window.flipmd.receiveFiles({json.dumps(files, ensure_ascii=False)})")
        except Exception as exc:
            self._window.run_js(f"window.flipmd.showError({json.dumps(str(exc), ensure_ascii=False)})")


def main():
    parser = argparse.ArgumentParser(description="FlipMD 本地桌面客户端")
    parser.add_argument("--data-dir", type=Path, help="独立数据文件夹（便于测试，不影响默认历史）")
    parser.add_argument("--debug", action="store_true", help="开启开发者工具")
    parser.add_argument("--self-test", type=Path, metavar="REPORT", help="验证打包依赖并写入 JSON 报告，不打开窗口")
    parser.add_argument("files", nargs="*", help="打开时导入的 PDF / DOCX 文件")
    args = parser.parse_args()
    if args.self_test:
        from desktop.selftest import run

        raise SystemExit(run(args.self_test))
    if sys.platform == "win32":
        from desktop.windows import require_webview2

        try:
            require_webview2()
        except RuntimeError as exc:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, str(exc), "FlipMD 无法启动", 0x10)
            raise SystemExit(1) from exc
    directory = (args.data_dir or CONFIG_DIR / "desktop").expanduser().resolve()
    lock = InstanceLock(directory)
    service = Service(directory)
    try:
        import webview
        from webview.dom import DOMEventHandler

        api = DesktopAPI(service)
        assets = Path(__file__).parent / "web"
        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["ALLOW_FILE_URLS"] = False
        window = webview.create_window(
            "FlipMD",
            str(assets / "index.html"),
            js_api=api,
            width=1180,
            height=800,
            min_size=(820, 600),
            background_color="#ffffff",
            text_select=True,
        )
        api._window = window

        def loaded():
            window.dom.document.events.drop += DOMEventHandler(api._drop, prevent_default=True)
            if args.files:
                try:
                    files = service.register_files(args.files)
                    window.run_js(f"window.flipmd.receiveFiles({json.dumps(files, ensure_ascii=False)})")
                except Exception as exc:
                    window.run_js(f"window.flipmd.showError({json.dumps(str(exc), ensure_ascii=False)})")

        def closing():
            if service.has_active_jobs():
                window.run_js('window.flipmd.showError("仍有转换任务，请先停止后续文件，待当前文件完成后再关闭。");')
                return False

        window.events.loaded += loaded
        window.events.closing += closing
        webview.start(debug=args.debug, http_server=True, gui="edgechromium" if sys.platform == "win32" else None)
    finally:
        service.close()
        lock.close()


if __name__ == "__main__":
    main()
