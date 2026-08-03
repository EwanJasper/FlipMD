"""Word 解析集成测试

注：需要 tests/samples/ 下有 .docx 样本才运行样式/表格测试。
当前阶段 word_engine 尚未做样式提取，此测试文件为后续阶段预留。
"""

import os

import pytest
from lxml import etree

from markdown_writer import render
from word_engine import parse_docx, _extract_table_grid

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


def _make_tbl_xml(rows_xml: str) -> etree._Element:
    """构造 Word 表格 XML 元素，用于测试 _extract_table_grid"""
    template = f"""<w:tbl xmlns:w="{W_NS}">
  <w:tblGrid>
    <w:gridCol w:w="1000"/>
    <w:gridCol w:w="1000"/>
    <w:gridCol w:w="1000"/>
    <w:gridCol w:w="1000"/>
    <w:gridCol w:w="1000"/>
  </w:tblGrid>
  {rows_xml}
</w:tbl>"""
    return etree.fromstring(template)


def _make_tc(text: str, vmerge: str | None = None, grid_span: int | None = None) -> str:
    """构造单个 <w:tc> XML 字符串"""
    tcpr_parts = []
    if vmerge:
        if vmerge == "restart":
            tcpr_parts.append('<w:vMerge w:val="restart"/>')
        else:
            tcpr_parts.append("<w:vMerge/>")
    if grid_span and grid_span > 1:
        tcpr_parts.append(f'<w:gridSpan w:val="{grid_span}"/>')
    tcpr = f"<w:tcPr>{''.join(tcpr_parts)}</w:tcPr>" if tcpr_parts else ""
    return f"""<w:tc>{tcpr}<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"""


class MockTbl:
    """模拟 python-docx 的 Table 对象，只暴露 _element"""
    def __init__(self, element):
        self._element = element


class TestParseDocx:
    def test_nonexistent_file(self):
        """不存在的文件应抛异常"""
        with pytest.raises(Exception):
            parse_docx("nonexistent.docx")

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(SAMPLES_DIR, "table.docx")),
        reason="无 table.docx 样本",
    )
    def test_table_docx(self):
        """含表格的 docx 应能解析出表格 Block"""
        path = os.path.join(SAMPLES_DIR, "table.docx")
        blocks = parse_docx(path)
        tables = [b for b in blocks if b.type == "table"]
        assert len(tables) >= 1
        assert len(tables[0].headers) > 0
        assert len(tables[0].rows) > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(SAMPLES_DIR, "styled.docx")),
        reason="无 styled.docx 样本",
    )
    def test_styled_docx(self):
        """含样式的 docx 应能解析"""
        path = os.path.join(SAMPLES_DIR, "styled.docx")
        blocks = parse_docx(path)
        assert len(blocks) > 0
        # 渲染应不报错
        md = render(blocks, title="Test")
        assert len(md) > 0


class TestExtractTableGrid:
    """_extract_table_grid 单元测试：合并单元格正确处理"""

    def test_vmerge_continue_consumed(self):
        """vMerge restart + continue：续接行的单元格不应错位

        模拟用户报告的表格：
        报文    元素名称          是否必填  说明
        请求头  1.  S-Token      N        令牌
        (合并)  2.  S-Req-Id     Y        请求编号
        """
        rows_xml = f"""<w:tr>
  {_make_tc("请求头", vmerge="restart")}
  {_make_tc("1.")}
  {_make_tc("S-Token")}
  {_make_tc("N")}
  {_make_tc("令牌")}
</w:tr>
<w:tr>
  {_make_tc("", vmerge="continue")}
  {_make_tc("2.")}
  {_make_tc("S-Req-Id")}
  {_make_tc("Y")}
  {_make_tc("请求编号")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(rows_xml))
        grid = _extract_table_grid(tbl)

        # 第一行：请求头 1. S-Token N 令牌
        assert grid[0] == ["请求头", "1.", "S-Token", "N", "令牌"]
        # 第二行：请求头(向下填充) 2. S-Req-Id Y 请求编号
        # 关键断言：S-Req-Id 应在第 3 列，不错位到第 4 列
        # vMerge 续接格用 restart 格的值向下填充
        assert grid[1] == ["请求头", "2.", "S-Req-Id", "Y", "请求编号"]

    def test_vmerge_multiple_continue_rows(self):
        """vMerge 跨多行续接：所有续接行都不错位"""
        row0 = f"""<w:tr>
  {_make_tc("请求头", vmerge="restart")}
  {_make_tc("1.")}
  {_make_tc("S-Token")}
  {_make_tc("N")}
  {_make_tc("令牌")}
