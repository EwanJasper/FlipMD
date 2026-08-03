"""html_writer 单元测试"""

from block import Block
from html_writer import render_html


class TestRenderHtml:
    def test_title(self):
        html = render_html([], title="文档标题")
        assert "<title>文档标题</title>" in html
        assert "<h1>文档标题</h1>" in html

    def test_paragraph(self):
        html = render_html([Block(type="paragraph", text="普通段落")])
        assert "<p>普通段落</p>" in html

    def test_table(self):
        html = render_html([Block(type="table", headers=["A", "B"], rows=[["1", "2"]])])
        assert "<table" in html
        assert "<th>A</th>" in html
        assert "<th>B</th>" in html
        assert "<td>1</td>" in html
        assert "<td>2</td>" in html

    def test_image(self):
        html = render_html([Block(type="image", image_path="images/a.png")])
        assert '<img src="images/a.png"' in html

    def test_inline_bold(self):
        html = render_html([Block(type="paragraph", text="**bold**")])
        assert "<strong>bold</strong>" in html

    def test_inline_italic(self):
        html = render_html([Block(type="paragraph", text="*italic*")])
        assert "<em>italic</em>" in html

    def test_inline_strike(self):
        html = render_html([Block(type="paragraph", text="~~del~~")])
        assert "<del>del</del>" in html

    def test_inline_code(self):
        html = render_html([Block(type="paragraph", text="`code`")])
        assert "<code>code</code>" in html

    def test_inline_link(self):
        html = render_html([Block(type="paragraph", text="[text](https://example.com)")])
        assert '<a href="https://example.com">text</a>' in html

    def test_inline_link_relative_path(self):
        """相对路径链接应保留"""
        html = render_html([Block(type="paragraph", text="[text](./page.html)")])
        assert '<a href="./page.html">text</a>' in html

    def test_inline_link_anchor(self):
        """锚点链接应保留"""
        html = render_html([Block(type="paragraph", text="[text](#section)")])
        assert '<a href="#section">text</a>' in html

    def test_inline_link_javascript_blocked(self):
        """javascript: scheme 应被过滤，防 XSS（P0-1 修复）"""
        html = render_html([Block(type="paragraph", text="[click](javascript:alert(1))")])
        assert "javascript:alert" not in html
        assert '<a href="">click</a>' in html

    def test_inline_link_data_blocked(self):
        """data: scheme 应被过滤"""
        html = render_html([Block(type="paragraph", text="[x](data:text/html,<script>)")])
        assert "data:text/html" not in html

    def test_html_escaped(self):
        """特殊字符应被转义，防 XSS"""
        html = render_html([Block(type="paragraph", text="<script>alert(1)</script>")])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_table_cell_escaped(self):
        html = render_html([Block(type="table", headers=["A"], rows=[["<b>"]])])
        assert "&lt;b&gt;" in html

    def test_full_html_document(self):
        """输出应是完整 HTML 文档"""
        html = render_html([Block(type="paragraph", text="内容")], title="T")
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_empty_paragraph_skipped(self):
        html = render_html([Block(type="paragraph", text="")])
        # 空段落不应产生 <p></p>
        assert "<p></p>" not in html

    def test_image_attr_escaped(self):
        """图片 src 属性应被转义，防注入"""
        html = render_html([Block(type="image", image_path='a" onerror="alert(1)')])  # noqa: S105
        # 不应有未转义的 onerror
        assert 'onerror="alert' not in html
