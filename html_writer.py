"""HTML 渲染器

复用 Block 数据结构，输出带基础样式的 HTML。
与 markdown_writer.render 平行，由 CLI 的 --format html 调用（留接口）。
"""

from __future__ import annotations

import html as _html

from block import Block


def render_html(blocks: list[Block], title: str = "") -> str:
    """将 Block 列表渲染为完整 HTML 文档字符串"""
    body_parts: list[str] = []

    if title:
        body_parts.append(f"<h1>{_escape(title)}</h1>")

    prev_was_table = False
    for block in blocks:
        if block.type == "paragraph":
            text = block.text.strip()
            if not text:
                continue
            if prev_was_table:
                body_parts.append("")  # 空行占位（HTML 中无影响，保持可读性）
            body_parts.append(f"<p>{_render_inline_html(text)}</p>")
            prev_was_table = False
        elif block.type == "table":
            body_parts.append(_render_table_html(block))
            prev_was_table = True
        elif block.type == "image":
            body_parts.append(
                f'<p><img src="{_escape_attr(block.image_path)}" alt=""></p>'
            )
            prev_was_table = False

    body = "\n".join(body_parts)

    return _HTML_TEMPLATE.format(
        title=_escape(title or "Document"),
        body=body,
    )


def _render_table_html(block: Block) -> str:
    if not block.headers and not block.rows:
        return ""
    lines = ['<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">']
    # 表头
    lines.append("<thead><tr>")
    for h in block.headers:
        lines.append(f"<th>{_escape(h)}</th>")
    lines.append("</tr></thead>")
    # 数据行
    lines.append("<tbody>")
    for row in block.rows:
        lines.append("<tr>")
        padded = list(row) + [""] * (len(block.headers) - len(row))
        for i in range(len(block.headers)):
            lines.append(f"<td>{_escape(padded[i])}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _render_inline_html(text: str) -> str:
    """渲染行内 Markdown 语法为 HTML（加粗/斜体/删除线/链接/代码）"""
    import re
    # 先 escape，再用占位符替换避免二次处理
    text = _escape(text)
    # 代码（``）— 先处理避免被其他规则误伤
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # 加粗
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    # 斜体
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    # 删除线
    text = re.sub(r'~~([^~]+)~~', r'<del>\1</del>', text)
    # 链接 [text](url) — URL 需过滤危险 scheme 防 XSS（javascript:/data: 等）
    text = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        lambda m: f'<a href="{_escape_attr(_safe_url(m.group(2)))}">{m.group(1)}</a>',
        text,
    )
    return text


def _safe_url(url: str) -> str:
    """过滤 URL scheme，仅允许白名单协议与相对路径，防 XSS

    允许：http(s):/mailto:/ftp:/tel:/相对路径(./../)/锚点(#)/纯文件名
    拒绝：javascript:/data:/vbscript:/file: 等
    """
    u = url.strip()
    if not u:
        return ""
    # 相对路径或锚点直接放行
    if u[0] in ("/#.") or ":" not in u.split("/", 1)[0]:
        return u
    scheme = u.split(":", 1)[0].lower()
    if scheme in ("http", "https", "mailto", "ftp", "tel"):
        return u
    return ""


def _escape(s: str) -> str:
    return _html.escape(s, quote=False)


def _escape_attr(s: str) -> str:
    return _html.escape(s, quote=True)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: "Microsoft YaHei UI", sans-serif; max-width: 900px; margin: 2em auto;
          padding: 0 1em; line-height: 1.6; color: #1e293b; }}
  h1 {{ color: #7c3aed; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.3em; }}
  h2, h3 {{ color: #6d28d9; }}
  table {{ border-collapse: collapse; margin: 1em 0; }}
  th {{ background: #f1f5f9; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 6px 12px; }}
  code {{ background: #f1f5f9; padding: 2px 4px; border-radius: 3px;
          font-family: "Cascadia Code", monospace; }}
  img {{ max-width: 100%; }}
  a {{ color: #7c3aed; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
