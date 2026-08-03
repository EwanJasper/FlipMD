"""PDF 解析引擎

仅负责 PDF 文本与表格的提取（依赖 pdfplumber）。
通用后处理（CJK 空格、序号修复、标题修复、表格合并）见 postprocess.py，
表格数据清洗见 table_utils.py，数据结构见 block.py。
"""

import logging
import os
import re

import pdfplumber

from block import Block, PdfEmptyError, PdfEncryptedError
from config import ConvertOptions
from postprocess import (
    fix_headings,
    fix_list_number_positions,
    merge_broken_paragraphs,
    merge_consecutive_tables,
    remove_cjk_spaces,
)
from table_utils import process_table_data

FOOTER_MARGIN = 60  # 页面底部忽略区域（点）


def get_page_count(pdf_path: str) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def parse(pdf_path: str, options: ConvertOptions | None = None) -> list[Block]:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"文件不存在: {pdf_path}")

    opts = options if options is not None else ConvertOptions.default()

    # 扫描型 PDF 自动 OCR
    if opts.enable_ocr:
        try:
            from ocr import is_paddleocr_available, is_scanned_pdf, ocr_pdf
            if is_scanned_pdf(pdf_path):
                # 扫描型 PDF：需 OCR
                if is_paddleocr_available():
                    blocks = ocr_pdf(pdf_path, opts)
                    # OCR 结果仍走通用后处理
                    blocks = merge_broken_paragraphs(blocks, opts)
                    blocks = fix_list_number_positions(blocks, opts)
                    blocks = fix_headings(blocks, opts)
                    return blocks
                else:
                    logging.warning(
                        "检测到扫描型 PDF，但 PaddleOCR 未安装，将回退到文本提取（内容可能不完整）。"
                        "请运行：uv sync --extra ocr 或 pip install paddleocr paddlepaddle"
                    )
        except Exception as e:
            # OCR 失败时回退到普通文本提取（记录日志便于排障）
            logging.warning("OCR 处理失败，回退到普通文本提取: %s", e, exc_info=True)

    all_blocks: list[Block] = []

    try:
        pdf_file = pdfplumber.open(pdf_path)
    except Exception as e:
        if "encrypt" in str(e).lower() or "password" in str(e).lower():
            raise PdfEncryptedError("PDF 文件已加密，暂不支持加密 PDF") from e
        raise

    with pdf_file as pdf:
        if len(pdf.pages) == 0:
            raise PdfEmptyError("PDF 文件为空")

        # 自适应页脚检测：扫描所有页底部，识别重复出现的页脚带
        footer_threshold = _detect_footer_threshold(pdf) if opts.filter_footer else None

        # 页码范围过滤（1-based 闭区间 [start, end]）
        total_pages = len(pdf.pages)
        if opts.page_range is not None:
            pr_start, pr_end = opts.page_range
            # 钳制到有效范围，避免越界
            pr_start = max(1, min(pr_start, total_pages))
            pr_end = max(pr_start, min(pr_end, total_pages))
            page_slice = pdf.pages[pr_start - 1:pr_end]
        else:
            pr_start, pr_end = 1, total_pages
            page_slice = pdf.pages

        for page_num, page in enumerate(page_slice, start=pr_start):
            try:
                page_blocks: list[Block] = []
                page_height = page.height

                # 1. 检测表格
                table_bboxes = []
                raw_tables = page.find_tables()

                for tbl in raw_tables:
                    bbox = tbl.bbox
                    table_bboxes.append(bbox)

                    data = tbl.extract()
                    if not data or len(data) < 1:
                        continue

                    col_count = max(len(r) for r in data)
                    if col_count <= 1 and len(data) <= 2:
                        continue

                    headers, rows = process_table_data(data, options)
                    if headers and rows:
                        page_blocks.append(Block(
                            type="table",
                            y_top=bbox[1],
                            headers=headers,
                            rows=rows,
                        ))

                # 2. 提取表格外的文字（过滤页脚）
                text_lines = _extract_text_outside_tables(
                    page, table_bboxes, page_height, options, footer_threshold
                )
                for y_top, text in text_lines:
                    if text.strip():
                        page_blocks.append(Block(
                            type="paragraph",
                            y_top=y_top,
                            text=text.strip(),
                        ))

                # 3. 按 y 坐标排序
                page_blocks.sort(key=lambda b: b.y_top)
                all_blocks.extend(page_blocks)

            except Exception as e:
                logging.warning("第%d页解析失败（已降级为占位段落，不影响其他页）: %s", page_num, e, exc_info=True)
                all_blocks.append(Block(
                    type="paragraph", y_top=0,
                    text=f"*[第{page_num}页解析失败: {e}]*"
                ))

    # 合并连续表格 + 合并断裂段落 + 修复标题 + 修复序号位置
    blocks = merge_consecutive_tables(all_blocks, opts)
    blocks = merge_broken_paragraphs(blocks, opts)
    blocks = fix_list_number_positions(blocks, opts)
    blocks = fix_headings(blocks, opts)
    return blocks


