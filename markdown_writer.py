from block import Block


def render(blocks: list[Block], title: str = "") -> str:
    """将 Block 对象列表渲染为 Markdown 字符串"""
    lines = []

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

    return "\n".join(lines).strip()


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
