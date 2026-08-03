"""cli 模块单元测试

不依赖真实文件转换（那需要样本），只测试：
- 参数解析
- _build_options 的开关映射
- _format_size / _apply_name_template / _resolve_output_path
- 子命令分发
"""

import os

import pytest

from cli import (
    _apply_name_template,
    _build_options,
    _format_size,
    _resolve_output_path,
    build_parser,
    main,
)
from config import ConvertOptions


class TestBuildOptions:
    def _args(self, **kw):
        # 模拟 argparse Namespace
        class N:
            pass
        n = N()
        n.no_postprocess = kw.get("no_postprocess", False)
        n.business_mode = kw.get("business_mode", False)
        n.no_ocr = kw.get("no_ocr", False)
        n.ocr_lang = kw.get("ocr_lang", None)
        n.page_range = kw.get("page_range", None)
        return n

    def test_default_options(self):
        opts = _build_options(self._args())
        assert isinstance(opts, ConvertOptions)
        assert opts.remove_cjk_spaces is True
        assert opts.business_mode is False

    def test_business_mode(self):
        opts = _build_options(self._args(business_mode=True))
        assert opts.business_mode is True
        assert opts.fix_list_number_positions is True
        assert opts.infer_empty_headers is True

    def test_no_postprocess_disables_all(self):
        opts = _build_options(self._args(no_postprocess=True))
        assert opts.remove_cjk_spaces is False
        assert opts.merge_broken_paragraphs is False
        assert opts.fix_headings is False
        assert opts.business_mode is False

    def test_no_ocr(self):
        opts = _build_options(self._args(no_ocr=True))
        assert opts.enable_ocr is False

    def test_ocr_lang_override(self):
        opts = _build_options(self._args(ocr_lang="en"))
        assert opts.ocr_lang == "en"

    def test_page_range_valid(self):
        opts = _build_options(self._args(page_range="5-10"))
        assert opts.page_range == (5, 10)

    def test_page_range_invalid_ignored(self, capsys):
        opts = _build_options(self._args(page_range="invalid"))
        assert opts.page_range is None


class TestFormatSize:
    def test_bytes(self):
        assert _format_size(512) == "512.0 B"

    def test_kb(self):
        assert _format_size(2048) == "2.0 KB"

    def test_mb(self):
        assert _format_size(2 * 1024 * 1024) == "2.0 MB"


class TestNameTemplate:
    def test_no_template(self):
        assert _apply_name_template(None, "report") == "report"

    def test_simple_name(self):
        assert _apply_name_template("{name}", "report") == "report"

    def test_with_date(self):
        result = _apply_name_template("{name}_{date}", "report")
        assert "report_" in result
        # 日期格式 YYYY-MM-DD
        assert len(result.split("_")[-1]) == 10

    def test_with_seq(self):
        assert _apply_name_template("{name}_{seq}", "report") == "report_0"


class TestResolveOutputPath:
    def test_no_out_dir(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        result = _resolve_output_path(None, str(src), None)
        assert result.endswith("src.md")
        assert os.path.dirname(result) == str(tmp_path)

    def test_with_out_dir(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        out_dir = tmp_path / "output"
        result = _resolve_output_path(str(out_dir), str(src), None)
        assert result == str(out_dir / "src.md")
        assert out_dir.exists()

    def test_with_template(self, tmp_path):
        src = tmp_path / "report.pdf"
        src.write_text("")
        result = _resolve_output_path(None, str(src), "{name}_v2")
        assert result.endswith("report_v2.md")


class TestArgparse:
    def test_convert_command(self):
        parser = build_parser()
        args = parser.parse_args(["convert", "input.pdf"])
        assert args.command == "convert"
        assert args.input == "input.pdf"
        assert args.no_postprocess is False

    def test_convert_with_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "convert", "input.pdf",
            "-o", "out.md",
            "--business-mode",
            "--no-ocr",
            "--page-range", "3-8",
        ])
        assert args.output == "out.md"
        assert args.business_mode is True
        assert args.no_ocr is True
        assert args.page_range == "3-8"

    def test_batch_recursive(self):
        parser = build_parser()
        args = parser.parse_args(["batch", "input_dir", "--recursive"])
        assert args.command == "batch"
        assert args.recursive is True

    def test_info_command(self):
        parser = build_parser()
        args = parser.parse_args(["info", "doc.pdf"])
        assert args.command == "info"
        assert args.input == "doc.pdf"

    def test_no_command_fails(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestInfoCommand:
    def test_info_nonexistent_file(self, capsys):
        rc = main(["info", "nonexistent_file.pdf"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "不存在" in err


class TestConvertCommand:
    def test_convert_nonexistent_file(self, capsys):
        rc = main(["convert", "nonexistent_file.pdf"])
        assert rc == 2


class TestBatchCommand:
    def test_batch_nonexistent_dir(self, capsys):
        rc = main(["batch", "nonexistent_dir"])
        assert rc == 2

    def test_batch_empty_dir(self, tmp_path, capsys):
        rc = main(["batch", str(tmp_path)])
        assert rc == 0
