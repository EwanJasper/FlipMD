"""文档智能摘要模块

从 Block 列表提取结构化摘要：标题层级 + 每章首段 + 表格统计。
不依赖外部 AI 模型，纯文本启发式提取，适用于快速了解文档内容。
"""

from __future__ import annotations

import re

from block import Block

# Markdown 标题正则（## / ### 等，render 后的格式）
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 可能的标题文字（中文技术文档中常见：1.1 / 第一章 / 一、等）
_SECTION_RE = re.compile(r"^(第[一二三四五六七八九十百]+[章节条]|[一二三四五六七八九十]+[、..]|\d+[\.\-]\d+)")


def summarize(
    blocks: list[Block],
    title: str = "",
    max_section_preview: int = 100,
) -> dict:
    """生成文档结构化摘要

    Args:
        blocks: Block 列表（来自 parse / parse_docx）
        title: 文档标题
        max_section_preview: 每个章节预览的最大字符数

    Returns:
        {
            "title": str,
            "outline": [{"level": int, "heading": str, "preview": str}, ...],
            "stats": {"paragraphs": int, "tables": int, "table_rows": int},
        }
    """
    outline: list[dict] = []
    current_heading: dict | None = None
    table_count = 0
    table_rows = 0
    paragraph_count = 0

    for block in blocks:
        if block.type == "table":
            table_count += 1
            table_rows += len(block.rows)
            # 表格也作为当前章节的预览内容
            if current_heading and not current_heading["preview"]:
                headers = " | ".join(block.headers[:4]) if block.headers else ""
                current_heading["preview"] = f"[表格: {headers}...]" if headers else "[表格]"
            continue

        if block.type != "paragraph":
            continue

        text = block.text.strip()
        if not text:
            continue

        paragraph_count += 1

        # 检测标题（render 前的 Block.text 可能含 # 前缀，也可能只是章节号开头的文字）
        m = _HEADING_RE.match(text)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            current_heading = {"level": level, "heading": heading, "preview": ""}
            outline.append(current_heading)
            continue

        # 检测章节号开头的段落（如 "1.1 总体说明" / "第一章 概述"）
        if _SECTION_RE.match(text) and len(text) < 60:
            current_heading = {"level": 2, "heading": text, "preview": ""}
            outline.append(current_heading)
            continue

        # 非标题段落：作为当前章节的预览（取首段）
        if current_heading and not current_heading["preview"]:
            preview = text[:max_section_preview]
            if len(text) > max_section_preview:
                preview += "..."
            current_heading["preview"] = preview

    return {
        "title": title,
        "outline": outline,
        "stats": {
            "paragraphs": paragraph_count,
            "tables": table_count,
            "table_rows": table_rows,
        },
    }
