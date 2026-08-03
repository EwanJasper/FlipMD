"""后处理规则单元测试

覆盖 README 效果对比表中的黄金用例，防止重构破坏现有行为。
"""

from block import Block
from config import ConvertOptions
from postprocess import (
    fix_headings,
    fix_list_number_positions,
    headers_match,
    merge_broken_paragraphs,
    merge_consecutive_tables,
    remove_cjk_spaces,
)

# 特定模式选项（启用所有特定规则，匹配黄金样本行为）
BUSINESS = ConvertOptions.business()
# 默认保守选项（业务规则关闭）
DEFAULT = ConvertOptions.default()


# ── remove_cjk_spaces ────────────────────────────────────────────

class TestRemoveCjkSpaces:
    def test_half_width_space(self):
        assert remove_cjk_spaces("单位公 共基础 信息采 集") == "单位公共基础信息采集"

    def test_full_width_space(self):
        assert remove_cjk_spaces("单位公\u3000共基础") == "单位公共基础"

    def test_keep_space_between_cjk_and_ascii(self):
        # 中文与英文/数字之间的空格应保留
        assert remove_cjk_spaces("使用 PDF 工具") == "使用 PDF 工具"

    def test_no_change_for_pure_ascii(self):
        assert remove_cjk_spaces("hello world") == "hello world"


# ── merge_broken_paragraphs ──────────────────────────────────────

