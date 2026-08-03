"""output_path 模块单元测试

覆盖：
- apply_name_template 变量替换
- resolve_unique_output_path 重名保护（_1/_2/...、{seq} 模板）
"""

import os

from output_path import apply_name_template, resolve_unique_output_path


class TestApplyNameTemplate:
    def test_no_template(self):
        assert apply_name_template(None, "report") == "report"

    def test_empty_template(self):
        assert apply_name_template("", "report") == "report"

    def test_simple_name(self):
        assert apply_name_template("{name}", "report") == "report"

    def test_with_date(self):
        result = apply_name_template("{name}_{date}", "report")
        assert result.startswith("report_")
        # YYYY-MM-DD
        assert len(result.split("_")[-1]) == 10

    def test_with_seq(self):
        assert apply_name_template("{name}_{seq}", "report", seq=3) == "report_3"

    def test_combined(self):
        result = apply_name_template("{name}_{date}_{seq}", "report", seq=5)
        assert result.startswith("report_")
        assert result.endswith("_5")


class TestResolveUniqueOutputPath:
    def test_no_conflict_no_out_dir(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        result = resolve_unique_output_path(None, str(src))
        assert result.endswith("src.md")
        assert os.path.dirname(result) == str(tmp_path)

    def test_no_conflict_with_out_dir(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        out_dir = tmp_path / "output"
        result = resolve_unique_output_path(str(out_dir), str(src))
        assert result == str(out_dir / "src.md")
        assert out_dir.exists()

    def test_conflict_appends_1(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        # 预先创建同名输出
        existing = tmp_path / "src.md"
        existing.write_text("old")
        result = resolve_unique_output_path(None, str(src))
        assert result.endswith("src_1.md")
        # 原文件不应被覆盖
        assert existing.read_text() == "old"

    def test_conflict_appends_2_then_3(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        (tmp_path / "src.md").write_text("0")
        (tmp_path / "src_1.md").write_text("1")
        result = resolve_unique_output_path(None, str(src))
        assert result.endswith("src_2.md")

    def test_template_with_seq_uses_template_seq(self, tmp_path):
        src = tmp_path / "report.pdf"
        src.write_text("")
        # 预占 seq=0
        (tmp_path / "report_0.md").write_text("x")
        result = resolve_unique_output_path(
            None, str(src), template="{name}_{seq}"
        )
        assert result.endswith("report_1.md")

    def test_template_with_seq_increments(self, tmp_path):
        src = tmp_path / "report.pdf"
        src.write_text("")
        (tmp_path / "report_0.md").write_text("x")
        (tmp_path / "report_1.md").write_text("x")
        (tmp_path / "report_2.md").write_text("x")
        result = resolve_unique_output_path(
            None, str(src), template="{name}_{seq}"
        )
        assert result.endswith("report_3.md")

    def test_template_without_seq_falls_back_to_suffix(self, tmp_path):
        src = tmp_path / "report.pdf"
        src.write_text("")
        (tmp_path / "report_v2.md").write_text("x")
        result = resolve_unique_output_path(
            None, str(src), template="{name}_v2"
        )
        assert result.endswith("report_v2_1.md")

    def test_creates_out_dir_if_missing(self, tmp_path):
        src = tmp_path / "src.pdf"
        src.write_text("")
        out_dir = tmp_path / "deep" / "nested" / "dir"
        result = resolve_unique_output_path(str(out_dir), str(src))
        assert out_dir.exists()
        assert result.startswith(str(out_dir))
