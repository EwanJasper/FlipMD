"""Word (.docx) 转 Block 解析器

复用 block.Block 数据结构和 postprocess 通用后处理逻辑，产出与 PDF 解析器
相同契约的 Block 列表，由 markdown_writer.render() 统一渲染。

支持的核心样式（写入 paragraph Block 的 text，不新增 Block.type）：
- Heading 1-6 → # ~ ###### 前缀
- List Bullet → - 前缀
- List Number → 1. 前缀（从 numPr 推断序号，退化为顺序编号）
- Bold run → **text**
- Italic run → *text*
- Strike run → ~~text~~
- Hyperlink → [text](url)
"""


from docx import Document
from docx.oxml.ns import qn

from block import Block
from config import ConvertOptions
from postprocess import (
    fix_headings,
    fix_list_number_positions,
    merge_broken_paragraphs,
    merge_consecutive_tables,
)
from table_utils import process_table_data


def parse_docx(path: str, options: ConvertOptions | None = None) -> list[Block]:
    """解析 .docx 文件，返回按文档顺序排列的 Block 列表"""
    doc = Document(path)
    blocks: list[Block] = []
    order = 0  # 递增序号代替 y_top，保持文档顺序

    body = doc.element.body
    para_idx = 0
    tbl_idx = 0
    list_counter = 0  # 有序列表序号

    for child in body.iterchildren():
        if child.tag == qn('w:p'):
            if para_idx >= len(doc.paragraphs):
                break
            para = doc.paragraphs[para_idx]
            para_idx += 1
            text = _render_paragraph(para, list_counter, doc)
            if text.strip():
                # 判断是否有序列表项以维护序号
                if _is_numbered_list(para):
                    list_counter += 1
                elif _is_bullet_list(para):
                    pass  # 无序列表不递增
                else:
                    list_counter = 0  # 非列表项，重置序号
                blocks.append(Block(type="paragraph", y_top=order, text=text))
                order += 1
        elif child.tag == qn('w:tbl'):
            if tbl_idx >= len(doc.tables):
                break
            tbl = doc.tables[tbl_idx]
            tbl_idx += 1
            data = _extract_table_grid(tbl)
            headers, rows = process_table_data(data, options)
            if headers and rows:
                blocks.append(Block(
                    type="table", y_top=order,
                    headers=headers, rows=rows,
                ))
                order += 1

    # 复用通用后处理（与 PDF 无关）
    blocks = merge_consecutive_tables(blocks, options)
    blocks = merge_broken_paragraphs(blocks, options)
    blocks = fix_list_number_positions(blocks, options)
    blocks = fix_headings(blocks, options)
    return blocks


# ── 段落样式渲染 ──────────────────────────────────────────────────

HEADING_LEVEL_MAP = {
    "Heading 1": 1, "Heading 2": 2, "Heading 3": 3,
    "Heading 4": 4, "Heading 5": 5, "Heading 6": 6,
    "标题 1": 1, "标题 2": 2, "标题 3": 3,
    "标题 4": 4, "标题 5": 5, "标题 6": 6,
}


def _render_paragraph(para, list_counter: int, doc=None) -> str:
    """渲染段落为 Markdown 文本（含样式前缀与行内格式）"""
    style_name = para.style.name if para.style else ""

    # 行内格式（加粗/斜体/删除线/超链接）
    inline = _render_inline(para, doc)

    # 标题样式
    level = HEADING_LEVEL_MAP.get(style_name)
    if level:
        return f"{'#' * level} {inline}"

    # 列表样式
    if _is_bullet_list(para):
        return f"- {inline}"
    if _is_numbered_list(para):
        return f"{list_counter + 1}. {inline}"

    return inline


def _render_inline(para, doc=None) -> str:
    """渲染段落的行内内容：run 的加粗/斜体/删除线 + 超链接"""
    parts: list[str] = []
    # 遍历段落 XML 子元素，按顺序处理 run (w:r) 和 hyperlink (w:hyperlink)
    for child in para._element:
        if child.tag == qn('w:r'):
            parts.append(_render_run(child))
        elif child.tag == qn('w:hyperlink'):
            parts.append(_render_hyperlink(child, doc))
    text = "".join(parts)
    return text


def _render_run(r_element) -> str:
    """渲染单个 run 元素，应用加粗/斜体/删除线"""
    # 提取文本（含 w:t 和 w:br）
    texts: list[str] = []
    for t in r_element.iter():
        if t.tag == qn('w:t'):
            texts.append(t.text or "")
        elif t.tag == qn('w:br') or t.tag == qn('w:cr'):
            texts.append("\n")
        elif t.tag == qn('w:tab'):
            texts.append("\t")
    text = "".join(texts)
    if not text:
        return ""

    # 读取格式属性
    rpr = r_element.find(qn('w:rPr'))
    bold = italic = strike = False
    if rpr is not None:
        if rpr.find(qn('w:b')) is not None:
            bold = True
        if rpr.find(qn('w:i')) is not None:
            italic = True
        if rpr.find(qn('w:strike')) is not None:
            strike = True

    # 应用 Markdown 包裹（避免对空格/换行包裹）
    if strike:
        text = f"~~{text}~~"
    if bold:
        text = f"**{text}**"
    if italic:
        text = f"*{text}*"
    return text


