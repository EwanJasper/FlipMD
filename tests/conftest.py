"""pytest 公共 fixture 与测试样本路径"""

import sys
from pathlib import Path

# 让测试能导入项目根目录的模块
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES_DIR = Path(__file__).parent / "samples"

# 黄金样本（内置，随仓库提交）- 用于回归测试，确保重构不破坏现有行为
# 使用 tests/samples/ 下的 PDF + 对应 .md 基线，不再依赖被 gitignore 的 result/
GOLDEN_PDF_1 = SAMPLES_DIR / "simple_test.pdf"
GOLDEN_MD_1 = SAMPLES_DIR / "simple_test_golden.md"
GOLDEN_PDF_2 = SAMPLES_DIR / "cross_page_table.pdf"
GOLDEN_MD_2 = SAMPLES_DIR / "cross_page_table_golden.md"


import pytest


@pytest.fixture
def simple_pdf() -> str:
    """简单测试 PDF"""
    return str(SAMPLES_DIR / "simple_test.pdf")


@pytest.fixture
def cross_page_pdf() -> str:
    """含跨页表格的测试 PDF"""
    return str(SAMPLES_DIR / "cross_page_table.pdf")


@pytest.fixture
def golden_pdf_1() -> str:
    """真实 PDF 黄金样本 1"""
    return str(GOLDEN_PDF_1)


@pytest.fixture
def golden_md_1() -> str:
    """真实业务 PDF 黄金样本 1 的预期 Markdown"""
    with open(GOLDEN_MD_1, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def golden_pdf_2() -> str:
    """真实 PDF 黄金样本 2"""
    return str(GOLDEN_PDF_2)


@pytest.fixture
def golden_md_2() -> str:
    """真实业务 PDF 黄金样本 2 的预期 Markdown"""
    with open(GOLDEN_MD_2, encoding="utf-8") as f:
        return f.read()


def has_golden_samples() -> bool:
    """检查黄金样本是否存在（CI 环境可能没有）"""
    return GOLDEN_PDF_1.exists() and GOLDEN_MD_1.exists()