class TestMergeBrokenParagraphs:
    def test_drop_pure_number(self):
        """单独的数字行（页码）应被丢弃"""
        blocks = [
            Block(type="paragraph", text="正文内容"),
            Block(type="paragraph", text="123"),
            Block(type="paragraph", text="下一段"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2
        assert result[0].text == "正文内容"
        assert result[1].text == "下一段"

    def test_drop_roman_numeral(self):
        """罗马数字页码应被丢弃"""
        blocks = [
            Block(type="paragraph", text="IV"),
            Block(type="paragraph", text="正文"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 1
        assert result[0].text == "正文"

    def test_drop_dotted_line(self):
        """目录点线应被丢弃"""
        blocks = [
            Block(type="paragraph", text="......"),
            Block(type="paragraph", text="正文"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 1

    def test_merge_short_line_after_number_dot(self):
        """前一段以 数字. 结尾时，短行（≤6字）应合并"""
        blocks = [
            Block(type="paragraph", text="...信 1."),
            Block(type="paragraph", text="息记录。"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 1
        assert "1." in result[0].text

    def test_table_block_passthrough(self):
        """表格块应原样保留"""
        tbl = Block(type="table", headers=["a", "b"], rows=[["1", "2"]])
        result = merge_broken_paragraphs([tbl], BUSINESS)
        assert len(result) == 1
        assert result[0].type == "table"

    def test_cross_page_continuation_merged(self):
        """跨页续行：上一段不以句末标点结尾、当前段非段落起始 → 合并"""
        blocks = [
            Block(type="paragraph", text="如原记录明细TB01 的状态标志为01-正常，则"),
            Block(type="paragraph", text="新增变更记录写02-变更；"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 1
        assert "则" in result[0].text
        assert "新增变更记录" in result[0].text

    def test_cross_page_continuation_sentence_end_not_merged(self):
        """上一段以句末标点结尾 → 不合并"""
        blocks = [
            Block(type="paragraph", text="这是一段足够长的正文内容用于测试句末标点。"),
            Block(type="paragraph", text="下一段也是足够长的正文内容用于测试。"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2

    def test_cross_page_continuation_paragraph_start_not_merged(self):
        """当前段以段落起始标志开头 → 不合并"""
        blocks = [
            Block(type="paragraph", text="这是一段足够长的正文内容用于测试续行"),
            Block(type="paragraph", text="（1）新的列表项开始了一段新的内容"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2

    def test_cross_page_continuation_heading_num_not_merged(self):
        """上一段是章节号标题（如 3.1.1 xxx）→ 不与下一行合并"""
        blocks = [
            Block(type="paragraph", text="3.1.1 数据查询"),
            Block(type="paragraph", text="数据应查询TB01表的记录"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2
        assert result[0].text == "3.1.1 数据查询"

    def test_cross_page_continuation_short_text_not_merged(self):
        """短文本（<10 字符）不参与跨页合并，避免误合并标题/短句"""
        blocks = [
            Block(type="paragraph", text="短文本"),
            Block(type="paragraph", text="另一短文本"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2


# ── fix_list_number_positions ────────────────────────────────────
# 用 README 效果对比表的 5 个黄金用例

class TestFixListNumberPositions:
    def _fix(self, text: str) -> str:
        blocks = [Block(type="paragraph", text=text)]
        result = fix_list_number_positions(blocks, BUSINESS)
        return result[0].text

    def test_case1_number_between_cjk_removed(self):
        """信 1.息记录。 → 信息记录。"""
        assert self._fix("信 1.息记录。") == "信息记录。"

    def test_case2_action_table_code(self):
        """删除表。 1. TB01 → 1. 删除TB01表。"""
        assert self._fix("删除表。 1. TB01") == "1. 删除TB01表。"

    def test_case3_content_code_after_punct(self):
        """更新TC02 表...的信息。 1. TC02 → 1. 更新TC02 表...的信息"""
        result = self._fix("更新TC02 表...的信息。 1. TC02")
        assert result.startswith("1. ")
        assert "更新TC02" in result
        assert "TC02" in result

    def test_case4_content_code_no_punct(self):
        """新增TB02表...单位修改 2. TB02 → 2. 新增TB02表...单位修改"""
        result = self._fix("新增TB02表...单位修改 2. TB02")
        assert result.startswith("2. ")
        assert "新增TB02表" in result

    def test_case5_sentence_end_number(self):
        """句子。 N. → N. 句子（标点被规则 5 移除并前置序号）"""
        result = self._fix("更新TB03表记录。 9.")
        assert result == "9. 更新TB03表记录"

    def test_case6_cjk_end_number(self):
        """中文 N. → N. 中文"""
        result = self._fix("参 12.")
        assert result == "12. 参"

    def test_normal_text_unchanged(self):
        """普通文本不应被修改"""
        assert self._fix("这是一段普通文字。") == "这是一段普通文字。"

    def test_table_block_unchanged(self):
        """表格块不应被修改"""
        tbl = Block(type="table", headers=["a"], rows=[["1"]])
        result = fix_list_number_positions([tbl], BUSINESS)
        assert result[0].type == "table"

    def test_disabled_when_not_business(self):
        """非特定模式下不执行序号修复"""
        blocks = [Block(type="paragraph", text="删除表。 1. TB099")]
        result = fix_list_number_positions(blocks, DEFAULT)
        assert result[0].text == "删除表。 1. TB099"


# ── fix_headings ─────────────────────────────────────────────────

class TestFixHeadings:
    def _fix(self, text: str) -> str:
        blocks = [Block(type="paragraph", text=text)]
        result = fix_headings(blocks, BUSINESS)
        return result[0].text

    def test_section_heading_swap_and_prefix(self):
        """总体说明 1.1 → ## 1.1 总体说明（位置调换 + H2 前缀）"""
        assert self._fix("总体说明 1.1") == "## 1.1 总体说明"

    def test_multilevel_heading_h3(self):
        """总体说明 1.1.2 → ### 1.1.2 总体说明（H3）"""
        assert self._fix("总体说明 1.1.2") == "### 1.1.2 总体说明"

    def test_five_level_heading(self):
        """操作数据库表处理逻辑说明 2.1.1.1.2 → ##### 2.1.1.1.2 ...（H5）"""
        result = self._fix("操作数据库表处理逻辑说明 2.1.1.1.2")
        assert result == "##### 2.1.1.1.2 操作数据库表处理逻辑说明"

    def test_six_level_heading(self):
        """6 级章节号 → H6"""
        result = self._fix("标题 1.1.1.1.1.1")
        assert result == "###### 1.1.1.1.1.1 标题"

    def test_num_first_format(self):
        """章节号在前的格式：1.1 总体说明 → ## 1.1 总体说明"""
        assert self._fix("1.1 总体说明") == "## 1.1 总体说明"

    def test_five_level_num_first(self):
        """2.1.1.1.2 标题 → ##### 2.1.1.1.2 标题（用户场景）"""
        assert self._fix("2.1.1.1.2 操作数据库表处理逻辑说明") == (
            "##### 2.1.1.1.2 操作数据库表处理逻辑说明"
        )

    def test_normal_text_unchanged(self):
        """不含数字.数字结尾的文本不变"""
        assert self._fix("这是普通段落") == "这是普通段落"

    def test_single_number_not_heading(self):
        """单独 1. 或 1 不识别为标题（避免与列表序号冲突）"""
        assert self._fix("1. 第一项") == "1. 第一项"
        assert self._fix("1 第一项") == "1 第一项"

    def test_long_title_not_heading(self):
        """过长标题（>60 字符）不识别，避免误判正文"""
        long_text = "1.1 " + "章节内容" * 20
        assert self._fix(long_text) == long_text

    def test_title_with_period_not_heading(self):
        """标题文字含句号（段落特征）不识别"""
        assert self._fix("1.1 这是正文。继续内容") == "1.1 这是正文。继续内容"

    def test_title_with_bad_tail_not_heading(self):
        """标题以 。?！; 结尾不识别"""
        assert self._fix("1.1 标题。") == "1.1 标题。"
        assert self._fix("1.1 标题?") == "1.1 标题?"

    def test_seven_level_not_heading(self):
        """7 级章节号超出 Markdown 上限（H6），不添加前缀"""
        text = "1.1.1.1.1.1.1 标题"
        assert self._fix(text) == text

    def test_table_block_unchanged(self):
        """表格块不应被修改"""
        tbl = Block(type="table", headers=["a"], rows=[["1"]])
        result = fix_headings([tbl], BUSINESS)
        assert result[0].type == "table"

    def test_disabled_when_not_business(self):
        """fix_headings 不依赖 business_mode，默认选项下仍执行"""
        # fix_headings 是通用规则，不受 business_mode 控制
        result = fix_headings([Block(type="paragraph", text="1.1 标题")], DEFAULT)
        assert result[0].text == "## 1.1 标题"

    def test_disabled_when_fix_headings_off(self):
        """fix_headings=False 时不执行"""
        opts = ConvertOptions(fix_headings=False)
        result = fix_headings([Block(type="paragraph", text="1.1 标题")], opts)
        assert result[0].text == "1.1 标题"


# ── headers_match / merge_consecutive_tables ─────────────────────

class TestMergeConsecutiveTables:
    def test_headers_match_exact(self):
        assert headers_match(["序号", "名称"], ["序号", "名称"])

    def test_headers_match_case_insensitive(self):
        assert headers_match(["ID", "Name"], ["id", "name"])

    def test_headers_match_with_spaces(self):
        """表头含空格时按原样比较（空格不忽略）"""
        assert not headers_match(["序 号", "名称"], ["序号", "名称"])
        assert headers_match(["序 号", "名称"], ["序 号", "名称"])

    def test_headers_not_match(self):
        assert not headers_match(["序号"], ["名称"])

    def test_merge_same_headers(self):
        """相同表头的连续表格应合并"""
        t1 = Block(type="table", y_top=0, headers=["A", "B"], rows=[["1", "2"]])
        t2 = Block(type="table", y_top=10, headers=["A", "B"], rows=[["3", "4"]])
        result = merge_consecutive_tables([t1, t2], BUSINESS)
        assert len(result) == 1
        assert len(result[0].rows) == 2

    def test_no_merge_different_headers(self):
        """不同表头不合并"""
        t1 = Block(type="table", y_top=0, headers=["A", "B"], rows=[["1", "2"]])
        t2 = Block(type="table", y_top=10, headers=["C", "D"], rows=[["3", "4"]])
        result = merge_consecutive_tables([t1, t2], BUSINESS)
        assert len(result) == 2

    def test_table_separated_by_paragraph_not_merged(self):
        """中间隔段落的两个表格不合并"""
        t1 = Block(type="table", y_top=0, headers=["A"], rows=[["1"]])
        p = Block(type="paragraph", y_top=5, text="中间文字")
        t2 = Block(type="table", y_top=10, headers=["A"], rows=[["2"]])
        result = merge_consecutive_tables([t1, p, t2], BUSINESS)
        assert len(result) == 3

    def test_merge_similar_headers(self):
        """表头相似度高（≥0.8）应合并"""
        t1 = Block(type="table", y_top=0, headers=["序号", "名称", "值"], rows=[["1", "A", "10"]])
        # 第二页表头略改（多一个空格），token 集合相同
        t2 = Block(type="table", y_top=10, headers=["序 号", "名称", "值"], rows=[["2", "B", "20"]])
        result = merge_consecutive_tables([t1, t2], BUSINESS)
        assert len(result) == 1
        assert len(result[0].rows) == 2

    def test_merge_second_page_no_header(self):
        """第二页无表头（首行像数据行）应合并"""
        t1 = Block(type="table", y_top=0, headers=["表代码", "说明"], rows=[["TB099", "删除"]])
        # 第二个表格首行是数据行（含业务代码），无独立表头
        t2 = Block(type="table", y_top=10, headers=["", ""], rows=[["TC097", "新增"], ["TD010", "修改"]])
        result = merge_consecutive_tables([t1, t2], BUSINESS)
        assert len(result) == 1
        assert len(result[0].rows) == 3

    def test_no_merge_dissimilar_headers(self):
        """表头相似度低不应合并"""
        t1 = Block(type="table", y_top=0, headers=["序号", "名称"], rows=[["1", "A"]])
        t2 = Block(type="table", y_top=10, headers=["日期", "金额", "备注", "经办"], rows=[["2024", "100", "无", "张"]])
        result = merge_consecutive_tables([t1, t2], BUSINESS)
        assert len(result) == 2

    def test_chain_merge_three_tables(self):
        """三个相同表头的表格应链式合并为一个"""
        t1 = Block(type="table", y_top=0, headers=["A"], rows=[["1"]])
        t2 = Block(type="table", y_top=10, headers=["A"], rows=[["2"]])
        t3 = Block(type="table", y_top=20, headers=["A"], rows=[["3"]])
        result = merge_consecutive_tables([t1, t2, t3], BUSINESS)
        assert len(result) == 1
        assert len(result[0].rows) == 3
