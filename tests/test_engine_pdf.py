"""PDF 解析集成测试

含黄金样本回归测试：确保重构后真实业务 PDF 转换结果与基线一致。
"""

import os

import pytest

from config import ConvertOptions
from engine import get_page_count, parse
from markdown_writer import render
from tests.conftest import has_golden_samples


class TestParsePdf:
    def test_simple_pdf(self, simple_pdf):
        """简单 PDF 应能解析出 Block 列表"""
        blocks = parse(simple_pdf)
        assert len(blocks) > 0
        # 应包含段落或表格
        types = {b.type for b in blocks}
        assert types & {"paragraph", "table"}

    def test_page_count(self, simple_pdf):
        """get_page_count 应返回正整数"""
        count = get_page_count(simple_pdf)
        assert count > 0

    def test_cross_page_table(self, cross_page_pdf):
        """含跨页表格的 PDF 应能解析（不报错）"""
        blocks = parse(cross_page_pdf)
        # 至少应解析出内容块（表格或段落）
        assert len(blocks) >= 1

    def test_nonexistent_file(self):
        """不存在的文件应抛 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            parse("nonexistent.pdf")


class TestPageRange:
    """page_range 对文本型 PDF 的页码范围过滤

    用 mock page 模拟多页 PDF，验证 parse() 只转换指定页码范围。
    page_range 为 1-based 闭区间 [start, end]。
    """

    def _make_mock_pdf(self, n_pages: int):
        """构造 n_pages 页的 mock pdfplumber PDF，每页含可区分的文字"""
        from unittest.mock import MagicMock

        pages = []
        for i in range(n_pages):
            page = MagicMock()
            page.height = 842  # A4 高度
            page.find_tables.return_value = []  # 无表格
            # 每页返回不同文字，便于断言哪些页被处理
            page.extract_words.return_value = [
                {"text": f"第{i+1}页内容", "x0": 50, "x1": 100, "top": 50, "bottom": 60}
            ]
            pages.append(page)

        pdf = MagicMock()
        pdf.pages = pages
        pdf.__enter__.return_value = pdf  # with 语句返回自身
        pdf.__exit__.return_value = None
        return pdf

    def test_page_range_filters_pages(self, monkeypatch):
        """page_range=[2,3] 应只处理第 2、3 页"""
        import engine

        mock_pdf = self._make_mock_pdf(5)
        monkeypatch.setattr(engine.pdfplumber, "open", lambda *a, **k: mock_pdf)
        monkeypatch.setattr(engine.os.path, "exists", lambda p: True)

        opts = ConvertOptions.default()
        opts.filter_footer = False  # 简化：关闭页脚检测避免 mock 依赖
        opts.page_range = (2, 3)
        blocks = parse("fake.pdf", opts)

        texts = [b.text for b in blocks if b.type == "paragraph"]
        assert "第2页内容" in texts
        assert "第3页内容" in texts
        assert "第1页内容" not in texts
        assert "第4页内容" not in texts
        assert "第5页内容" not in texts

    def test_page_range_full(self, monkeypatch):
        """无 page_range 时处理全部页"""
        import engine

        mock_pdf = self._make_mock_pdf(3)
        monkeypatch.setattr(engine.pdfplumber, "open", lambda *a, **k: mock_pdf)
        monkeypatch.setattr(engine.os.path, "exists", lambda p: True)

        opts = ConvertOptions.default()
        opts.filter_footer = False
        blocks = parse("fake.pdf", opts)

        texts = [b.text for b in blocks if b.type == "paragraph"]
        assert "第1页内容" in texts
        assert "第2页内容" in texts
        assert "第3页内容" in texts

    def test_page_range_out_of_bounds_clamped(self, monkeypatch):
        """page_range 越界时应钳制到有效范围，不报错"""
        import engine

        mock_pdf = self._make_mock_pdf(3)
        monkeypatch.setattr(engine.pdfplumber, "open", lambda *a, **k: mock_pdf)
        monkeypatch.setattr(engine.os.path, "exists", lambda p: True)

        opts = ConvertOptions.default()
        opts.filter_footer = False
        opts.page_range = (2, 100)  # end 越界
        blocks = parse("fake.pdf", opts)

        texts = [b.text for b in blocks if b.type == "paragraph"]
        assert "第2页内容" in texts
        assert "第3页内容" in texts
        assert "第1页内容" not in texts


class TestClusterWordsIntoLines:
    """_cluster_words_into_lines 单元测试"""

    def _cluster(self, words):
        from engine import _cluster_words_into_lines
        return _cluster_words_into_lines(words)

    def _word(self, text, x0, top):
        return {"text": text, "x0": x0, "x1": x0 + len(text) * 5,
                "top": top, "bottom": top + 10}

    def test_single_line_ordered_by_x0(self):
        """同一行内词按 x0 排序"""
        words = [
            self._word("新增", 126, 696.1),
            self._word("TB01", 154, 697.0),  # top 略不同但 < 3
            self._word("表", 186, 696.1),
        ]
        lines = self._cluster(words)
        assert len(lines) == 1
        assert [w["text"] for w in lines[0]] == ["新增", "TB01", "表"]

    def test_baseline_misalignment_reordered_by_x0(self):
        """中文与西文 baseline 微差（<1pt）不应打乱 x0 顺序

        模拟真实场景：中文 top=696.1，TB01 top=697.0，
        原 (top, x0) 排序会把 TB01 排到行尾，修复后行内按 x0 重排。
        """
        words = [
            self._word("新增", 126, 696.1),
            self._word("表，在记录明细", 186, 696.1),
            self._word("中新增原数据", 330, 696.1),
            self._word("的变更数据。", 439, 696.1),
            self._word("1.", 111, 697.0),
            self._word("TB01", 154, 697.0),
            self._word("TB01", 298, 697.0),
            self._word("TB01", 406, 697.0),
        ]
        lines = self._cluster(words)
        assert len(lines) == 1
        texts = [w["text"] for w in lines[0]]
        # TB01 应穿插在中文之间，而非堆在行末
        assert texts == ["1.", "新增", "TB01", "表，在记录明细",
                         "TB01", "中新增原数据", "TB01", "的变更数据。"]

    def test_multiple_lines(self):
        """多行应正确分离"""
        words = [
            self._word("第一行", 100, 100),
            self._word("第二行", 100, 200),
        ]
        lines = self._cluster(words)
        assert len(lines) == 2
        assert lines[0][0]["text"] == "第一行"
        assert lines[1][0]["text"] == "第二行"

    def test_empty(self):
        assert self._cluster([]) == []


class TestMergeIndentedContinuations:
    """_merge_indented_continuations 单元测试（同页续行合并）

    输入格式：list[tuple[float, float, str]] = [(y_top, x0, text), ...]
    """

    def _merge(self, lines):
        from engine import _merge_indented_continuations
        return _merge_indented_continuations(lines)

    def test_indented_continuation_merged(self):
        """首行缩进 + 续行顶格 → 合并"""
        lines = [
            (100.0, 111.2, "（2）如原记录明细TB01 的状态标志为01-正常，则"),
            (115.0, 90.1, "新增变更记录写02-变更；"),
        ]
        result = self._merge(lines)
        assert len(result) == 1
        assert "则" in result[0][2]
        assert "新增变更记录" in result[0][2]

    def test_sentence_end_not_merged(self):
        """上一行以句末标点结尾 → 不合并"""
        lines = [
            (100.0, 90.0, "第一段正文以句号结尾。"),
            (115.0, 90.0, "第二段正文内容。"),
        ]
        result = self._merge(lines)
        assert len(result) == 2

    def test_paragraph_start_not_merged(self):
        """当前行以段落起始标志开头 → 不合并"""
        lines = [
            (100.0, 90.0, "上一段足够长的正文内容用于测试"),
            (115.0, 90.0, "（1）新列表项开始了一段新的内容"),
        ]
        result = self._merge(lines)
        assert len(result) == 2

    def test_heading_num_prev_not_merged(self):
        """上一行是章节号标题（如 3.1.1 xxx）→ 不与下一行合并"""
        lines = [
            (100.0, 90.0, "3.1.1 数据查询"),
            (115.0, 90.0, "数据应查询TB01表的记录"),
        ]
        result = self._merge(lines)
        assert len(result) == 2
        assert result[0][2] == "3.1.1 数据查询"

    def test_large_gap_not_merged(self):
        """行间距过大（>25pt，可能是标题/表格间隔）→ 不合并"""
        lines = [
            (100.0, 90.0, "上一段足够长的正文内容用于测试"),
            (140.0, 90.0, "下一段足够长的正文内容用于测试"),
        ]
        result = self._merge(lines)
        assert len(result) == 2

    def test_more_indented_not_merged(self):
        """当前行比上一行缩进更多（新缩进段落）→ 不合并"""
        lines = [
            (100.0, 90.0, "上一段足够长的正文内容用于测试"),
            (115.0, 100.0, "当前行缩进更多视为新段落"),
        ]
        result = self._merge(lines)
        assert len(result) == 2

    def test_single_line_passthrough(self):
        """单行原样返回"""
        lines = [(100.0, 90.0, "唯一一行")]
        assert self._merge(lines) == lines


@pytest.mark.skipif(not has_golden_samples(), reason="黄金样本不存在")
class TestGoldenRegression:
    """黄金样本回归测试：重构后转换结果必须与基线完全一致

    黄金样本是真实文档，需用 ConvertOptions.business()（启用特定规则）。
    """

    def test_golden_pdf_1(self, golden_pdf_1, golden_md_1):
        """样本1 PDF 转换结果应与黄金样本一致"""
        blocks = parse(golden_pdf_1, ConvertOptions.business())
        title = os.path.splitext(os.path.basename(golden_pdf_1))[0]
        md = render(blocks, title=title)
        assert md == golden_md_1, "样本1转换结果与黄金样本不一致（回归！）"

    def test_golden_pdf_2(self, golden_pdf_2, golden_md_2):
        """样本2 PDF 转换结果应与黄金样本一致"""
        blocks = parse(golden_pdf_2, ConvertOptions.business())
        title = os.path.splitext(os.path.basename(golden_pdf_2))[0]
        md = render(blocks, title=title)
        assert md == golden_md_2, "样本2转换结果与黄金样本不一致（回归！）"
