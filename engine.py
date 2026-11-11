"""PDF 解析引擎

仅负责 PDF 文本与表格的提取（依赖 pdfplumber）。
通用后处理（CJK 空格、序号修复、标题修复、表格合并）见 postprocess.py，
表格数据清洗见 table_utils.py，数据结构见 block.py。
"""

import logging
import os
import re
from collections import Counter

import pdfplumber

from block import Block, PdfEmptyError, PdfEncryptedError
from config import ConvertOptions
from postprocess import (
    _BULLET_PREFIX_RE,
    _HAS_DOT_LEADER_RE,
    _HEADING_NUM_PREFIX_RE,
    _PARAGRAPH_START_RE,
    _SENTENCE_END_RE,
    _apply_font_headings,
    fix_headings,
    fix_list_number_positions,
    merge_broken_paragraphs,
    merge_consecutive_tables,
    remove_cjk_spaces,
    smart_join,
)
from table_utils import process_table_data

FOOTER_MARGIN = 60  # 页面底部忽略区域（点）
# 词级 x_tolerance：默认 3 会把字母间距较紧的英文词错误粘连
# （实测 "isn'talwaystrue" / "separatingthe" 类融合），1.5 可正确切分
_WORD_X_TOLERANCE = 1.5


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

        # 自适应页脚 / 页眉检测：扫描样本页的底部与顶部，识别重复出现的页脚带 / 页眉带
        footer_threshold = _detect_footer_threshold(pdf) if opts.filter_footer else None
        header_threshold = _detect_header_threshold(pdf) if opts.filter_footer else None

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

                # 2. 提取表格外的文字（过滤页脚 / 页眉）
                text_lines = _extract_text_outside_tables(
                    page, table_bboxes, page_height, options, footer_threshold, header_threshold
                )
                for y_top, text, font_size, font_bold in text_lines:
                    if text.strip():
                        page_blocks.append(Block(
                            type="paragraph",
                            y_top=y_top,
                            text=text.strip(),
                            page=page_num,
                            font_size=font_size,
                            font_bold=font_bold,
                        ))

                # 3. 按 y 坐标排序
                page_blocks.sort(key=lambda b: b.y_top)
                all_blocks.extend(page_blocks)

            except Exception as e:
                logging.warning("第%d页解析失败（已降级为占位段落，不影响其他页）: %s", page_num, e, exc_info=True)
                all_blocks.append(Block(
                    type="paragraph", y_top=0, page=page_num,
                    text=f"*[第{page_num}页解析失败: {e}]*"
                ))

    # 合并连续表格 + 合并断裂段落 + 修复标题 + 修复序号位置 + 字号标题检测
    blocks = merge_consecutive_tables(all_blocks, opts)
    blocks = merge_broken_paragraphs(blocks, opts)
    blocks = fix_list_number_positions(blocks, opts)
    blocks = fix_headings(blocks, opts)
    if opts.heading_from_font_size:
        blocks = _apply_font_headings(blocks)
    return blocks


