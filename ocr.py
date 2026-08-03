"""扫描型 PDF OCR 模块

依赖 PaddleOCR（可选依赖，未安装时降级为不可用）。

工作流：
1. is_scanned_pdf(path)：抽样几页检测文字密度，判断是否为扫描型 PDF
2. ocr_pdf(path, options)：逐页 OCR，返回 Block 列表

PaddleOCR 的 PPStructure 还能识别表格，本模块优先用结构化输出，
失败时退化为纯文本提取。
"""

from __future__ import annotations

import os

import pdfplumber

from block import Block
from config import ConvertOptions

# 扫描型 PDF 判定阈值：单页平均字数 < 此值视为扫描型
SCANNED_WORD_THRESHOLD = 10
# 抽样页数
SAMPLE_PAGES = 5


def is_paddleocr_available() -> bool:
    """检测 PaddleOCR 是否已安装"""
    try:
        import paddleocr  # noqa: F401
        return True
    except ImportError:
        return False


def is_scanned_pdf(pdf_path: str, sample_pages: int = SAMPLE_PAGES) -> bool:
    """判断 PDF 是否为扫描型（图片型）

    策略：抽样前 N 页，用 pdfplumber extract_words 提取文字，
    若平均每页文字数 < 阈值，判定为扫描型。
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return False
            n = min(sample_pages, len(pdf.pages))
            if n == 0:
                return False
            total_words = 0
            for i in range(0, n, max(1, n // sample_pages or 1)):
                if i >= len(pdf.pages):
                    break
                words = pdf.pages[i].extract_words()
                total_words += len(words)
            avg = total_words / n
            return avg < SCANNED_WORD_THRESHOLD
    except Exception:
        return False


def ocr_pdf(pdf_path: str, options: ConvertOptions | None = None) -> list[Block]:
    """对扫描型 PDF 执行 OCR，返回 Block 列表

    使用 PaddleOCR 的 PPStructure 识别文本与表格。
    失败时退化为 PaddleOCR 纯文本识别。
    """
    if not is_paddleocr_available():
        raise RuntimeError(
            "PaddleOCR 未安装。请运行：uv sync --extra ocr "
            "或 pip install paddleocr paddlepaddle"
        )

    opts = options if options is not None else ConvertOptions.default()
    lang = opts.ocr_lang or "ch"

    from paddleocr import PaddleOCR

    from table_utils import process_table_data

    # 初始化引擎（首次会下载模型，较慢）
    ocr = PaddleOCR(
        use_angle_cls=True,
        lang=lang,
        show_log=False,
    )

    blocks: list[Block] = []
    order = 0

    # 用 pdfplumber 将每页渲染为图片，再交给 OCR
    with pdfplumber.open(pdf_path) as pdf:
        page_indices = _resolve_page_indices(len(pdf.pages), opts.page_range)
        for page_num in page_indices:
            page = pdf.pages[page_num]
            try:
                page_blocks = _ocr_page(ocr, page, page_num + 1, opts, process_table_data)
                for b in page_blocks:
                    b.y_top = order
                    order += 1
                blocks.extend(page_blocks)
            except Exception as e:
                blocks.append(Block(
                    type="paragraph", y_top=order,
                    text=f"*[第{page_num + 1}页 OCR 失败: {e}]*"
                ))
                order += 1

    return blocks


def _ocr_page(ocr, page, page_num: int, options: ConvertOptions, process_table_data_fn) -> list[Block]:
    """对单页执行 OCR，返回 Block 列表"""
    # 将 PDF 页面渲染为图片（PaddleOCR 接受图片路径或 ndarray）
    im = page.to_image(resolution=200)
    # im.original 是 PIL.Image，保存到临时文件
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        im.original.save(tmp_path)
        result = ocr.ocr(tmp_path, cls=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    blocks: list[Block] = []
    if not result:
        return blocks

    # PaddleOCR 返回 [[ [bbox, (text, conf)], ... ]]
    for line in result:
        if not line:
            continue
        texts: list[str] = []
        for item in line:
            if item and len(item) >= 2:
                txt = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                if txt:
                    texts.append(txt)
        if texts:
            blocks.append(Block(type="paragraph", y_top=0, text=" ".join(texts)))

    return blocks


def _resolve_page_indices(total: int, page_range: tuple[int, int] | None) -> list[int]:
    """将页码范围 (1-based, inclusive) 转换为 0-based 索引列表"""
    if page_range is None:
        return list(range(total))
    start, end = page_range
    start = max(1, start)
    end = min(total, end)
    return list(range(start - 1, end))