def _detect_footer_threshold(pdf, sample_pages: int = 10) -> float | None:
    """自适应检测页脚带的 y 坐标阈值（绝对坐标）

    扫描前 sample_pages 页底部 100pt 区域的文字行，若某些文字在多页重复出现
    （页码、页脚文字），则取这些重复文字的最高 y 坐标作为页脚带上界。
    检测失败时返回 None（调用方回退到 page_height - FOOTER_MARGIN）。

    返回值：绝对 y 坐标阈值，y > 该值的行视为页脚。None 表示未检测到。
    """
    from collections import Counter

    pages = pdf.pages[:sample_pages] if len(pdf.pages) >= 3 else pdf.pages
    if len(pages) < 3:
        return None  # 页数太少，无法可靠检测

    # 收集每页底部区域的文字行：(y_top, text)
    page_bottom_lines: list[list[tuple[float, str]]] = []
    for page in pages:
        page_height = page.height
        scan_zone = 100  # 底部 100pt 扫描区
        words = page.extract_words()
        if not words:
            page_bottom_lines.append([])
            continue
        word_lines = _cluster_words_into_lines(words)
        bottom_lines = []
        for line in word_lines:
            y_top = min(w["top"] for w in line)
            if y_top > page_height - scan_zone:
                text = " ".join(w["text"] for w in line).strip()
                if text:
                    bottom_lines.append((y_top, text))
        page_bottom_lines.append(bottom_lines)

    # 统计文字出现次数（归一化：去掉数字，因为页码数字每页不同）
    text_counter: Counter[str] = Counter()
    for bottom_lines in page_bottom_lines:
        for _, text in bottom_lines:
            fingerprint = re.sub(r'\d+', '', text).strip()
            if fingerprint:
                text_counter[fingerprint] += 1

    # 找出在 ≥ 半数页出现的文字（页脚特征）
    threshold_count = max(3, len(pages) // 2)
    footer_fingerprints = {fp for fp, cnt in text_counter.items() if cnt >= threshold_count}

    if not footer_fingerprints:
        return None  # 未检测到重复页脚

    # 取这些页脚文字的最高 y 坐标作为页脚带上界（留 5pt 余量）
    max_footer_y = 0.0
    found = False
    for bottom_lines in page_bottom_lines:
        for y_top, text in bottom_lines:
            fp = re.sub(r'\d+', '', text).strip()
            if fp in footer_fingerprints:
                if y_top > max_footer_y:
                    max_footer_y = y_top
                    found = True

    if not found:
        return None

    return max_footer_y - 5


def _extract_text_outside_tables(
    page,
    table_bboxes: list[tuple],
    page_height: float,
    options: ConvertOptions | None = None,
    footer_threshold: float | None = None,
) -> list[tuple[float, str]]:
    opts = options if options is not None else ConvertOptions.default()
    words = page.extract_words()
    if not words:
        full_text = page.extract_text() or ""
        return [(0, full_text)] if full_text.strip() else []

    lines = _cluster_words_into_lines(words)
    # 收集非表格、非页脚的行（保留 x0 用于缩进判断）
    page_lines: list[tuple[float, float, str]] = []  # (y_top, x0, text)
    for line in lines:
        y_top = min(w["top"] for w in line)

        # 过滤页脚区域（页码、页脚文字）
        if opts.filter_footer:
            thresh = footer_threshold if footer_threshold is not None else (page_height - FOOTER_MARGIN)
            if y_top > thresh:
                continue

        in_table = False
        for bbox in table_bboxes:
            if _line_in_bbox(line, bbox):
                in_table = True
                break
        if not in_table:
            raw = " ".join(w["text"] for w in line)
            text = remove_cjk_spaces(raw) if opts.remove_cjk_spaces else raw
            text = text.strip()
            if text:
                x0 = min(w["x0"] for w in line)
                page_lines.append((y_top, x0, text))

    # 同页内合并续行：首行缩进 + 顶格续行 的段落模式
    if opts.merge_broken_paragraphs:
        page_lines = _merge_indented_continuations(page_lines)

    return [(y, t) for y, _x, t in page_lines]


# 句末标点：行以这些结尾时不与下一行合并
_SENTENCE_END_RE = re.compile(r'[。！？；;…」』\)\)]$')
# 段落起始标志：行以这些开头时不与上一行合并
_PARAGRAPH_START_RE = re.compile(
    r'^（\d+[)）]|^\d+[.、]\s|^第\d+章|^【|^序号|^说明[:：]|^注[:：]|^#{1,6}\s|^\d+\.\d+'
)
# 章节号标题前缀（如 "3.1.1 数据查询"）— 作为上一行时不与下一行合并
_HEADING_NUM_PREFIX_RE = re.compile(r'^\d+(?:\.\d+)+\s')


def _merge_indented_continuations(
    lines: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    """合并同页内首行缩进 + 顶格续行的段落

    典型中文排版：段落首行缩进 2 字符，续行顶格。当 pdfplumber 按物理行
    提取时，一个段落会被拆成多行。此函数把续行合并回首行。

    判断条件（同时满足才合并）：
    1. 上一行不以句末标点结尾（。！？；等）
    2. 当前行不以段落起始标志开头（（N）、N.、第N章等）
    3. 当前行 x0 明显小于上一行（顶格续行 vs 缩进首行），或两行 x0 接近

    保守策略：只在缩进差异明确（≥5pt）或无差异时合并，避免误合并标题。
    """
    if len(lines) < 2:
        return lines
    result: list[tuple[float, float, str]] = [lines[0]]
    for y, x0, text in lines[1:]:
        prev_y, prev_x0, prev_text = result[-1]
        prev_stripped = prev_text.strip()
        curr_stripped = text.strip()

        # 上一行以句末标点结尾 → 不合并
        if _SENTENCE_END_RE.search(prev_stripped):
            result.append((y, x0, text))
            continue
        # 当前行以段落起始标志开头 → 不合并
        if _PARAGRAPH_START_RE.match(curr_stripped):
            result.append((y, x0, text))
            continue
        # 上一行是章节号标题（如 "3.1.1 数据查询"）→ 不与下一行合并
        if _HEADING_NUM_PREFIX_RE.match(prev_stripped):
            result.append((y, x0, text))
            continue
        # 行间距过大（可能是标题/表格间隔）→ 不合并
        if y - prev_y > 25:
            result.append((y, x0, text))
            continue

        # 缩进判断：续行通常顶格（x0 小于首行）或与首行对齐
        # 当前行比上一行缩进更多（curr_x0 > prev_x0 + 5）→ 可能是新缩进段落，不合并
        if x0 > prev_x0 + 5:
            result.append((y, x0, text))
            continue

        # 合并：续行拼到上一行
        merged_text = prev_stripped + curr_stripped
        result[-1] = (prev_y, prev_x0, merged_text)
    return result


def _cluster_words_into_lines(words: list[dict]) -> list[list[dict]]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    current_line = [sorted_words[0]]
    for w in sorted_words[1:]:
        if abs(w["top"] - current_line[-1]["top"]) < 3:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
    if current_line:
        lines.append(current_line)
    # 同一行内的词可能因 baseline 微小差异（如中文与西文/数字 top 差 <1pt）
    # 被 (top, x0) 排序打散，聚类后需按 x0 重排恢复阅读顺序
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def _line_in_bbox(line: list[dict], bbox: tuple) -> bool:
    x0, y0, x1, y1 = bbox
    line_top = min(w["top"] for w in line)
    line_bottom = max(w["bottom"] for w in line)
    line_x0 = min(w["x0"] for w in line)
    line_x1 = max(w["x1"] for w in line)
    overlap_y = max(0, min(line_bottom, y1) - max(line_top, y0))
    overlap_x = max(0, min(line_x1, x1) - max(line_x0, x0))
    return overlap_y > 0 and overlap_x > 0
