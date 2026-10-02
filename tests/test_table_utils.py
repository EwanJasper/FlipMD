"""表格处理单元测试

注意：process_table_data 的 is_header_row 启发式为真实多行表格设计。
判断数据行的关键信号是单元格含业务代码（[A-Za-z]{2}\\d{3,}）或长文本。
无法区分表头与数据的全文字表格退回首行表头，保留其余行。
含数字或业务代码的表格仍使用原有多行表头识别。
"""

from config import ConvertOptions
from table_utils import process_table_data

# 特定模式（启用空表头推断）
BUSINESS = ConvertOptions.business()
# 默认保守（禁用空表头推断）
DEFAULT = ConvertOptions.default()


def _with_code_rows(headers, data_rows):
    """构造含代码数据行的表格，确保 is_header_row 正确识别数据行"""
    return [headers] + data_rows


class TestProcessTableData:
    def test_all_text_table_preserves_data_rows(self):
        data = [["项目", "状态"], ["原文内容", "保留"], ["任务历史", "本地保存"]]
        headers, rows = process_table_data(data, DEFAULT)
        assert headers == data[0]
        assert rows == data[1:]

    def test_blank_table_remains_empty(self):
        assert process_table_data([["", None], [None, ""]], DEFAULT) == ([], [])

    def test_table_with_code_rows(self):
        """含业务代码数据行的表格：表头 + 数据行"""
        data = _with_code_rows(
            ["序号", "表代码", "说明"],
            [["1", "TB099", "删除操作"], ["2", "TC097", "新增操作"], ["3", "TD010", "修改操作"]],
        )
        headers, rows = process_table_data(data, DEFAULT)
        assert headers == ["序号", "表代码", "说明"]
        assert len(rows) == 3
        assert rows[0] == ["1", "TB099", "删除操作"]

    def test_empty_column_compressed(self):
        """全空列应被压缩（含代码数据行）"""
        data = _with_code_rows(
            ["序号", "", "表代码"],
            [["1", "", "TB099"], ["2", "", "TC097"], ["3", "", "TD010"]],
        )
        headers, rows = process_table_data(data, DEFAULT)
        assert "序号" in headers
        assert "表代码" in headers
        assert len(headers) == 2
        assert len(rows) == 3

    def test_multiline_header_flattened(self):
        """多行表头应扁平化为单行"""
        data = [
            ["基础信息", "基础信息", "扩展"],
            ["序号", "表代码", "备注"],
            ["1", "TB099", "无"],
            ["2", "TC097", "无"],
        ]
        headers, rows = process_table_data(data, DEFAULT)
        assert headers[0] == "基础信息 序号"
        assert headers[1] == "基础信息 表代码"
        assert headers[2] == "扩展 备注"
        assert len(rows) == 2

    def test_infer_header_disabled_by_default(self):
        """默认模式下不做空表头推断"""
        data = _with_code_rows(
            ["表代码", ""],
            [["TB099", "操作表名称"], ["TC097", "操作表名称"]],
        )
        headers, rows = process_table_data(data, DEFAULT)
        assert headers[1] == ""

    def test_infer_header_single_row_uses_value(self):
        """单行表空表头 → 用该值作表头（通用启发式）"""
        data = _with_code_rows(
            ["表代码", ""],
            [["TB099", "操作表名称"]],
        )
        headers, rows = process_table_data(data, BUSINESS)
        assert headers[1] == "操作表名称"

    def test_infer_header_multi_row_same_value(self):
        """多行表全列同值 → 用该值作表头（通用启发式）"""
        data = _with_code_rows(
            ["表代码", ""],
            [["TB099", "操作表名称"], ["TC097", "操作表名称"]],
        )
        headers, rows = process_table_data(data, BUSINESS)
        assert headers[1] == "操作表名称"

    def test_infer_header_multi_row_distinct_values_empty(self):
        """多行表列有不同值 → 留空（无法通用推断）"""
        data = _with_code_rows(
            ["表代码", ""],
            [["TB099", "新增"], ["TC097", "修改"], ["TD010", "删除"]],
        )
        headers, rows = process_table_data(data, BUSINESS)
        assert headers[1] == ""

    def test_infer_header_yes_no_mixed_empty(self):
        """是/否混合值 → 留空（不再硬编码为「是否必须」）"""
        data = _with_code_rows(
            ["表代码", ""],
            [["TB099", "是"], ["TC097", "否"], ["TD010", "是"]],
        )
        headers, rows = process_table_data(data, BUSINESS)
        assert headers[1] == ""

    def test_infer_header_business_codes_mixed_empty(self):
        """不同业务代码 → 留空（不再硬编码为「关联表编号」）"""
        data = _with_code_rows(
            ["序号", ""],
            [["1", "TB099"], ["2", "TC097"], ["3", "TD010"]],
        )
        headers, rows = process_table_data(data, BUSINESS)
        assert headers[1] == ""

    def test_align_merged_cell_header_to_data_column(self):
        """PDF 合并单元格表头与数据列错位时，表头应移到数据列

        模拟真实场景：表头文字「关联表 编号」所在列无数据，相邻列有数据 TB099，
        表头应移到 TB099 列。
        """
        data = [
            ["序号", "", "关联表", "", "说明"],
            [None, None, "编号", None, None],
            ["1", "TB099", None, None, "测试"],
            ["2", "TC097", None, None, "示例"],
        ]
        headers, rows = process_table_data(data, BUSINESS)
        # 「关联表 编号」应移到 TB099 所在列，原表头列被压缩
        assert "关联表 编号" in headers
        assert "TB099" not in headers  # TB099 是数据，不应作表头
        assert headers[0] == "序号"
        assert "说明" in headers

    def test_align_multirow_header_all_columns(self):
        """完整多行表头错位场景（模拟复杂表格）"""
        data = [
            ["编号", "名称", "说明", "", "操作类别", None, None, None, None, None, None, None, ""],
            [None, None, None, "", "关联表", "", "关联表名称", "", "关联表", "", "", "是否", ""],
            [None, None, None, None, "编号", None, None, None, "操作", None, None, "必须", None],
            ["TB027", "核定", "说明", "TB01", None, None, "记录明细", "新增", None, None, "是", None, None],
        ]
        headers, rows = process_table_data(data, BUSINESS)
        assert headers == [
            "编号", "名称", "说明",
            "操作类别 关联表 编号", "关联表名称", "关联表 操作", "是否 必须",
        ]
        assert rows[0] == ["TB027", "核定", "说明", "TB01", "记录明细", "新增", "是"]

    def test_empty_data(self):
        assert process_table_data([], DEFAULT) == ([], [])

    def test_newline_in_cell_cleaned(self):
        """单元格内的换行应被清理（含代码数据行）"""
        data = _with_code_rows(
            ["表代码", "说明"],
            [["TB099", "测试A"], ["TC097", "测试B\n内容"], ["TD010", "测试C"]],
        )
        headers, rows = process_table_data(data, DEFAULT)
        assert len(rows) == 3
        assert all("\n" not in cell for row in rows for cell in row)