def _render_hyperlink(hl_element, doc=None) -> str:
    """渲染超链接元素为 [text](url)"""
    # 提取文本
    texts: list[str] = []
    for r in hl_element.iter(qn('w:r')):
        texts.append(_render_run(r))
    text = "".join(texts)

    # 提取 URL（r:id 属性 → doc.part.rels 解析为真实 URL）
    rid = hl_element.get(qn('r:id'))
    url = ""
    if rid and doc is not None:
        try:
            rel = doc.part.rels.get(rid)
            if rel is not None:
                url = rel.target_ref or ""
        except Exception:
            url = ""
    if url:
        return f"[{text}]({url})"
    return text


def _is_bullet_list(para) -> bool:
    """判断是否为无序列表项"""
    style_name = para.style.name if para.style else ""
    if "List Bullet" in style_name or "项目符号" in style_name:
        return True
    # 检查 numPr 且 numFmt 为 bullet
    ppr = para._element.find(qn('w:pPr'))
    if ppr is not None:
        numpr = ppr.find(qn('w:numPr'))
        if numpr is not None:
            numfmt = numpr.find(qn('w:numFmt'))
            if numfmt is not None and numfmt.get(qn('w:val')) == 'bullet':
                return True
    return False


def _is_numbered_list(para) -> bool:
    """判断是否为有序列表项"""
    style_name = para.style.name if para.style else ""
    if "List Number" in style_name or "编号" in style_name:
        return True
    ppr = para._element.find(qn('w:pPr'))
    if ppr is not None:
        numpr = ppr.find(qn('w:numPr'))
        if numpr is not None:
            numfmt = numpr.find(qn('w:numFmt'))
            if numfmt is not None and numfmt.get(qn('w:val')) in ('decimal', 'chineseCounting'):
                return True
    return False


# ── 表格网格提取（正确处理合并单元格）──────────────────────────────

def _extract_table_grid(tbl) -> list[list[str]]:
    """提取表格为二维网格，正确处理合并单元格

    python-docx 的 row.cells 对合并单元格会重复填充同一值，导致列数虚增。
    此方法通过遍历 XML 的 tr/tc，结合 gridSpan/vMerge 构建真实网格：
    - 横向合并（gridSpan）：左上角取值，其余位置填空
    - 纵向合并（vMerge）：起始格取值，续接格填空
    """
    grid: list[list[str]] = []
    # 纵向合并追踪：列索引 -> restart 格的值
    vmerge_pending: dict[int, str] = {}

    for tr in tbl._element.iter(qn('w:tr')):
        row: list[str] = []
        col_idx = 0
        # findall 只取直接子元素，避免递归进入嵌套表格的单元格
        tc_list = list(tr.findall(qn('w:tc')))
        tc_iter = iter(tc_list)

        while col_idx < _table_grid_cols(tbl) or tc_iter:
            try:
                tc = next(tc_iter)
            except StopIteration:
                break

            # 读取 gridSpan（横向合并）+ vMerge（纵向合并）
            tcpr = tc.find(qn('w:tcPr'))
            grid_span = 1
            vmerge_state = "none"  # "none" | "restart" | "continue"
            if tcpr is not None:
                gs = tcpr.find(qn('w:gridSpan'))
                if gs is not None:
                    try:
                        grid_span = int(gs.get(qn('w:val'), '1'))
                    except ValueError:
                        grid_span = 1
                vm = tcpr.find(qn('w:vMerge'))
                if vm is not None:
                    val = vm.get(qn('w:val'))
                    vmerge_state = "restart" if val == "restart" else "continue"

            # 读取单元格文本
            cell_text = _tc_text(tc)

            if vmerge_state == "restart":
                # 纵向合并起始：记录值供续接格向下填充
                # 若带 gridSpan，所有覆盖的列都注册为 vMerge pending
                for i in range(grid_span):
                    vmerge_pending[col_idx + i] = cell_text if i == 0 else ""
                row.append(cell_text)
                # 横向合并空位
                for _ in range(grid_span - 1):
                    row.append("")
                col_idx += grid_span
            elif vmerge_state == "continue":
                # vMerge 续接格：用 restart 格的值向下填充
                for i in range(grid_span):
                    row.append(vmerge_pending.get(col_idx + i, ""))
                col_idx += grid_span
            else:
                # 普通单元格：清除该列的 vMerge pending（合并已结束）
                for i in range(grid_span):
                    vmerge_pending.pop(col_idx + i, None)
                row.append(cell_text)
                # 横向合并空位
                for _ in range(grid_span - 1):
                    row.append("")
                col_idx += grid_span

        if row:
            grid.append(row)

    # 退路：若 XML 解析失败，回退到 row.cells
    if not grid:
        return [[cell.text for cell in row.cells] for row in tbl.rows]
    return grid


def _table_grid_cols(tbl) -> int:
    """获取表格的网格列数（tblGrid 的 gridCol 数量）"""
    tbl_grid = tbl._element.find(qn('w:tblGrid'))
    if tbl_grid is not None:
        return len(list(tbl_grid.iter(qn('w:gridCol'))))
    # 退路：取第一行的 cell 数
    first_row = tbl._element.find(qn('w:tr'))
    if first_row is not None:
        return len(list(first_row.iter(qn('w:tc'))))
    return 0


def _tc_text(tc_element) -> str:
    """提取 tc 元素的纯文本"""
    texts: list[str] = []
    for t in tc_element.iter(qn('w:t')):
        texts.append(t.text or "")
    return "".join(texts)
