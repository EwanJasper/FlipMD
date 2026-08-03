"""Markdown 渲染器测试"""

from block import Block
from markdown_writer import render


class TestRender:
    def test_title(self):
        md = render([], title="文档标题")
        assert md.startswith("# 文档标题")

    def test_paragraph(self):
        blocks = [Block(type="paragraph", text="这是段落。")]
        md = render(blocks, title="T")
        assert "这是段落。" in md

    def test_table(self):
        blocks = [Block(type="table", headers=["A", "B"], rows=[["1", "2"]])]
        md = render(blocks, title="T")
        assert "| A | B |" in md
        assert "| --- | --- |" in md
        assert "| 1 | 2 |" in md

    def test_paragraph_table_spacing(self):
        """段落与表格之间应有空行"""
        blocks = [
            Block(type="paragraph", text="段落"),
            Block(type="table", headers=["A"], rows=[["1"]]),
        ]
        md = render(blocks, title="T")
        lines = md.splitlines()
        # 段落行与表格首行之间应有空行
        assert "段落" in lines
        assert "" in lines

    def test_pipe_escaped(self):
        """表格单元格中的 | 应被转义"""
        blocks = [Block(type="table", headers=["A"], rows=[["a|b"]])]
        md = render(blocks, title="T")
        assert "\\|" in md

    def test_empty_paragraph_skipped(self):
        blocks = [Block(type="paragraph", text="")]
        md = render(blocks, title="T")
        # 空段落应被跳过
        assert md.strip() == "# T"

    def test_image_block(self):
        """image Block 应渲染为 ![](path)"""
        blocks = [Block(type="image", image_path="images/page1_0.png")]
        md = render(blocks, title="T")
        assert "![](images/page1_0.png)" in md

    def test_image_with_paragraph_spacing(self):
        """图片与段落间应有空行"""
        blocks = [
            Block(type="paragraph", text="前段"),
            Block(type="image", image_path="images/a.png"),
            Block(type="paragraph", text="后段"),
        ]
        md = render(blocks, title="T")
        assert "前段" in md
        assert "![](images/a.png)" in md
        assert "后段" in md
        # 图片前后有空行
        lines = md.splitlines()
        assert "" in lines
