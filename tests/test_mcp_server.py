"""mcp_server 模块单元测试

测试三个 MCP 工具的核心行为：
- convert_to_markdown：单文件转换（成功/失败/写文件/page_range）
- batch_convert：目录批量转换
- get_document_info：文档信息查询

MCP 工具函数用 @mcp.tool() 装饰后仍可直接调用（装饰器不改变函数签名），
因此测试直接调用函数，无需启动 MCP server / client。测试样本位于
tests/samples/ 目录（与其他测试共用，避免样本冗余）。
"""

import os

import pytest

import mcp_server
from config import ConvertOptions

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")
SIMPLE_PDF = os.path.join(SAMPLES, "simple_test.pdf")
CROSS_PDF = os.path.join(SAMPLES, "cross_page_table.pdf")


class TestConvertToMarkdown:
    def test_pdf_convert_returns_content(self):
        """PDF 转换成功，返回 Markdown 内容与统计"""
        r = mcp_server.convert_to_markdown(SIMPLE_PDF)
        assert r["success"] is True
        assert r["error"] is None
        assert isinstance(r["content"], str)
        assert "# simple_test" in r["content"]
        assert "测试文档" in r["content"]
        assert r["output_path"] == ""  # 未指定则不写文件

    def test_pdf_convert_stats(self):
        """stats 字段结构正确"""
        r = mcp_server.convert_to_markdown(SIMPLE_PDF)
        stats = r["stats"]
        assert stats["page_count"] == 1
        assert stats["paragraphs"] >= 1
        assert "tables" in stats
        assert "lines" in stats

    def test_convert_writes_file(self, tmp_path):
        """指定 output_path 时写入文件并返回绝对路径"""
        out = tmp_path / "out.md"
        r = mcp_server.convert_to_markdown(SIMPLE_PDF, output_path=str(out))
        assert r["success"] is True
        assert r["output_path"] == str(out.resolve())
        assert out.exists()
        assert out.read_text(encoding="utf-8") == r["content"]

    def test_nonexistent_file(self):
        """文件不存在返回结构化错误，不抛异常"""
        r = mcp_server.convert_to_markdown("nonexistent.pdf")
        assert r["success"] is False
        assert "不存在" in r["error"]

    def test_unsupported_format(self, tmp_path):
        """不支持的扩展名返回错误"""
        f = tmp_path / "x.txt"
        f.write_text("hello", encoding="utf-8")
        r = mcp_server.convert_to_markdown(str(f))
        assert r["success"] is False
        assert "不支持" in r["error"]

    def test_html_format(self):
        """format=html 返回 HTML 内容"""
        r = mcp_server.convert_to_markdown(SIMPLE_PDF, format="html")
        assert r["success"] is True
        assert "<html" in r["content"] or "<h1>" in r["content"]

    def test_page_range(self):
        """page_range=[1,1] 正常工作（不抛异常）"""
        r = mcp_server.convert_to_markdown(CROSS_PDF, page_range=[1, 1])
        assert r["success"] is True
        assert r["error"] is None

    def test_invalid_page_range(self):
        """page_range 长度不为 2 时返回错误"""
        r = mcp_server.convert_to_markdown(CROSS_PDF, page_range=[1])
        assert r["success"] is False
        assert "page_range" in r["error"]

    def test_business_mode_flag(self):
        """business_mode=True 不影响转换成功（开关映射正确）"""
        r = mcp_server.convert_to_markdown(SIMPLE_PDF, business_mode=True)
        assert r["success"] is True


class TestBatchConvert:
    def test_batch_directory(self, tmp_path):
        """批量转换 test_samples 目录，全部成功"""
        r = mcp_server.batch_convert(SAMPLES, output_dir=str(tmp_path))
        assert r["total"] >= 2
        assert r["success"] == r["total"]
        assert r["failed"] == 0
        assert len(r["results"]) == r["total"]
        for item in r["results"]:
            assert item["success"] is True
            assert os.path.exists(item["output_path"])

    def test_batch_nonexistent_dir(self):
        """目录不存在返回错误"""
        r = mcp_server.batch_convert("nonexistent_dir")
        assert r["success"] is False
        assert "不存在" in r["error"]

    def test_batch_empty_dir(self, tmp_path):
        """空目录返回 total=0"""
        r = mcp_server.batch_convert(str(tmp_path))
        assert r["total"] == 0
        assert r["success"] == 0

    def test_batch_creates_output_files(self, tmp_path):
        """批量转换在输出目录生成 .md 文件"""
        r = mcp_server.batch_convert(SAMPLES, output_dir=str(tmp_path))
        md_files = list(tmp_path.glob("*.md"))
        assert len(md_files) == r["success"]


class TestGetDocumentInfo:
    def test_pdf_info(self):
        """PDF 信息含格式/大小/页数/扫描件判定"""
        r = mcp_server.get_document_info(SIMPLE_PDF)
        assert r["format"] == "PDF"
        assert r["size_bytes"] > 0
        assert r["page_count"] == 1
        assert "is_scanned" in r
        assert r["error"] is None

    def test_nonexistent_file(self):
        """文件不存在返回错误"""
        r = mcp_server.get_document_info("nonexistent.pdf")
        assert r["success"] is False
        assert "不存在" in r["error"]

    def test_unsupported_format(self, tmp_path):
        """不支持的格式返回错误"""
        f = tmp_path / "x.txt"
        f.write_text("hello", encoding="utf-8")
        r = mcp_server.get_document_info(str(f))
        assert r["success"] is False
        assert "不支持" in r["error"]


class TestBuildOptions:
    """_build_options 辅助函数的参数映射"""

    def test_default(self):
        opts = mcp_server._build_options()
        assert isinstance(opts, ConvertOptions)
        assert opts.business_mode is False
        assert opts.enable_ocr is True

    def test_business_mode(self):
        opts = mcp_server._build_options(business_mode=True)
        assert opts.business_mode is True
        assert opts.fix_list_number_positions is True
        assert opts.infer_empty_headers is True

    def test_page_range_to_tuple(self):
        opts = mcp_server._build_options(page_range=[5, 10])
        assert opts.page_range == (5, 10)

    def test_invalid_page_range(self):
        with pytest.raises(ValueError):
            mcp_server._build_options(page_range=[1])


class TestServerRegistration:
    """验证三个工具已正确注册到 MCPServer"""

    def test_three_tools_registered(self):
        """list_tools 返回三个工具"""
        import asyncio

        tools = asyncio.run(mcp_server.mcp.list_tools())
        names = {t.name for t in tools}
        assert names == {"convert_to_markdown", "batch_convert", "get_document_info"}

    def test_tool_schemas_have_required_params(self):
        """工具 schema 含必填参数"""
        import asyncio

        tools = asyncio.run(mcp_server.mcp.list_tools())
        tool_map = {t.name: t for t in tools}
        assert "file_path" in tool_map["convert_to_markdown"].input_schema["required"]
        assert "directory" in tool_map["batch_convert"].input_schema["required"]
        assert "file_path" in tool_map["get_document_info"].input_schema["required"]
