"""Read original documents independently of converted Markdown."""

from __future__ import annotations

import base64
import html
import io
import threading
from pathlib import Path

import pdfplumber
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

# PDFium (also used by the existing OCR path) is not thread safe.
PDF_LOCK = threading.RLock()
RASTER_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}


def data_url(blob, mime):
    return f"data:{mime};base64," + base64.b64encode(blob).decode("ascii")


def pdf_page(path: Path, page: int):
    with PDF_LOCK, pdfplumber.open(path) as pdf:
        if not 1 <= page <= len(pdf.pages):
            raise ValueError("页码超出 PDF 范围。")
        original = pdf.pages[page - 1]
        resolution = min(150, 1600 * 72 / max(original.width, original.height))
        picture = original.to_image(resolution=resolution, antialias=True).original
        output = io.BytesIO()
        picture.save(output, format="PNG")
        return {
            "kind": "PDF",
            "page": page,
            "total": len(pdf.pages),
            "data_url": data_url(output.getvalue(), "image/png"),
        }


def docx_html(path: Path):
    document = Document(path)

    def paragraph(para):
        # XML text order preserves hyperlink text without opening its target.
        chunks = []
        for node in para._p.iter():
            if node.tag == qn("w:t"):
                chunks.append(html.escape(node.text or ""))
            elif node.tag in (qn("w:br"), qn("w:cr")):
                chunks.append("<br>")
            elif node.tag == qn("w:tab"):
                chunks.append("&emsp;")
            elif node.tag == qn("a:blip"):
                relationship = document.part.rels.get(node.get(qn("r:embed")))
                if relationship is not None and not relationship.is_external:
                    part = relationship.target_part
                    if part.content_type in RASTER_TYPES:
                        chunks.append(f'<img alt="文档图片" src="{data_url(part.blob, part.content_type)}">')
        style = para.style.name if para.style else ""
        tag = "p"
        if style.startswith(("Heading ", "标题 ")) and style[-1:] in "123456":
            tag = "h" + style[-1]
        prefix = "• " if "List Bullet" in style else ""
        return f"<{tag}>{prefix}{''.join(chunks) or '<br>'}</{tag}>"

    def table(tbl):
        rows = []
        for row in tbl.rows:
            cells = []
            for cell in row.cells:
                cells.append("<td>" + "".join(paragraph(p) for p in cell.paragraphs) + "</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return "<table><tbody>" + "".join(rows) + "</tbody></table>"

    parts = []
    for node in document.element.body:
        if node.tag == qn("w:p"):
            parts.append(paragraph(Paragraph(node, document)))
        elif node.tag == qn("w:tbl"):
            parts.append(table(Table(node, document)))
    return {"kind": "DOCX", "html": "".join(parts), "note": "源文件内容预览 · 不还原 Word 分页、字体及复杂版式"}


def markdown_html(markdown: str, images=None):
    from markdown_it import MarkdownIt

    renderer = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    images = images or {}

    def image(tokens, index, options, env):
        token = tokens[index]
        ref = token.attrGet("src")
        source = images.get(ref)
        if not source:
            return '<span class="image-note">[图片未缓存]</span>'
        return f'<img src="{html.escape(source, quote=True)}" alt="{html.escape(token.content, quote=True)}">'

    # Display document links without allowing a document to navigate the privileged app.
    renderer.renderer.rules["image"] = image
    renderer.renderer.rules["link_open"] = lambda *args: '<span class="document-link">'
    renderer.renderer.rules["link_close"] = lambda *args: "</span>"
    return renderer.render(markdown)
