"""Conversion orchestration independent of the native window."""

from __future__ import annotations

import importlib.util
import logging
import shutil
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from block import Block
from config import CONFIG_DIR, ConvertOptions, load_config
from desktop.preview import PDF_LOCK, data_url, docx_html, markdown_html, pdf_page
from desktop.store import Store
from engine import get_page_count, parse
from html_writer import render_html
from image_extract import extract_images
from markdown_writer import render
from summarize import summarize
from word_engine import parse_docx

ACTIVE = {"queued", "running"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_options(value):
    if not isinstance(value, dict):
        raise ValueError("转换设置格式不正确。")
    defaults = ConvertOptions().to_dict()
    for key, val in value.items():
        if key not in defaults:
            raise ValueError(f"未知转换设置：{key}")
        if isinstance(defaults[key], bool) and type(val) is not bool:
            raise ValueError(f"开关设置无效：{key}")
    merged = defaults | value
    if merged["ocr_lang"] not in ("ch", "en", "ch_en"):
        raise ValueError("不支持的 OCR 语言。")
    pages = merged["page_range"]
    if pages is not None:
        if (
            not isinstance(pages, (list, tuple))
            or len(pages) != 2
            or any(type(v) is not int for v in pages)
            or not 1 <= pages[0] <= pages[1]
        ):
            raise ValueError("页码范围应为正整数，结束页不得小于开始页。")
    return ConvertOptions.from_dict(merged)


def reserve_output(directory: Path, name: str, suffix: str):
    """Reserve a fresh destination, including when another process writes concurrently."""
    directory.mkdir(parents=True, exist_ok=True)
    for n in range(10000):
        candidate = directory / (name + (f"_{n}" if n else "") + suffix)
        try:
            with candidate.open("x", encoding="utf-8"):
                pass
            return candidate
        except FileExistsError:
            continue
    raise OSError("同名结果过多，请选择其他输出目录。")


class JobLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.thread_id = threading.get_ident()
        self.lines = []

    def emit(self, record):
        if record.thread == self.thread_id:
            self.lines.append(f"[{record.levelname}] {record.getMessage()}")


class Service:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else CONFIG_DIR / "desktop"
        self.store = Store(self.directory)
        self.store.recover()
        self._guard = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flipmd-convert")
        self._stops = {}
        self._futures = {}
        self._closed = False
        self.ocr_available = all(importlib.util.find_spec(name) is not None for name in ("paddleocr", "paddle"))
        if self.store.settings() is None:
            legacy = load_config()
            self.store.save_settings(
                {
                    "options": legacy.convert_options.to_dict(),
                    "output_dir": legacy.output_dir,
                    "format": "md",
                    "theme": "system",
                }
            )

    def bootstrap(self):
        return {
            "brand": {"name": "FlipMD", "tagline": "PDF / Word → Markdown"},
            "settings": self.store.settings(),
            "jobs": self.list_jobs(),
            "ocr": {
                "available": self.ocr_available,
                "message": "已检测到 OCR 依赖，首次识别可能需要下载模型。"
                if self.ocr_available
                else "未安装 OCR 组件；文字型 PDF 和 Word 可正常转换，扫描件需要 OCR。",
            },
        }

    def register_files(self, paths):
        files, seen = [], set()
        for raw in paths:
            path = Path(raw).expanduser().resolve()
            if path in seen:
                continue
            if path.suffix.lower() not in (".pdf", ".docx"):
                raise ValueError(f"不支持 {path.suffix or '此文件'}，请选择 PDF 或 DOCX。旧版 DOC 请另存为 DOCX。")
            if not path.is_file():
                raise ValueError(f"找不到文件：{path.name}")
            seen.add(path)
            stat = path.stat()
            files.append(
                {
                    "id": uuid4().hex,
                    "path": str(path),
                    "name": path.name,
                    "kind": path.suffix[1:].upper(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
        for source in files:
            self.store.add_source(source)
        return files

    def save_settings(self, settings):
        options = validate_options(settings.get("options", {})).to_dict()
        if settings.get("theme") not in ("light", "dark", "system"):
            raise ValueError("外观设置无效。")
        if settings.get("format") not in ("md", "html"):
            raise ValueError("输出格式无效。")
        output = settings.get("output_dir", "")
        if not isinstance(output, str):
            raise ValueError("输出位置无效。")
        value = {"options": options, "output_dir": output, "format": settings["format"], "theme": settings["theme"]}
        self.store.save_settings(value)
        return value

    def start_job(self, file_ids, options, output_dir="", format="md", mode="convert", title="合并文档"):
        with self._guard:
            if self._closed:
                raise ValueError("应用正在关闭。")
            if mode not in ("convert", "merge", "summary") or format not in ("md", "html"):
                raise ValueError("任务类型或输出格式无效。")
            if not isinstance(file_ids, list) or not file_ids or len(set(file_ids)) != len(file_ids):
                raise ValueError("请先选择文件，且不要重复添加相同文件。")
            if mode == "merge" and len(file_ids) < 2:
                raise ValueError("合并需要至少两个文件。")
            if not isinstance(title, str) or not title.strip() or any(c in title for c in "/\\\x00"):
                raise ValueError("请输入有效的输出名称，不包含路径分隔符。")
            if not isinstance(output_dir, str):
                raise ValueError("输出位置无效。")
            opts = validate_options(options)
            sources = [self.store.source(i) for i in file_ids]
            job_id = uuid4().hex
            job = {
                "id": job_id,
                "created_at": now(),
                "mode": mode,
                "state": "queued",
                "stop_requested": False,
                "options": opts.to_dict(),
                "output_dir": output_dir,
                "format": format,
                "title": title.strip(),
                "processed_sources": 0,
                "source_total": len(sources),
            }
            groups = [sources] if mode == "merge" else [[source] for source in sources]
            items = []
            for group in groups:
                first = group[0]
                items.append(
                    {
                        "id": uuid4().hex,
                        "job_id": job_id,
                        "source_id": first["id"],
                        "source_ids": [s["id"] for s in group],
                        "name": title.strip() if mode == "merge" else first["name"],
                        "path": first["path"],
                        "kind": first["kind"],
                        "state": "queued",
                        "pages": None,
                        "error": "",
                        "output_path": "",
                        "created_at": job["created_at"],
                    }
                )
            self.store.create_job(job, items)
            self._stops[job_id] = threading.Event()
            self._futures[job_id] = self._executor.submit(self._run_job, job_id)
            return {"id": job_id}

    def list_jobs(self):
        jobs = self.store.jobs()
        for job in jobs:
            job["total"] = len(job["items"])
            job["done"] = sum(item["state"] in ("completed", "failed") for item in job["items"])
        return jobs

    def stop_job(self, job_id):
        with self._guard:
            job = self.store.job(job_id)
            if job["state"] not in ACTIVE:
                return False
            self._stops[job_id].set()
            self.store.update_job(job_id, stop_requested=True)
            return True

    def delete_job(self, job_id):
        with self._guard:
            if self.store.job(job_id)["state"] in ACTIVE:
                raise ValueError("任务还在处理中，请等待当前文件完成后再删除记录。")
            # Only database history is removed. Source files, exports and cached assets remain untouched.
            self.store.delete_job(job_id)
            return True

    def _parse(self, source, opts):
        path = Path(source["path"])
        if not path.is_file():
            raise FileNotFoundError(f"找不到原文件：{path.name}")
        if source["kind"] == "PDF":
            with PDF_LOCK:
                pages = get_page_count(str(path))
                if opts.page_range and opts.page_range[1] > pages:
                    raise ValueError(f"页码范围超出文档范围；本文件共 {pages} 页。")
                blocks = parse(str(path), opts)
        else:
            pages = None
            blocks = parse_docx(str(path), opts.with_overrides(page_range=None))
        if not blocks:
            raise ValueError("没有提取到可转换的内容。若为扫描件，请检查 OCR 是否可用。")
        return blocks, pages

    def _run_job(self, job_id):
        job = self.store.job(job_id)
        stop = self._stops[job_id]
        self.store.update_job(job_id, state="running")
        try:
            for item in job["items"]:
                if stop.is_set():
                    self.store.update_item(item["id"], state="stopped")
                    continue
                self._run_item(job, item, stop)
            states = [item["state"] for item in self.store.job(job_id)["items"]]
            state = "completed"
            if "stopped" in states:
                state = "stopped"
            elif "failed" in states:
                state = "partial" if "completed" in states else "failed"
            elif any(item["error"] for item in self.store.job(job_id)["items"]):
                state = "partial"
            self.store.update_job(job_id, state=state, stop_requested=False)
        except Exception as exc:
            for item in self.store.job(job_id)["items"]:
                if item["state"] in ACTIVE:
                    self.store.update_item(item["id"], state="failed", error=str(exc))
            self.store.update_job(job_id, state="failed", stop_requested=False)

    def _run_item(self, job, item, stop):
        self.store.update_item(item["id"], state="running")
        log = JobLog()
        logging.getLogger().addHandler(log)
        log.lines.append(f"[{now()}] 开始 {item['name']}")
        output = None
        try:
            opts = validate_options(job["options"])
            artifact_dir = self.directory / "results" / item["id"]
            artifact_dir.mkdir(parents=True, exist_ok=True)
            blocks, manifest, failed = [], [], []
            pages = None
            for index, source_id in enumerate(item["source_ids"]):
                if stop.is_set():
                    log.lines.append("停止后续文件；此项尚未生成结果。")
                    self.store.update_item(item["id"], state="stopped", result={"logs": "\n".join(log.lines)})
                    return
                source = self.store.source(source_id)
                try:
                    parsed, pages = self._parse(source, opts)
                    log.lines.append(f"已读取 {source['name']}")
                    if opts.extract_images and job["mode"] != "summary":
                        image_target = artifact_dir / source_id / "result.md"
                        image_target.parent.mkdir(parents=True, exist_ok=True)
                        with PDF_LOCK:
                            images = extract_images(source["path"], str(image_target))
                        for image in images:
                            cached = source_id + "/" + image.image_path
                            image.image_path = cached
                            manifest.append({"ref": cached, "cache_rel": cached})
                        parsed += images
                        parsed.sort(key=lambda block: block.y_top)
                        log.lines.append(f"已提取 {len(images)} 张图片")
                    if job["mode"] == "merge":
                        blocks.append(Block(type="paragraph", text="## " + Path(source["name"]).stem))
                    blocks.extend(parsed)
                except Exception as exc:
                    if job["mode"] != "merge":
                        raise
                    failed.append(source["name"])
                    log.lines.append(f"合并跳过 {source['name']}：{exc}")
                finally:
                    count = self.store.job(job["id"])["processed_sources"] + 1
                    self.store.update_job(job["id"], processed_sources=count)
                if stop.is_set() and index < len(item["source_ids"]) - 1:
                    self.store.update_item(item["id"], state="stopped", result={"logs": "\n".join(log.lines)})
                    return
            if not blocks:
                raise ValueError("没有成功解析的文档。" + "、".join(failed))
            title = job["title"] if job["mode"] == "merge" else Path(item["name"]).stem
            summary = summarize(blocks, title=title)
            if job["mode"] != "summary":
                directory = Path(job["output_dir"]).expanduser() if job["output_dir"] else Path(item["path"]).parent
                output = reserve_output(directory, title, "." + job["format"])
                asset_name = "assets_" + item["id"]
                refs = {
                    asset["ref"]: asset_name + f"/image-{i}" + Path(asset["cache_rel"]).suffix
                    for i, asset in enumerate(manifest)
                }
                for block in blocks:
                    if block.type == "image":
                        block.image_path = refs[block.image_path]
                for asset in manifest:
                    asset["ref"] = refs[asset["ref"]]
                    destination = output.parent / asset["ref"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(artifact_dir / asset["cache_rel"], destination)
            metadata = {"source": item["name"], "format": item["kind"], "converted": now()}
            if pages is not None and job["mode"] != "merge":
                metadata["pages"] = pages
            markdown = render(blocks, title=title, options=opts, metadata=metadata)
            document_html = render_html(blocks, title=title)
            if output:
                output.write_text(document_html if job["format"] == "html" else markdown, encoding="utf-8")
                log.lines.append(f"已保存 {output}")
            else:
                log.lines.append("大纲与摘要已生成，结果保存在任务历史中。")
            if failed:
                log.lines.append("部分文件未合并：" + "、".join(failed))
            result = {
                "markdown": markdown,
                "document_html": document_html,
                "summary": summary,
                "logs": "\n".join(log.lines),
                "assets": manifest,
                "options": job["options"],
            }
            self.store.update_item(
                item["id"],
                result=result,
                state="completed",
                pages=pages if job["mode"] != "merge" else None,
                output_path=str(output) if output else "",
                error="部分文件未合并：" + "、".join(failed) if failed else "",
            )
        except Exception as exc:
            log.lines.append(f"失败：{exc}\n{traceback.format_exc()}")
            self.store.update_item(item["id"], state="failed", error=str(exc), result={"logs": "\n".join(log.lines)})
            if output is not None and output.exists() and output.stat().st_size == 0:
                output.unlink()
        finally:
            logging.getLogger().removeHandler(log)

    def preview_source(self, source_id, page=1):
        source = self.store.source(source_id)
        path = Path(source["path"])
        if not path.is_file():
            raise ValueError("原文件已移动或删除。右侧保留转换时的结果，可继续查看或导出。")
        if type(page) is not int or page < 1:
            raise ValueError("页码无效。")
        result = pdf_page(path, page) if source["kind"] == "PDF" else docx_html(path)
        stat = path.stat()
        if stat.st_mtime_ns != source["mtime_ns"] or stat.st_size != source["size"]:
            result["note"] = "原文件在导入后有改动，当前预览可能与历史结果不同。"
        return result

    def get_result(self, item_id):
        item, stored = self.store.item(item_id)
        images = {}
        for asset in stored.get("assets", []):
            image = self.directory / "results" / item_id / asset["cache_rel"]
            if image.is_file():
                from PIL import Image

                try:
                    with Image.open(image) as picture:
                        mime = Image.MIME.get(picture.format, "image/png")
                    images[asset["ref"]] = data_url(image.read_bytes(), mime)
                except OSError:
                    pass
        sources = [self.store.source(i) for i in item["source_ids"]]
        for source in sources:
            source["exists"] = Path(source["path"]).is_file()
        markdown = stored.get("markdown", "")
        return {
            "item": item,
            "markdown": markdown,
            "html": markdown_html(markdown, images),
            "summary": stored.get("summary", {"outline": [], "stats": {"paragraphs": 0, "tables": 0, "table_rows": 0}}),
            "logs": stored.get("logs", item.get("error", "")),
            "sources": sources,
            "options": stored.get("options", {}),
        }

    def export_to(self, item_id, target, format="md"):
        if format not in ("md", "html"):
            raise ValueError("不支持的导出格式。")
        _, stored = self.store.item(item_id)
        if "markdown" not in stored:
            raise ValueError("此任务还没有可导出的结果。")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Native save dialog handles overwrite confirmation for the document only.
        # Image folders get a new identifier and never overwrite unrelated files.
        asset_name = "assets_" + uuid4().hex
        content = stored["document_html"] if format == "html" else stored["markdown"]
        for index, asset in enumerate(stored.get("assets", [])):
            ref = asset_name + f"/image-{index}" + Path(asset["cache_rel"]).suffix
            source = self.directory / "results" / item_id / asset["cache_rel"]
            if not source.is_file():
                raise ValueError("结果图片缓存缺失，无法完整导出。")
            destination = target.parent / ref
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            content = content.replace(asset["ref"], ref)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def has_active_jobs(self):
        return any(job["state"] in ACTIVE for job in self.store.jobs())

    def wait(self, job_id, timeout=30):
        self._futures[job_id].result(timeout=timeout)
        return self.store.job(job_id)

    def close(self):
        with self._guard:
            self._closed = True
            for event in self._stops.values():
                event.set()
        self._executor.shutdown(wait=True)
        self.store.close()
