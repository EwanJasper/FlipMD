"""PDF/Word -> Markdown MCP Server

将现有转换能力封装为 MCP（Model Context Protocol）server，提供三个工具：
- convert_to_markdown：转换单个 PDF/Word 文档
- batch_convert：批量转换目录下所有文档
- get_document_info：获取文档基本信息

复用 engine / word_engine / markdown_writer / html_writer / config 等底层模块，
不重写核心逻辑。传输方式为 stdio（由 MCP 客户端以子进程方式启动）。

用法：
    uv run python mcp_server.py          # 直接运行（stdio）
    pw-to-markdown-mcp                   # 通过入口点运行
    uv run mcp dev mcp_server.py         # 用 MCP Inspector 调试
"""

from __future__ import annotations

import os
import sys

# Windows GBK 终端兼容：强制 stdout/stderr 用 UTF-8（与 cli.py 一致）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from mcp.server import MCPServer

from block import Block, PdfEmptyError, PdfEncryptedError
from config import ConvertOptions
from engine import get_page_count
from engine import parse as parse_pdf
from html_writer import render_html
from markdown_writer import merge_and_render, render
from output_path import resolve_unique_output_path
from summarize import summarize
from word_engine import parse_docx

mcp = MCPServer(
    "pw-to-markdown",
    title="PDF & Word -> Markdown",
    description="将 PDF / Word(.docx)文档转换为 Markdown 或 HTML，支持表格提取、跨页合并、中文排版优化、扫描件 OCR。",
)


# ── 辅助函数 ────────────────────────────────────────────────────

def _build_options(
    business_mode: bool = False,
    enable_ocr: bool = True,
    ocr_lang: str = "ch",
    page_range: list[int] | None = None,
    extract_images: bool = False,
    remove_cjk_spaces: bool = True,
    merge_broken_paragraphs: bool = True,
    fix_headings: bool = True,
    merge_cross_page_tables: bool = True,
    filter_footer: bool = True,
    merge_blank_lines: bool = True,
    add_front_matter: bool = False,
) -> ConvertOptions:
    """把工具参数映射为 ConvertOptions。

    business_mode=True 时启用业务规则（序号修复 + 空表头推断），其余开关按显式传入值。
    page_range 从 list[int] 转为 tuple[int, int]，供 ConvertOptions 使用。
    """
    if business_mode:
        opts = ConvertOptions.business()
    else:
        opts = ConvertOptions.default()

    # 覆盖单项开关（业务模式已开启的规则不强制关闭）
    opts.enable_ocr = enable_ocr
    opts.ocr_lang = ocr_lang
    opts.extract_images = extract_images
    opts.remove_cjk_spaces = remove_cjk_spaces
    opts.merge_broken_paragraphs = merge_broken_paragraphs
    opts.fix_headings = fix_headings
    opts.merge_cross_page_tables = merge_cross_page_tables
    opts.filter_footer = filter_footer
    opts.merge_blank_lines = merge_blank_lines
    opts.add_front_matter = add_front_matter

    if page_range is not None:
        if len(page_range) != 2:
            raise ValueError(f"page_range 应为 [start, end] 两个整数，收到: {page_range}")
        opts.page_range = (int(page_range[0]), int(page_range[1]))

    return opts


