"""OCR 模块单元测试

只测试不依赖真实 PaddleOCR 模型的逻辑：
- is_paddleocr_available()
- _resolve_page_indices()
- is_scanned_pdf 的判定逻辑（用 mock）

真实 OCR 转换需要扫描型 PDF 样本和模型，放集成测试。
"""


from config import ConvertOptions
from ocr import (
    _resolve_page_indices,
    is_paddleocr_available,
    is_scanned_pdf,
)


class TestPaddleOcrAvailable:
    def test_returns_bool(self):
        assert isinstance(is_paddleocr_available(), bool)


class TestResolvePageIndices:
    def test_no_range_returns_all(self):
        assert _resolve_page_indices(10, None) == list(range(10))

    def test_with_range(self):
        assert _resolve_page_indices(10, (3, 5)) == [2, 3, 4]

    def test_range_clamped_to_total(self):
        assert _resolve_page_indices(3, (1, 100)) == [0, 1, 2]

    def test_range_start_below_one(self):
        assert _resolve_page_indices(5, (0, 3)) == [0, 1, 2]

    def test_empty_range(self):
        assert _resolve_page_indices(5, (10, 12)) == []


class TestIsScannedPdf:
    def test_nonexistent_file_returns_false(self):
        """不存在的文件不应抛异常，返回 False"""
        assert is_scanned_pdf("nonexistent_file.pdf") is False


class TestOcrOptions:
    def test_default_options_enable_ocr(self):
        opts = ConvertOptions.default()
        assert opts.enable_ocr is True

    def test_business_options_enable_ocr(self):
        opts = ConvertOptions.business()
        assert opts.enable_ocr is True

    def test_ocr_lang_default(self):
        opts = ConvertOptions.default()
        assert opts.ocr_lang == "ch"
