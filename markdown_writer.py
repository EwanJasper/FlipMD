from __future__ import annotations

import re

from block import Block
from config import ConvertOptions

# 连续 2+ 空行压缩为 1 个
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def render(
    blocks: list[Block],
    title: str = "",
    options: ConvertOptions | None = None,
    metadata: dict | None = None,
) -> str:
    """将 Block 对象列表渲染为 Markdown 字符串

    Args:
        blocks: Block 列表
        title: 文档标题，非空时生成 # title
        options: 转换选项，控制 merge_blank_lines / add_front_matter（None 用默认）
        metadata: front matter 元数据（source/pages/converted 等），仅当
                  options.add_front_matter=True 时生效
    """
    opts = options if options is not None else ConvertOptions()
    lines: list[str] = []

    # YAML front matter 元数据头
    if opts.add_front_matter and metadata:
        lines.append("---")
        for key, val in metadata.items():
            lines.append(f"{key}: {val}")
        lines.append("---")
        lines.append("")

    if title:
        lines.append(f"# {title}")
        lines.append("")

    prev_was_table = False
    for block in blocks:
        if block.type == "paragraph":
            text = block.text.strip()
            if not text:
                continue
            # 段落与表格之间空行分隔
            if prev_was_table:
                lines.append("")
            lines.append(text)
            prev_was_table = False
        elif block.type == "table":
            # 表格前后空行分隔
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(_render_table(block))
            prev_was_table = True
        elif block.type == "image":
            # 图片前后空行分隔
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"![]({block.image_path})")
            lines.append("")
            prev_was_table = False

    content = "\n".join(lines).strip()

    # 压缩连续空行：3+ 换行（即 2+ 空行）压缩为 2 换行（1 空行）
    if opts.merge_blank_lines:
        content = _BLANK_LINES_RE.sub("\n\n", content)

    return content


def _render_table(block: Block) -> list[str]:
    """将 Table Block 渲染为 GFM 表格语法"""
    if not block.headers and not block.rows:
        return []

    def escape(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", "")

    result = []

    # 表头
    header_line = "| " + " | ".join(escape(h) for h in block.headers) + " |"
    result.append(header_line)

    # 分隔行
    separator = "| " + " | ".join("---" for _ in block.headers) + " |"
    result.append(separator)

    # 数据行
    for row in block.rows:
        padded = list(row) + [""] * (len(block.headers) - len(row))
        data_line = "| " + " | ".join(escape(padded[i]) for i in range(len(block.headers))) + " |"
        result.append(data_line)

    return result