def _detect_footer_threshold(pdf, sample_pages: int = 12) -> float | None:
    """自适应检测页脚带的 y 坐标阈值（绝对坐标）

    扫描采样页底部 100pt 区域的文字行，若某些文字在多页重复出现
    （页码、页脚文字），或行字号明显小于正文主字号 × 0.9（随章节变化的
    页脚文字逐章不同，重复检测会漏掉），则视为页脚行。
    取这些页脚行的最高 y 坐标作为页脚带上界。采样页在全文均匀分布。
    检测失败时返回 None（调用方回退到 page_height - FOOTER_MARGIN）。

    返回值：绝对 y 坐标阈值，y > 该值的行视为页脚。None 表示未检测到。
    """
    total = len(pdf.pages)
    if total < 3:
        return None  # 页数太少，无法可靠检测
    # 全文均匀采样（首中尾），最多 sample_pages 页
    count = min(sample_pages, total)
    step = total / count
    indices = sorted({min(total - 1, int(i * step)) for i in range(count)})
    pages = [pdf.pages[i] for i in indices]

    # 收集每页底部区域的文字行：(y_top, text, size)
    page_bottom_lines: list[list[tuple[float, str, float]]] = []
    for page in pages:
        page_height = page.height
        scan_zone = 100  # 底部 100pt 扫描区
        words = page.extract_words(extra_attrs=["size"], x_tolerance=_WORD_X_TOLERANCE)
        if not words:
            page_bottom_lines.append([])
            continue
        word_lines = _cluster_words_into_lines(words)
        bottom_lines = []
        for line in word_lines:
            y_top = min(w["top"] for w in line)
            if y_top > page_height - scan_zone:
                text = " ".join(w["text"] for w in line).strip()
                size = _line_style(line)[0]
                if text:
                    bottom_lines.append((y_top, text, size))
        page_bottom_lines.append(bottom_lines)

    # 正文主字号：采样页全部行的字号加权众数（页脚行少，不影响众数）
    size_counter: Counter[float] = Counter()
    for bottom_lines in page_bottom_lines:
        for _, text, size in bottom_lines:
            if size > 0:
                size_counter[round(size, 1)] += len(text)
    body_size = size_counter.most_common(1)[0][0] if size_counter else 0.0

    # 统计文字出现次数（归一化：去掉数字，因为页码数字每页不同）
    text_counter: Counter[str] = Counter()
    for bottom_lines in page_bottom_lines:
        for _, text, _size in bottom_lines:
            fingerprint = re.sub(r'\d+', '', text).strip()
            if fingerprint:
                text_counter[fingerprint] += 1

    # 找出在 ≥ 半数页出现的文字（页脚特征）
    threshold_count = max(3, len(pages) // 2)
    footer_fingerprints = {fp for fp, cnt in text_counter.items() if cnt >= threshold_count}

    # 取这些页脚文字的最高 y 坐标作为页脚带上界（留 5pt 余量）
    max_footer_y = 0.0
    found = False
    for bottom_lines in page_bottom_lines:
        for y_top, text, size in bottom_lines:
            fp = re.sub(r'\d+', '', text).strip()
            is_footer = fp in footer_fingerprints
            if not is_footer and body_size > 0 and 0 < size < body_size * 0.9:
                is_footer = True  # 字号小于正文的底部行：随章节变化的页脚
            if is_footer:
                if y_top > max_footer_y:
                    max_footer_y = y_top
                    found = True

    if not found:
        return None

    return max_footer_y - 5


def _detect_header_threshold(pdf, sample_pages: int = 12) -> float | None:
    """自适应检测页眉带的 y 坐标阈值（绝对坐标）

    扫描采样页顶部 100pt 区域，满足任一条件的行视为页眉：
    1. 归一化文字（去数字）在 ≥ 半数采样页重复出现（居中书名等固定页眉）；
    2. 行字号明显小于正文主字号 × 0.9（随章节变化的页眉文字逐章不同，
       重复检测会漏掉，但页眉字号几乎总比正文小）。

    取所有页眉行的最低 y 坐标作为页眉带下界（留 5pt 余量），
    y < 阈值的行视为页眉。采样页在全文均匀分布（页眉文字随章节变化，
    只采前几页会漏检）。未检测到时返回 None。
    """
    from collections import Counter

    total = len(pdf.pages)
    if total < 3:
        return None
    # 全文均匀采样（首中尾），最多 sample_pages 页
    count = min(sample_pages, total)
    step = total / count
    indices = sorted({min(total - 1, int(i * step)) for i in range(count)})
    pages = [pdf.pages[i] for i in indices]

    page_top_lines: list[list[tuple[float, str, float]]] = []  # (y, text, size)
    for page in pages:
        scan_zone = 100  # 顶部 100pt 扫描区
        words = page.extract_words(extra_attrs=["size"], x_tolerance=_WORD_X_TOLERANCE)
        if not words:
            page_top_lines.append([])
            continue
        word_lines = _cluster_words_into_lines(words)
        top_lines = []
        for line in word_lines:
            y_top = min(w["top"] for w in line)
            if y_top < scan_zone:
                text = " ".join(w["text"] for w in line).strip()
                size = _line_style(line)[0]
                if text:
                    top_lines.append((y_top, text, size))
        page_top_lines.append(top_lines)

    # 正文主字号：采样页全部行的字号加权众数（页眉行少，不影响众数）
    size_counter: Counter[float] = Counter()
    for top_lines in page_top_lines:
        for _, text, size in top_lines:
            if size > 0:
                size_counter[round(size, 1)] += len(text)
    body_size = size_counter.most_common(1)[0][0] if size_counter else 0.0

    text_counter: Counter[str] = Counter()
    for top_lines in page_top_lines:
        for _, text, _size in top_lines:
            fingerprint = re.sub(r'\d+', '', text).strip()
            if fingerprint:
                text_counter[fingerprint] += 1

    threshold_count = max(3, len(pages) // 2)
    header_fingerprints = {fp for fp, cnt in text_counter.items() if cnt >= threshold_count}

    min_header_y = float("inf")
    found = False
    for top_lines in page_top_lines:
        for y_top, text, size in top_lines:
            fingerprint = re.sub(r'\d+', '', text).strip()
            is_header = fingerprint in header_fingerprints
            if not is_header and body_size > 0 and 0 < size < body_size * 0.9:
                is_header = True  # 字号小于正文的顶部行：随章节变化的页眉
            if is_header:
                if y_top < min_header_y:
                    min_header_y = y_top
                    found = True

    return min_header_y + 5 if found else None


def _extract_text_outside_tables(
    page,
    table_bboxes: list[tuple],
    page_height: float,
    options: ConvertOptions | None = None,
    footer_threshold: float | None = None,
    header_threshold: float | None = None,
) -> list[tuple[float, str, float, bool]]:
    """提取表格外的文字行，返回 (y_top, text, 行主字号, 是否粗体)"""
    opts = options if options is not None else ConvertOptions.default()
    words = page.extract_words(extra_attrs=["size", "fontname"], x_tolerance=_WORD_X_TOLERANCE)
    if not words:
        full_text = page.extract_text() or ""
        return [(0, full_text, 0.0, False)] if full_text.strip() else []

    lines = _cluster_words_into_lines(words)
    # 收集非表格、非页眉页脚的行（保留 x0 用于缩进判断，字号/粗体用于标题检测）
    page_lines: list[tuple[float, float, str, float, bool]] = []  # (y_top, x0, text, size, bold)
    for line in lines:
        y_top = min(w["top"] for w in line)

        # 过滤页脚区域（页码、页脚文字）
        if opts.filter_footer:
            thresh = footer_threshold if footer_threshold is not None else (page_height - FOOTER_MARGIN)
            if y_top > thresh:
                continue
            # 过滤页眉区域（书名、章节名等重复文字）
            if header_threshold is not None and y_top < header_threshold:
                continue

        in_table = False
        for bbox in table_bboxes:
            if _line_in_bbox(line, bbox):
                in_table = True
                break
        if not in_table:
            raw = " ".join(w["text"] for w in line)
            text = remove_cjk_spaces(raw) if opts.remove_cjk_spaces else raw
            text = _BULLET_PREFIX_RE.sub("- ", text.strip())  # 行首项目符号 → Markdown 列表
            if text:
                x0 = min(w["x0"] for w in line)
                size, bold = _line_style(line)
                page_lines.append((y_top, x0, text, size, bold))

    # 同页内合并续行：首行缩进 + 顶格续行 的段落模式
    if opts.merge_broken_paragraphs:
        page_lines = _merge_indented_continuations(page_lines)

    return [(y, t, size, bold) for y, _x, t, size, bold in page_lines]


def _line_style(line: list[dict]) -> tuple[float, bool]:
    """行的主字号（按字符数加权众数）与粗体标记（粗体字符占比 ≥ 50%）"""
    sizes: Counter[float] = Counter()
    bold_chars = 0
    total = 0
    for w in line:
        text = w.get("text", "")
        n = len(text)
        if not n:
            continue
        total += n
        size = w.get("size")
        if isinstance(size, (int, float)):
            sizes[round(size, 1)] += n
        if "bold" in str(w.get("fontname", "")).lower():
            bold_chars += n
    main_size = sizes.most_common(1)[0][0] if sizes else 0.0
    return main_size, total > 0 and bold_chars >= total * 0.5


def _line_style_conflict(prev_size: float, prev_bold: bool, size: float, bold: bool) -> bool:
    """两行字号差 ≥15% 或粗体不同 → 大概率是标题与正文，不合并"""
    if prev_size > 0 and size > 0:
        hi = max(prev_size, size)
        lo = min(prev_size, size)
        if hi >= lo * 1.15 or prev_bold != bold:
            return True
    return False


def _merge_indented_continuations(
    lines: list[tuple[float, float, str, float, bool]],
) -> list[tuple[float, float, str, float, bool]]:
    """合并同页内首行缩进 + 顶格续行的段落

    典型中文排版：段落首行缩进 2 字符，续行顶格。当 pdfplumber 按物理行
    提取时，一个段落会被拆成多行。此函数把续行合并回首行。

    判断条件（同时满足才合并）：
    1. 上一行不以句末标点结尾（。！？；等）
    2. 当前行不以段落起始标志开头（（N）、N.、第N章、列表符号等）
    3. 上一行不是标题/章节号行，且两行字号/粗体样式一致
    4. 当前行 x0 明显小于上一行（顶格续行 vs 缩进首行），或两行 x0 接近

    保守策略：只在缩进差异明确（≥5pt）或无差异时合并，避免误合并标题。
    """
    if len(lines) < 2:
        return lines
    result: list[tuple[float, float, str, float, bool]] = [lines[0]]
    for y, x0, text, size, bold in lines[1:]:
        prev_y, prev_x0, prev_text, prev_size, prev_bold = result[-1]
        prev_stripped = prev_text.strip()
        curr_stripped = text.strip()

        # 上一行以句末标点结尾 → 不合并
        if _SENTENCE_END_RE.search(prev_stripped):
            result.append((y, x0, text, size, bold))
            continue
        # 目录/索引条目行 → 每行是独立条目，不合并（与跨页守卫同款特征）：
        # 上一行含点导线（. . . . 页码），或两行都以页码数字结尾
        if _HAS_DOT_LEADER_RE.search(prev_stripped) or (
            prev_stripped[-1:].isdigit() and re.search(r"\s\d{1,3}$", curr_stripped)
        ):
            result.append((y, x0, text, size, bold))
            continue
        # 当前行以段落起始标志开头 → 不合并
        if _PARAGRAPH_START_RE.match(curr_stripped):
            result.append((y, x0, text, size, bold))
            continue
        # 上一行是章节号标题（如 "3.1.1 数据查询"）→ 不与下一行合并
        if _HEADING_NUM_PREFIX_RE.match(prev_stripped):
            result.append((y, x0, text, size, bold))
            continue
        # 字号/粗体样式不同（标题 vs 正文）→ 不合并
        if _line_style_conflict(prev_size, prev_bold, size, bold):
            result.append((y, x0, text, size, bold))
            continue
        # 行间距过大（可能是标题/表格间隔）→ 不合并
        if y - prev_y > 25:
            result.append((y, x0, text, size, bold))
            continue

        # 缩进判断：续行通常顶格（x0 小于首行）或与首行对齐
        # 当前行比上一行缩进更多（curr_x0 > prev_x0 + 5）→ 可能是新缩进段落，不合并
        if x0 > prev_x0 + 5:
            result.append((y, x0, text, size, bold))
            continue

        # 合并：续行拼到上一行（按边界字符智能补空格）
        merged_text = smart_join(prev_stripped, curr_stripped)
        result[-1] = (prev_y, prev_x0, merged_text, prev_size, prev_bold)
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
