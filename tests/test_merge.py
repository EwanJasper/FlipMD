"""merge_and_render 多文档合并渲染测试"""

from block import Block
from markdown_writer import merge_and_render


class TestMergeAndRender:
    def test_basic_merge(self):
        """两个文档合并为单个 Markdown，每个作为二级标题章节"""
        docs = [
            ("文档A", [Block(type="paragraph", text="内容A")]),
            ("文档B", [Block(type="paragraph", text="内容B")]),
        ]
        md = merge_and_render(docs, title="合并")
        assert md.startswith("# 合并")
        assert "## 文档A" in md
        assert "## 文档B" in md
        assert "内容A" in md
        assert "内容B" in md

    def test_merge_with_tables(self):
        """合并含表格的文档"""
        docs = [
            ("doc1", [Block(type="table", headers=["A", "B"], rows=[["1", "2"]])]),
            ("doc2", [Block(type="paragraph", text="文字")]),
        ]
        md = merge_and_render(docs, title="T")
        assert "## doc1" in md
        assert "| A | B |" in md
        assert "## doc2" in md

    def test_merge_order_preserved(self):
        """合并顺序应与传入顺序一致"""
        docs = [
            ("第一", [Block(type="paragraph", text="1")]),
            ("第二", [Block(type="paragraph", text="2")]),
            ("第三", [Block(type="paragraph", text="3")]),
        ]
        md = merge_and_render(docs, title="T")
        pos1 = md.index("第一")
        pos2 = md.index("第二")
        pos3 = md.index("第三")
        assert pos1 < pos2 < pos3

    def test_empty_documents(self):
        """空文档列表应返回仅含标题"""
        md = merge_and_render([], title="T")
        assert md.strip() == "# T"

    def test_blank_lines_merged(self):
        """合并后空行清理生效"""
        docs = [
            ("A", [Block(type="paragraph", text="x"), Block(type="paragraph", text="")]),
            ("B", [Block(type="paragraph", text="y")]),
        ]
        md = merge_and_render(docs, title="T")
        assert "\n\n\n" not in md
