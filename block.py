"""Block 数据结构与异常定义

所有内容（段落、表格）统一为 Block，按 y_top 排序确保阅读顺序正确。
PDF 引擎、Word 引擎、Markdown 渲染器共用此结构。
"""

from dataclasses import dataclass, field


class PdfEncryptedError(Exception):
    """PDF 加密异常"""
    pass


class PdfEmptyError(Exception):
    """PDF 内容为空异常"""
    pass


@dataclass
class Block:
    """内容块，按 (page, y_top) 排列"""
    type: str  # "paragraph" / "table" / "image"
    y_top: float = 0.0
    # 段落
    text: str = ""
    # 表格
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    # 图片：相对 Markdown 文件的引用路径（如 "images/page1_0.png"）
    image_path: str = ""
    # 所在 PDF 页码（1-based）；0 表示未知（Word / 合并流）
    # y_top 是页内坐标，跨页全局排序必须先按 page 再按 y_top
    page: int = 0
    # 行主字号与粗体标记（PDF 专有，用于字号→标题级别检测）；Word 流保持 0/False
    font_size: float = 0.0
    font_bold: bool = False
    # 检测出的 Markdown 标题级别（1-6），0 表示非标题
    heading_level: int = 0
