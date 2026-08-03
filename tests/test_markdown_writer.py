"""Markdown 渲染器测试"""

from block import Block
from config import ConvertOptions
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


class TestMergeBlankLines:
    """空行清理：连续 2+ 空行压缩为 1 个"""

    def test_blank_lines_merged_by_default(self):
        """默认开启，连续空行被压缩"""
        blocks = [
            Block(type="paragraph", text="段落A"),
            Block(type="paragraph", text=""),
            Block(type="paragraph", text=""),
            Block(type="paragraph", text="段落B"),
        ]
        md = render(blocks, title="T")
        # 不应出现 3+ 连续换行（即 2+ 空行）
        assert "\n\n\n" not in md

    def test_blank_lines_disabled(self):
        """关闭后不压缩（但仍跳过空段落）"""
        opts = ConvertOptions(merge_blank_lines=False)
        blocks = [Block(type="paragraph", text="A"), Block(type="paragraph", text="B")]
        md = render(blocks, title="T", options=opts)
        assert "A" in md
        assert "B" in md

    def test_no_extra_blank_lines_in_normal_output(self):
        """正常输出不应有多余空行"""
        blocks = [
            Block(type="paragraph", text="段落1"),
            Block(type="table", headers=["A"], rows=[["1"]]),
            Block(type="paragraph", text="段落2"),
        ]
        md = render(blocks, title="T")
        assert "\n\n\n" not in md


class TestFrontMatter:
    """YAML front matter 元数据头"""

    def test_front_matter_added(self):
        """add_front_matter=True 时输出 YAML 头"""
        opts = ConvertOptions(add_front_matter=True)
        blocks = [Block(type="paragraph", text="内容")]
        metadata = {"source": "test.pdf", "pages": 5, "converted": "2026-08-03"}
        md = render(blocks, title="T", options=opts, metadata=metadata)
        assert md.startswith("---")
        assert "source: test.pdf" in md
        assert "pages: 5" in md
        assert "converted: 2026-08-03" in md

    def test_front_matter_disabled_by_default(self):
        """默认不输出 front matter"""
        blocks = [Block(type="paragraph", text="内容")]
        md = render(blocks, title="T")
        assert not md.startswith("---")

    def test_front_matter_without_metadata_ignored(self):
        """add_front_matter=True 但无 metadata 时不输出"""
        opts = ConvertOptions(add_front_matter=True)
        blocks = [Block(type="paragraph", text="内容")]
        md = render(blocks, title="T", options=opts, metadata=None)
        assert not md.startswith("---")