</w:tr>"""
        rows_continue = ""
        for i in range(2, 5):
            rows_continue += f"""<w:tr>
  {_make_tc("", vmerge="continue")}
  {_make_tc(f"{i}.")}
  {_make_tc(f"S-Id-{i}")}
  {_make_tc("Y")}
  {_make_tc(f"项{i}")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(row0 + rows_continue))
        grid = _extract_table_grid(tbl)

        assert grid[0] == ["请求头", "1.", "S-Token", "N", "令牌"]
        for i, row in enumerate(grid[1:], start=2):
            # vMerge 续接格用 restart 格的值向下填充
            assert row == ["请求头", f"{i}.", f"S-Id-{i}", "Y", f"项{i}"]

    def test_no_vmerge_normal_table(self):
        """无合并的普通表格不回归"""
        rows_xml = f"""<w:tr>
  {_make_tc("A")}
  {_make_tc("B")}
  {_make_tc("C")}
</w:tr>
<w:tr>
  {_make_tc("1")}
  {_make_tc("2")}
  {_make_tc("3")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(rows_xml))
        grid = _extract_table_grid(tbl)
        assert grid[0] == ["A", "B", "C"]
        assert grid[1] == ["1", "2", "3"]

    def test_gridspan_horizontal_merge(self):
        """gridSpan 横向合并：左上角取值，其余填空"""
        rows_xml = f"""<w:tr>
  {_make_tc("合并头", grid_span=2)}
  {_make_tc("C")}
</w:tr>
<w:tr>
  {_make_tc("1")}
  {_make_tc("2")}
  {_make_tc("3")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(rows_xml))
        grid = _extract_table_grid(tbl)
        assert grid[0] == ["合并头", "", "C"]
        assert grid[1] == ["1", "2", "3"]

    def test_vmerge_with_gridspan(self):
        """vMerge + gridSpan 组合：多列纵向合并"""
        rows_xml = f"""<w:tr>
  {_make_tc("合并区", vmerge="restart", grid_span=2)}
  {_make_tc("C")}
  {_make_tc("D")}
</w:tr>
<w:tr>
  {_make_tc("", vmerge="continue", grid_span=2)}
  {_make_tc("c2")}
  {_make_tc("d2")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(rows_xml))
        grid = _extract_table_grid(tbl)
        assert grid[0] == ["合并区", "", "C", "D"]
        # vMerge 续接格用 restart 格的值向下填充
        # col_idx=0 -> "合并区"，col_idx=1 -> ""（restart 注册的空值）
        assert grid[1] == ["合并区", "", "c2", "d2"]

    def test_two_independent_vmerges(self):
        """两列各自独立 vMerge"""
        rows_xml = f"""<w:tr>
  {_make_tc("A1", vmerge="restart")}
  {_make_tc("B1", vmerge="restart")}
  {_make_tc("C1")}
</w:tr>
<w:tr>
  {_make_tc("", vmerge="continue")}
  {_make_tc("", vmerge="continue")}
  {_make_tc("C2")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(rows_xml))
        grid = _extract_table_grid(tbl)
        assert grid[0] == ["A1", "B1", "C1"]
        # vMerge 续接格用 restart 格的值向下填充
        assert grid[1] == ["A1", "B1", "C2"]

    def test_vmerge_ends_then_normal_cell(self):
        """vMerge 结束后，普通单元格不应被 pending 值填充

        模拟用户报告的表格：
        序号  校验对象    描述
        1     开始日志    描述1
        2     结束日志    描述2
        3     (合并)      描述3
        4     (合并)      描述4
        5     回退日志    描述5   ← vMerge 已结束，应为"回退日志"而非"结束日志"
        """
        rows_xml = f"""<w:tr>
  {_make_tc("1")}
  {_make_tc("开始日志")}
  {_make_tc("描述1")}
</w:tr>
<w:tr>
  {_make_tc("2")}
  {_make_tc("结束日志", vmerge="restart")}
  {_make_tc("描述2")}
</w:tr>
<w:tr>
  {_make_tc("3")}
  {_make_tc("", vmerge="continue")}
  {_make_tc("描述3")}
</w:tr>
<w:tr>
  {_make_tc("4")}
  {_make_tc("", vmerge="continue")}
  {_make_tc("描述4")}
</w:tr>
<w:tr>
  {_make_tc("5")}
  {_make_tc("回退日志")}
  {_make_tc("描述5")}
</w:tr>"""
        tbl = MockTbl(_make_tbl_xml(rows_xml))
        grid = _extract_table_grid(tbl)

        assert grid[0] == ["1", "开始日志", "描述1"]
        assert grid[1] == ["2", "结束日志", "描述2"]
        assert grid[2] == ["3", "结束日志", "描述3"]
        assert grid[3] == ["4", "结束日志", "描述4"]
        # 关键：vMerge 已结束，第 5 行应为"回退日志"，不是"结束日志"
        assert grid[4] == ["5", "回退日志", "描述5"]
