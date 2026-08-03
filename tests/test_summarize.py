"""summarize 智能摘要模块测试"""

from block import Block
from summarize import summarize


class TestSummarize:
    def test_basic_summary(self):
        """提取标题和预览"""
        blocks = [
            Block(type="paragraph", text="# 文档标题"),
            Block(type="paragraph", text="## 第一章 概述"),
            Block(type="paragraph", text="这是第一章的内容。"),
            Block(type="paragraph", text="## 第二章 详情"),
            Block(type="paragraph", text="这是第二章的内容。"),
        ]
        result = summarize(blocks, title="测试文档")
        assert result["title"] == "测试文档"
        # # 文档标题(L1) + 两个 ## 章节(L2) = 3 个
        assert len(result["outline"]) == 3
        assert result["outline"][0]["level"] == 1
        assert result["outline"][1]["heading"] == "第一章 概述"
        assert result["outline"][1]["preview"] == "这是第一章的内容。"

    def test_table_stats(self):
        """表格统计正确"""
        blocks = [
            Block(type="paragraph", text="## 章节"),
            Block(type="table", headers=["A", "B"], rows=[["1", "2"], ["3", "4"]]),
        ]
        result = summarize(blocks)
        assert result["stats"]["tables"] == 1
        assert result["stats"]["table_rows"] == 2

    def test_section_number_heading(self):
        """章节号开头的段落识别为标题"""
        blocks = [
            Block(type="paragraph", text="1.1 总体说明"),
            Block(type="paragraph", text="总体说明的内容。"),
        ]
        result = summarize(blocks)
        assert len(result["outline"]) == 1
        assert result["outline"][0]["heading"] == "1.1 总体说明"

    def test_preview_truncated(self):
        """预览超长时截断"""
        long_text = "a" * 200
        blocks = [
            Block(type="paragraph", text="## 标题"),
            Block(type="paragraph", text=long_text),
        ]
        result = summarize(blocks, max_section_preview=50)
        assert len(result["outline"][0]["preview"]) == 53  # 50 + "..."
        assert result["outline"][0]["preview"].endswith("...")

    def test_no_headings(self):
        """无标题时 outline 为空，段落仍统计"""
        blocks = [
            Block(type="paragraph", text="普通段落1"),
            Block(type="paragraph", text="普通段落2"),
        ]
        result = summarize(blocks)
        assert result["outline"] == []
        assert result["stats"]["paragraphs"] == 2

    def test_empty_blocks(self):
        """空 Block 列表"""
        result = summarize([])
        assert result["outline"] == []
        assert result["stats"]["paragraphs"] == 0

    def test_chapter_prefix_heading(self):
        """中文章节号（第X章）识别为标题"""
        blocks = [
            Block(type="paragraph", text="第一章 概述"),
            Block(type="paragraph", text="概述内容"),
        ]
        result = summarize(blocks)
        assert len(result["outline"]) == 1
        assert "第一章" in result["outline"][0]["heading"]