def _parse_blocks(file_path: str, options: ConvertOptions) -> tuple[list[Block], str, int]:
    """根据扩展名选择引擎解析，返回 (blocks, ext, page_count)。

    page_count 仅对 PDF 有意义，Word 返回 0。
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            page_count = get_page_count(file_path)
        except Exception:
            page_count = 0
        blocks = parse_pdf(file_path, options)
        return blocks, ext, page_count
    elif ext == ".docx":
        blocks = parse_docx(file_path, options)
        return blocks, ext, 0
    elif ext == ".doc":
        raise ValueError("不支持 .doc 格式，请先用 Word 另存为 .docx")
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def _render_content(
    blocks: list[Block], title: str, fmt: str,
    options: ConvertOptions | None = None, metadata: dict | None = None,
) -> str:
    """根据格式选择渲染器，返回内容字符串。"""
    if fmt == "html":
        return render_html(blocks, title=title)
    return render(blocks, title=title, options=options, metadata=metadata)


def _stats(blocks: list[Block], content: str, page_count: int) -> dict:
    """从 blocks 和 content 计算统计信息。"""
    # 统计解析失败的页（engine.parse 单页失败会生成占位段落）
    page_errors = [
        b.text for b in blocks
        if b.type == "paragraph" and b.text.startswith("*[第") and "解析失败" in b.text
    ]
    return {
        "page_count": page_count,
        "paragraphs": sum(1 for b in blocks if b.type == "paragraph"),
        "tables": sum(1 for b in blocks if b.type == "table"),
        "lines": len(content.splitlines()),
        "page_errors": page_errors,
    }


def _ocr_status(file_path: str, opts: ConvertOptions, ext: str) -> str:
    """计算 OCR 状态，告知调用方 OCR 是否生效。

    返回值：
    - "disabled": 用户关闭了 OCR（enable_ocr=False）
    - "not_applicable": 非 PDF 文件（Word 无 OCR 概念）
    - "not_scanned": 文本型 PDF，无需 OCR（与 PaddleOCR 是否安装无关）
    - "unavailable": 扫描型 PDF，但 PaddleOCR 未安装（将回退文本提取，内容可能不完整）
    - "applied": 扫描型 PDF，已尝试 OCR
    """
    if not opts.enable_ocr:
        return "disabled"
    if ext != ".pdf":
        return "not_applicable"
    try:
        from ocr import is_paddleocr_available, is_scanned_pdf
        if not is_scanned_pdf(file_path):
            return "not_scanned"
        if not is_paddleocr_available():
            return "unavailable"
        return "applied"
    except Exception:
        return "unavailable"


def _format_size(size_bytes: float) -> str:
    """字节大小转人类可读字符串。"""
    for unit in ["B", "KB", "MB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


def _error_result(error: str, **extra) -> dict:
    """构造统一的错误返回结构。"""
    result = {"success": False, "error": error}
    result.update(extra)
    return result


def _collect_files(directory: str, recursive: bool) -> list[str]:
    """收集目录下的 PDF/DOCX 文件路径。"""
    inputs: list[str] = []
    if recursive:
        for root, _dirs, files in os.walk(directory):
            for fname in files:
                if fname.lower().endswith((".pdf", ".docx")):
                    inputs.append(os.path.join(root, fname))
    else:
        for fname in sorted(os.listdir(directory)):
            if fname.lower().endswith((".pdf", ".docx")):
                inputs.append(os.path.join(directory, fname))
    return inputs


# ── 后处理开关的公共参数签名（三个工具复用同一组开关） ─────────────
# 注意：以下两个工具的参数列表保持一致，便于 LLM 理解。修改时请同步更新。


@mcp.tool()
def convert_to_markdown(
    file_path: str,
    output_path: str = "",
    format: str = "md",
    business_mode: bool = False,
    enable_ocr: bool = True,
    ocr_lang: str = "ch",
    page_range: list[int] | None = None,
    extract_images: bool = False,
    remove_cjk_spaces: bool = True,
    merge_broken_paragraphs: bool = True,
    fix_headings: bool = True,
    merge_cross_page_tables: bool = True,
    filter_footer: bool = True,
    merge_blank_lines: bool = True,
    add_front_matter: bool = False,
    max_content_chars: int = 50000,
) -> dict:
    """将单个 PDF 或 Word(.docx)文档转换为 Markdown（或 HTML）。

    支持表格提取、跨页表格合并、中文排版优化、扫描型 PDF OCR。
    返回转换后的文本内容及统计信息；若指定 output_path 则同时写入文件。

    Args:
        file_path: 输入文件绝对路径（.pdf / .docx）
        output_path: 输出文件路径；留空则不写文件，仅返回内容
        format: 输出格式，"md"（默认）或 "html"
        business_mode: 启用业务文档模式（序号修复 + 空表头推断）
        enable_ocr: 扫描型 PDF 自动 OCR（需安装 PaddleOCR，否则回退文本提取）
        ocr_lang: OCR 语言（ch / en / ch_en）
        page_range: PDF 页码范围 [start, end]，如 [5, 10]；None=全部
        extract_images: 提取图片到 output 同级 images/ 目录
        remove_cjk_spaces: 去除中文间多余空格
        merge_broken_paragraphs: 合并 PDF 换行导致的断裂短行
        fix_headings: 章节标题修复（"总体说明 1.1" -> "1.1 总体说明"）
        merge_cross_page_tables: 跨页表格合并（PDF 专用）
        filter_footer: 页脚过滤（PDF 专用）
        max_content_chars: 返回 content 的最大字符数，超出则截断并标记 truncated（默认 50000，0=不限）

    Returns:
        成功: {"success": True, "content": str, "stats": {...}, "output_path": str, "error": None, "truncated": bool}
        失败: {"success": False, "error": str, "content": None, ...}
        stats 含 page_count / paragraphs / tables / lines / page_errors / ocr_status
        注：output_path 写入的是完整内容，截断仅影响返回的 content 字段
    """
    try:
        if not os.path.exists(file_path):
            return _error_result(f"文件不存在: {file_path}")

        opts = _build_options(
            business_mode=business_mode,
            enable_ocr=enable_ocr,
            ocr_lang=ocr_lang,
            page_range=page_range,
            extract_images=extract_images,
            remove_cjk_spaces=remove_cjk_spaces,
            merge_broken_paragraphs=merge_broken_paragraphs,
            fix_headings=fix_headings,
            merge_cross_page_tables=merge_cross_page_tables,
            filter_footer=filter_footer,
            merge_blank_lines=merge_blank_lines,
            add_front_matter=add_front_matter,
        )

        blocks, _ext, page_count = _parse_blocks(file_path, opts)
        title = os.path.splitext(os.path.basename(file_path))[0]
        # front matter 元数据
        metadata = None
        if opts.add_front_matter:
            from datetime import date
            metadata = {
                "source": os.path.basename(file_path),
                "format": _ext.lstrip(".").upper(),
                "pages": page_count,
                "converted": date.today().isoformat(),
            }
        content = _render_content(blocks, title, format, options=opts, metadata=metadata)

        written_path = ""
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)  # 文件始终写完整内容
            written_path = os.path.abspath(output_path)

        # 截断返回内容，避免大文档撑爆 LLM 上下文（文件已写完整，截断仅影响返回值）
        truncated = False
        returned_content = content
        if max_content_chars > 0 and len(content) > max_content_chars:
            hint = f"\n\n<!-- 内容过长已截断，完整内容共 {len(content)} 字符，见 output_path -->"
            returned_content = content[:max_content_chars] + hint
            truncated = True

        stats = _stats(blocks, content, page_count)
        stats["ocr_status"] = _ocr_status(file_path, opts, _ext)
        return {
            "success": True,
            "content": returned_content,
            "stats": stats,
            "output_path": written_path,
            "truncated": truncated,
            "error": None,
        }
    except (FileNotFoundError, PdfEncryptedError, PdfEmptyError, ValueError) as e:
        return _error_result(str(e))
    except Exception as e:
        return _error_result(f"转换失败: {type(e).__name__}: {e}")


@mcp.tool()
def batch_convert(
    directory: str,
    output_dir: str = "",
    recursive: bool = False,
    format: str = "md",
    name_template: str = "",
    business_mode: bool = False,
    enable_ocr: bool = True,
    ocr_lang: str = "ch",
    page_range: list[int] | None = None,
    extract_images: bool = False,
    remove_cjk_spaces: bool = True,
    merge_broken_paragraphs: bool = True,
    fix_headings: bool = True,
    merge_cross_page_tables: bool = True,
    filter_footer: bool = True,
    merge_blank_lines: bool = True,
    add_front_matter: bool = False,
) -> dict:
    """批量转换目录下所有 PDF/Word 文档为 Markdown（或 HTML）。

    逐个转换目录中的 .pdf / .docx 文件，汇总成功/失败数和每个文件的处理明细。
    输出文件名冲突时自动加 _1 / _2 后缀。

    Args:
        directory: 输入目录
        output_dir: 输出目录；留空则与源文件同目录
        recursive: 是否递归子目录
        format: 输出格式，"md"（默认）或 "html"
        name_template: 输出文件名模板，支持 {name}/{date}/{seq}；留空用源文件名
        business_mode: 启用业务文档模式（序号修复 + 空表头推断）
        enable_ocr: 扫描型 PDF 自动 OCR
        ocr_lang: OCR 语言（ch / en / ch_en）
        page_range: PDF 页码范围 [start, end]；None=全部
        其余后处理开关同 convert_to_markdown

    Returns:
        {"total": int, "success": int, "failed": int, "results": [...], "error": null}
        results 每项: {"file": str, "success": bool, "output_path": str,
                       "stats": {...}, "error": str|null}
        stats 含 page_count / paragraphs / tables / lines / page_errors / ocr_status
    """
    if not os.path.isdir(directory):
        return _error_result(f"目录不存在: {directory}")

    try:
        opts = _build_options(
            business_mode=business_mode,
            enable_ocr=enable_ocr,
            ocr_lang=ocr_lang,
            page_range=page_range,
            extract_images=extract_images,
            remove_cjk_spaces=remove_cjk_spaces,
            merge_broken_paragraphs=merge_broken_paragraphs,
            fix_headings=fix_headings,
            merge_cross_page_tables=merge_cross_page_tables,
            filter_footer=filter_footer,
            merge_blank_lines=merge_blank_lines,
            add_front_matter=add_front_matter,
        )
    except ValueError as e:
        return _error_result(str(e))

    inputs = _collect_files(directory, recursive)
    if not inputs:
        return {"total": 0, "success": 0, "failed": 0, "results": [], "error": None}

    out_ext = ".html" if format == "html" else ".md"
    template = name_template or None
    results: list[dict] = []
    success_count = 0
    failed_count = 0

    for path in inputs:
        item: dict = {"file": path, "success": False, "output_path": "", "error": None}
        try:
            blocks, _ext, page_count = _parse_blocks(path, opts)
            title = os.path.splitext(os.path.basename(path))[0]
            metadata = None
            if opts.add_front_matter:
                from datetime import date
                metadata = {
                    "source": os.path.basename(path),
                    "format": _ext.lstrip(".").upper(),
                    "pages": page_count,
                    "converted": date.today().isoformat(),
                }
            content = _render_content(blocks, title, format, options=opts, metadata=metadata)

            out_path = resolve_unique_output_path(
                output_dir or None, path, ext=out_ext, template=template
            )
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)

            item["success"] = True
            item["output_path"] = os.path.abspath(out_path)
            stats = _stats(blocks, content, page_count)
            stats["ocr_status"] = _ocr_status(path, opts, _ext)
            item["stats"] = stats
            success_count += 1
        except (FileNotFoundError, PdfEncryptedError, PdfEmptyError, ValueError) as e:
            item["error"] = str(e)
            failed_count += 1
        except Exception as e:
            item["error"] = f"{type(e).__name__}: {e}"
            failed_count += 1
        results.append(item)

    return {
        "total": len(inputs),
        "success": success_count,
        "failed": failed_count,
        "results": results,
        "error": None,
    }


@mcp.tool()
def merge_documents(
    file_paths: list[str],
    output_path: str = "",
    title: str = "合并文档",
    business_mode: bool = False,
    enable_ocr: bool = True,
    ocr_lang: str = "ch",
    page_range: list[int] | None = None,
    merge_blank_lines: bool = True,
) -> dict:
    """将多个 PDF/Word 文档合并为单个 Markdown 文件。

    每个文档渲染为一个二级标题(## 文件名)章节,按传入顺序合并。
    适用于多份报告汇总、章节拼接等场景。

    Args:
        file_paths: 输入文件路径列表(.pdf / .docx),按顺序合并
        output_path: 输出文件路径;留空则不写文件,仅返回内容
        title: 合并文档的总标题(默认"合并文档")
        business_mode: 启用业务文档模式
        enable_ocr: 扫描型 PDF 自动 OCR
        ocr_lang: OCR 语言(ch / en / ch_en)
        page_range: PDF 页码范围 [start, end];None=全部
        merge_blank_lines: 压缩连续空行(默认开)

    Returns:
        {"success": bool, "content": str, "stats": {...}, "output_path": str, "error": str|null}
    """
    try:
        if not file_paths:
            return _error_result("file_paths 不能为空")

        opts = _build_options(
            business_mode=business_mode,
            enable_ocr=enable_ocr,
            ocr_lang=ocr_lang,
            page_range=page_range,
            merge_blank_lines=merge_blank_lines,
        )

        documents: list[tuple[str, list[Block]]] = []
        total_page_count = 0
        failed_files: list[str] = []

        for fp in file_paths:
            if not os.path.exists(fp):
                failed_files.append(f"{fp}: 文件不存在")
                continue
            try:
                blocks, _ext, page_count = _parse_blocks(fp, opts)
                doc_title = os.path.splitext(os.path.basename(fp))[0]
                documents.append((doc_title, blocks))
                total_page_count += page_count
            except Exception as e:
                failed_files.append(f"{fp}: {type(e).__name__}: {e}")

        if not documents:
            return _error_result("所有文件均解析失败: " + "; ".join(failed_files))

        content = merge_and_render(documents, title=title, options=opts)

        written_path = ""
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            written_path = os.path.abspath(output_path)

        stats = _stats(
            [b for _, bl in documents for b in bl], content, total_page_count
        )
        if failed_files:
            stats["failed_files"] = failed_files

        return {
            "success": True,
            "content": content,
            "stats": stats,
            "output_path": written_path,
            "merged_count": len(documents),
            "error": None,
        }
    except Exception as e:
        return _error_result(f"合并失败: {type(e).__name__}: {e}")


@mcp.tool()
def get_document_info(file_path: str) -> dict:
    """获取 PDF/Word 文档的基本信息（格式、大小、页数、段落数、是否扫描件）。

    用于在转换前了解文档情况，判断是否需要 OCR、转换耗时等。

    Args:
        file_path: 文档路径（.pdf / .docx）

    Returns:
        PDF: {"format": "PDF", "size_bytes": int, "size": str, "page_count": int|null,
              "is_scanned": bool|null, "avg_words_per_page": float, "error": null}
            （page_count/is_scanned 在读取异常时为 null，avg_words_per_page 仅采样成功时有）
        Word: {"format": "DOCX", "size_bytes": int, "size": str,
               "paragraph_count": int, "table_count": int, "error": null}
        失败: {"success": False, "error": str}
    """
    try:
        if not os.path.exists(file_path):
            return _error_result(f"文件不存在: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        size_bytes = os.path.getsize(file_path)
        info: dict = {
            "format": ext.lstrip(".").upper(),
            "size_bytes": size_bytes,
            "size": _format_size(size_bytes),
        }

        if ext == ".pdf":
            try:
                info["page_count"] = get_page_count(file_path)
            except Exception as e:
                info["page_count"] = None
                info["page_count_error"] = str(e)

            # 文字密度采样判断是否扫描件
            is_scanned = None
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    n = min(5, len(pdf.pages))
                    total = 0
                    for i in range(n):
                        total += len(pdf.pages[i].extract_words())
                    avg = total / n if n else 0
                    is_scanned = avg < 10
                    info["avg_words_per_page"] = round(avg, 1)
            except Exception:
                pass
            info["is_scanned"] = is_scanned

        elif ext == ".docx":
            try:
                from docx import Document
                doc = Document(file_path)
                info["paragraph_count"] = len(doc.paragraphs)
                info["table_count"] = len(doc.tables)
            except Exception as e:
                info["read_error"] = str(e)

        elif ext == ".doc":
            return _error_result("不支持 .doc 格式，请先用 Word 另存为 .docx")

        else:
            return _error_result(f"不支持的文件格式: {ext}")

        info["error"] = None
        return info
    except Exception as e:
        return _error_result(f"读取失败: {type(e).__name__}: {e}")


@mcp.tool()
def summarize_document(
    file_path: str,
    business_mode: bool = False,
    enable_ocr: bool = True,
    ocr_lang: str = "ch",
    page_range: list[int] | None = None,
    max_section_preview: int = 100,
) -> dict:
    """生成文档的结构化摘要（大纲 + 每章预览 + 统计）。

    从文档中提取标题层级和每章首段，生成结构化摘要。不依赖 AI 模型，
    纯文本启发式提取，适用于快速了解文档内容、判断是否需要全文转换。

    Args:
        file_path: 输入文件路径（.pdf / .docx）
        business_mode: 启用业务文档模式
        enable_ocr: 扫描型 PDF 自动 OCR
        ocr_lang: OCR 语言（ch / en / ch_en）
        page_range: PDF 页码范围 [start, end]；None=全部
        max_section_preview: 每个章节预览的最大字符数（默认 100）

    Returns:
        {"success": bool, "title": str, "outline": [...], "stats": {...},
         "ocr_status": str, "error": str|null}
        outline 每项: {"level": int, "heading": str, "preview": str}
    """
    try:
        if not os.path.exists(file_path):
            return _error_result(f"文件不存在: {file_path}")

        opts = _build_options(
            business_mode=business_mode,
            enable_ocr=enable_ocr,
            ocr_lang=ocr_lang,
            page_range=page_range,
        )

        blocks, _ext, page_count = _parse_blocks(file_path, opts)
        title = os.path.splitext(os.path.basename(file_path))[0]
        result = summarize(blocks, title=title, max_section_preview=max_section_preview)
        result["success"] = True
        result["ocr_status"] = _ocr_status(file_path, opts, _ext)
        result["error"] = None
        return result
    except (FileNotFoundError, PdfEncryptedError, PdfEmptyError, ValueError) as e:
        return _error_result(str(e))
    except Exception as e:
        return _error_result(f"摘要生成失败: {type(e).__name__}: {e}")


def main() -> None:
    """启动 MCP server（stdio 传输）。"""
    mcp.run()


if __name__ == "__main__":
    main()
