"""表格数据处理工具

从 PDF / Word 提取的原始二维表格数据，经此模块清洗为 (headers, rows)：
- 表头/数据行分离
- 多级表头扁平化
- 空表头推断（通用启发式，受 options.infer_empty_headers 控制）
- 空列压缩
- 换行清理

空表头推断规则（通用，不硬编码特定关键词）：
- 列中所有非空值相同（含单行表）→ 用该值作表头
- 否则留空
"""

import re

from block import Block  # noqa: F401  (Block 供外部调用方参考签名)
from config import ConvertOptions
from postprocess import remove_cjk_spaces

CODE_PATTERN = re.compile(r'[A-Za-z]{2}\d{3,}')


def _opts(options: ConvertOptions | None) -> ConvertOptions:
    return options if options is not None else ConvertOptions.default()


def process_table_data(
    data: list[list],
    options: ConvertOptions | None = None,
) -> tuple[list[str], list[list[str]]]:
    """处理表格数据：扁平化多级表头、压缩空列、清理换行

    Args:
        data: pdfplumber / python-docx 提取的原始二维列表（含表头行）
        options: 转换选项，options.infer_empty_headers=False 时不做业务表头推断

    Returns:
        (headers, rows) — 扁平化表头列表与数据行列表
    """
    opts = _opts(options)
    if not data:
        return [], []

    def is_header_row(row: list[str]) -> bool:
        texts = [str(c or "").replace("\n", " ").strip() for c in row]
        non_empty = [t for t in texts if t]
        if not non_empty:
            return True
        for t in non_empty:
            if CODE_PATTERN.match(t):
                return False
        # 含纯数字单元格（编号、年龄等）的行是数据行，不是表头
        # 表头单元格几乎都是文字标签，不会是纯数字
        if any(t.isdigit() for t in non_empty):
            return False
        if len(non_empty) >= 3:
            avg = sum(len(t) for t in non_empty) / len(non_empty)
            return avg <= 5
        return True

    data_start = 0
    for ri, row in enumerate(data):
        if is_header_row(row):
            data_start = ri + 1
        else:
            break

    # 全文字表格可能没有数字、业务代码等数据行信号。将所有行当成
    # 表头会令调用方因 rows 为空而丢掉整张表；此时保留首个非空行
    # 作为表头，其余行作为数据，优先保全内容及行列关系。
    if data_start == len(data) and len(data) > 1:
        first_content = next(
            (i for i, row in enumerate(data) if any(str(cell or "").strip() for cell in row)),
            None,
        )
        if first_content is not None:
            data_start = first_content + 1

    header_rows = data[:data_start]
    data_rows = data[data_start:]

    if not data_rows:
        col_count = max(len(r) for r in header_rows) if header_rows else 0
        col_has = [False] * col_count
        for row in header_rows:
            for ci in range(min(len(row), col_count)):
                if row[ci] and str(row[ci]).strip():
                    col_has[ci] = True
        keep = [i for i, h in enumerate(col_has) if h]
        trimmed = []
        for row in header_rows:
            trimmed.append([str(row[i] or "") if i < len(row) else "" for i in keep])

        def clean(s: str) -> str:
            return s.replace("\n", "")

        flat = []
        for ci in range(len(trimmed[0])):
            parts = [clean(trimmed[ri][ci]).strip() for ri in range(len(trimmed))]
            flat.append(" ".join(p for p in parts if p))
        return flat, []

    # 列保留条件：表头行或数据行任一非空则保留
    # （仅看数据行会丢弃「有表头无数据」的错位列，导致合并单元格表头无法对齐）
    col_count = max(
        max((len(r) for r in data_rows), default=0),
        max((len(r) for r in header_rows), default=0),
    )
    col_has = [False] * col_count
    for row in list(header_rows) + list(data_rows):
        for ci in range(min(len(row), col_count)):
            if row[ci] and str(row[ci]).strip():
                col_has[ci] = True
    keep = [i for i in range(col_count) if col_has[i]]
    if not keep:
        return [], []

    trimmed_rows = []
    for row in data_rows:
        trimmed_rows.append([str(row[i] or "") if i < len(row) else "" for i in keep])

    trimmed_headers = []
    for row in header_rows:
        trimmed_headers.append([str(row[i] or "") if i < len(row) else "" for i in keep])

    def clean_cell(s: str) -> str:
        return remove_cjk_spaces(s.replace("\n", " "))

    # 扁平化表头：纯多行表头拼接（不做数据推断，空列保持空）
    flat_headers = []
    for ci in range(len(keep)):
        parts = []
        for ri in range(len(trimmed_headers)):
            val = clean_cell(trimmed_headers[ri][ci]).strip()
            if val:
                parts.append(val)
        flat_headers.append(" ".join(parts))

    rows = [[clean_cell(c) for c in row] for row in trimmed_rows]

    # 列对齐修复：PDF 合并单元格表头常与数据列错位
    flat_headers = _align_headers_to_data(flat_headers, rows)

    # 空表头推断（受 infer_empty_headers 控制，通用启发式）
    if opts.infer_empty_headers:
        for ci in range(len(flat_headers)):
            if flat_headers[ci].strip():
                continue
            data_vals = [r[ci] for r in rows if ci < len(r) and r[ci].strip()]
            if data_vals:
                unique_vals = set(v.strip() for v in data_vals)
                if len(unique_vals) == 1:
                    # 列中所有值相同（含单行表）→ 用该值作表头
                    flat_headers[ci] = list(unique_vals)[0]

    # 去除全空列
    final_headers: list[str] = []
    final_rows: list[list[str]] = [[] for _ in range(len(rows))]
    for ci in range(len(flat_headers)):
        h = flat_headers[ci]
        if h.strip():
            final_headers.append(h)
            for ri in range(len(rows)):
                final_rows[ri].append(rows[ri][ci])
        else:
            has_data = any(rows[ri][ci].strip() for ri in range(len(rows)))
            if has_data:
                final_headers.append(h)
                for ri in range(len(rows)):
                    final_rows[ri].append(rows[ri][ci])

    return final_headers, final_rows


def _align_headers_to_data(headers: list[str], rows: list[list[str]]) -> list[str]:
    """修复 PDF 合并单元格导致的表头/数据列错位

    PDF 多行表头的合并单元格文字 anchor 在合并区域左上角列，而数据落在合并
    区域内的另一列，产生相邻的「有表头无数据」列与「有数据无表头」列。此
    函数把表头从前者移到相邻的后者，使表头与数据对齐。

    通用启发式，不依赖特定关键词或 cell bbox。
    """
    if not headers or not rows:
        return headers
    n = len(headers)
    new_headers = list(headers)
    has_header = [bool(h.strip()) for h in headers]
    has_data = [
        any(ci < len(row) and str(row[ci]).strip() for row in rows)
        for ci in range(n)
    ]

    for ci in range(n):
        if has_header[ci] and not has_data[ci]:
            # 纯表头列：优先左邻、其次右邻的纯数据列
            # （合并单元格文字 anchor 在左上角，表头列多在数据列右侧，故优先左移）
            target = None
            if ci - 1 >= 0 and has_data[ci - 1] and not has_header[ci - 1]:
                target = ci - 1
            elif ci + 1 < n and has_data[ci + 1] and not has_header[ci + 1]:
                target = ci + 1
            if target is not None:
                moved = new_headers[ci].strip()
                existing = new_headers[target].strip()
                new_headers[target] = f"{moved} {existing}".strip() if existing else moved
                new_headers[ci] = ""
                has_header[ci] = False
                has_header[target] = True
    return new_headers
