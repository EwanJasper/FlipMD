"""后处理规则单元测试

覆盖 README 效果对比表中的黄金用例，防止重构破坏现有行为。
"""

from block import Block
from config import ConvertOptions
from postprocess import (
    _BULLET_PREFIX_RE,
    _PARAGRAPH_START_RE,
    _apply_font_headings,
    _collapse_dot_leaders,
    fix_headings,
    fix_list_number_positions,
    headers_match,
    merge_broken_paragraphs,
    merge_consecutive_tables,
    remove_cjk_spaces,
    smart_join,
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


# ── smart_join ───────────────────────────────────────────────────

class TestSmartJoin:
    def test_english_words_get_space(self):
        assert smart_join("a lot of", "different weights") == "a lot of different weights"

    def test_sentence_punct_gets_space(self):
        assert smart_join("that low.", "But your users") == "that low. But your users"

    def test_cjk_concat_no_space(self):
        assert smart_join("数据查询", "模块设计") == "数据查询模块设计"

    def test_cjk_left_concat_no_space(self):
        # 左边界是中文时直接拼接（与 remove_cjk_spaces 行为一致）
        assert smart_join("使用", "PDF 工具") == "使用PDF 工具"

    def test_digit_then_word_gets_space(self):
        # 目录条目页码后接下一行
        assert smart_join("not a layout 8", "Detail comes later") == "not a layout 8 Detail comes later"

    def test_digits_concat_no_space(self):
        assert smart_join("2024", "0915") == "20240915"

    def test_punctuation_right_concat_no_space(self):
        # 右侧以标点开头（URL 续行等）不加空格
        assert smart_join("https://example.com", ".cn/docs") == "https://example.com.cn/docs"

    def test_word_then_open_paren_gets_space(self):
        assert smart_join("the function", "(see below)") == "the function (see below)"

    def test_strips_edges(self):
        assert smart_join("  left ", " right  ") == "left right"

    def test_empty_sides(self):
        assert smart_join("", "abc") == "abc"
        assert smart_join("abc", "") == "abc"


# ── _collapse_dot_leaders ────────────────────────────────────────

class TestCollapseDotLeaders:
    def test_spaced_leaders_collapsed(self):
        assert _collapse_dot_leaders("Start with a feature. . . . . . . 8") == "Start with a feature 8"

    def test_leading_space_before_leaders_consumed(self):
        """词尾与导线间的空格一并吃掉，页码前只留单空格"""
        assert _collapse_dot_leaders("Start with a feature . . . . . . 8") == "Start with a feature 8"

    def test_normal_ellipsis_kept(self):
        assert _collapse_dot_leaders("wait for it...") == "wait for it..."

    def test_long_dot_run_normalized(self):
        assert _collapse_dot_leaders("loading......done") == "loading...done"

    def test_sentence_untouched(self):
        text = "第一段。第二段。 1.2"
        assert _collapse_dot_leaders(text) == text


# ── 字号 → 标题级别检测 ──────────────────────────────────────────

def _para(text, size=0.0, bold=False, page=1):
    return Block(type="paragraph", y_top=1.0, text=text, page=page,
                 font_size=size, font_bold=bold)


class TestApplyFontHeadings:
    def test_size_tiers_map_to_levels(self):
        blocks = [
            _para("Introduction", size=28.0),
            _para("This is the chapter opening body text without any heading style.", size=10.0),
            _para("Setup and conventions", size=12.0),
            _para("Body text follows the section heading in the same body font size.", size=10.0),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text == "# Introduction"
        assert result[2].text == "## Setup and conventions"

    def test_bold_same_size_becomes_heading(self):
        blocks = [
            _para("Starting from Scratch", size=10.0, bold=True),
            _para("Start with a feature, not a layout when designing something new.", size=10.0),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text.startswith("# ")
        assert result[1].text == blocks[1].text  # 正文不动

    def test_pure_digit_line_excluded(self):
        blocks = [
            _para("3", size=96.0),
            _para("Body content of the chapter opener page goes here normally.", size=10.0),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text == "3"

    def test_sentence_like_line_excluded(self):
        blocks = [
            _para("This line ends with a period.", size=12.0),
            _para("Body content of the page continues here at body size.", size=10.0),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text == "This line ends with a period."

    def test_existing_hash_prefix_skipped(self):
        blocks = [
            _para("# 1.2 数据查询", size=16.0),
            _para("Body content of the section continues here at body size.", size=10.0),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text == "# 1.2 数据查询"

    def test_trailing_page_number_stripped(self):
        blocks = [
            _para("Contents", size=28.0),
            _para("Layout and Spacing", size=12.0, bold=True),
            _para("Body content fills the rest of the page at the body size.", size=10.0),
        ]
        # 目录条目行（正文号 + 页码尾巴）
        result = _apply_font_headings(blocks + [_para("Layout and Spacing 65", size=10.0, bold=True)])
        assert "## Layout and Spacing" in [b.text for b in result]

    def test_short_digit_tail_kept(self):
        blocks = [
            _para("iOS 13", size=12.0),
            _para("Body content about the platform continues here at body size.", size=10.0),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text == "# iOS 13"

    def test_no_font_info_passthrough(self):
        """Word / OCR 流（无字号信息）原样返回"""
        blocks = [
            Block(type="paragraph", y_top=0, text="普通标题文字"),
            Block(type="paragraph", y_top=1, text="普通正文内容"),
        ]
        result = _apply_font_headings(blocks)
        assert result[0].text == "普通标题文字"

    def test_empty_blocks(self):
        assert _apply_font_headings([]) == []


# ── 项目符号与列表保护 ──────────────────────────────────────────

class TestBulletsAndListProtection:
    def test_bullet_prefix_replacement(self):
        assert _BULLET_PREFIX_RE.sub("- ", "• A field for the departure city") == "- A field for the departure city"
        assert _BULLET_PREFIX_RE.sub("- ", "●居中显示的要点") == "- 居中显示的要点"

    def test_bullet_line_not_merged_into_prev(self):
        blocks = [
            Block(type="paragraph", y_top=0, text="Your interface will need the following things to work"),
            Block(type="paragraph", y_top=1, text="- A field for the departure city"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2

    def test_dash_paragraph_start_protects(self):
        r"""'- ' 开头的行不并入上一段（_PARAGRAPH_START_RE 含 ^-\s）"""
        assert _PARAGRAPH_START_RE.match("- 列表项内容")


# ── 目录条目防连串 ──────────────────────────────────────────────

class TestTocEntryGuard:
    def test_toc_entries_not_chained(self):
        """两行都以页码结尾（目录条目）→ 不合并成一段"""
        blocks = [
            Block(type="paragraph", y_top=0, text="Start with a feature, not a layout 8"),
            Block(type="paragraph", y_top=1, text="Detail comes later 12"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2

    def test_normal_continuation_with_digits_still_merges(self):
        """只有 prev 以数字结尾、curr 是普通续行 → 正常合并"""
        blocks = [
            Block(type="paragraph", y_top=0, text="the library ships in version 3"),
            Block(type="paragraph", y_top=1, text="and supports the legacy API"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 1


class TestBulletContinuationGuard:
    def test_uppercase_sentence_after_bullet_not_merged(self):
        """列表项后接大写字母开头的新句 → 不并入列表项"""
        blocks = [
            Block(type="paragraph", y_top=0, text="- A button to perform the search"),
            Block(type="paragraph", y_top=1, text="Start with that. Hell, you might not even need that other stuff"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 2
        assert result[0].text == "- A button to perform the search"

    def test_lowercase_continuation_after_bullet_merges(self):
        """列表项的换行续行（小写开头）→ 正常并入列表项"""
        blocks = [
            Block(type="paragraph", y_top=0, text="- install the required packages on the server"),
            Block(type="paragraph", y_top=1, text="before running the application for the first time"),
        ]
        result = merge_broken_paragraphs(blocks, BUSINESS)
        assert len(result) == 1
        assert result[0].text == "- install the required packages on the server before running the application for the first time"
