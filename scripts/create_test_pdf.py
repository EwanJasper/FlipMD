"""生成测试用 PDF 文件"""
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus import Table as RMLTable

# 注册中文字体
_FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
pdfmetrics.registerFont(TTFont("SimHei", _FONT_PATH))


def create_test_pdf(path: str):
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()

    # 修改默认样式使用中文字体
    for s in styles.byName.values():
        s.fontName = "SimHei"

    elements = []

    # 标题
    elements.append(Paragraph("测试文档", styles["Title"]))
    elements.append(Spacer(1, 20))

    # 段落
    elements.append(Paragraph("这是一段测试文字。PDF to Markdown 转换工具应该能够正确提取这段文字。", styles["Normal"]))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("这是第二段文字，包含一些中文内容。用于测试段落提取功能。", styles["Normal"]))
    elements.append(Spacer(1, 20))

    # 表格
    table_data = [
        ["姓名", "年龄", "部门"],
        ["张三", "28", "技术部"],
        ["李四", "32", "市场部"],
        ["王五", "25", "财务部"],
    ]
    table = RMLTable(table_data, colWidths=[100, 80, 100])
    table.setStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"),
                    ("FONTNAME", (0, 0), (-1, -1), "SimHei")])
    elements.append(table)
    elements.append(Spacer(1, 20))

    # 段落
    elements.append(Paragraph("表格后面的文字，用于验证表格区域外文字的正确提取。", styles["Normal"]))

    doc.build(elements)


def create_cross_page_table_pdf(path: str):
    """生成一个跨页表格的测试 PDF"""
    from reportlab.lib.units import mm
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()

    # 修改默认样式使用中文字体
    for s in styles.byName.values():
        s.fontName = "SimHei"

    elements = []

    elements.append(Paragraph("跨页表格测试", styles["Title"]))
    elements.append(Spacer(1, 10))

    # 生成足够多行以跨页的表格
    headers = ["编号", "姓名", "部门", "职位"]
    data = [headers]
    for i in range(1, 40):  # 40 行足够跨页
        data.append([str(i), f"员工{i}", ["技术部", "市场部", "财务部", "行政部"][i % 4],
                     ["工程师", "经理", "专员", "总监"][i % 4]])

    table = RMLTable(data, colWidths=[50, 80, 80, 80], repeatRows=1)
    table.setStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"),
                    ("FONTNAME", (0, 0), (-1, -1), "SimHei")])
    elements.append(table)

    doc.build(elements)


if __name__ == "__main__":
    os.makedirs("tests/samples", exist_ok=True)
    create_test_pdf("tests/samples/simple_test.pdf")
    print("测试 PDF 已生成: tests/samples/simple_test.pdf")
    create_cross_page_table_pdf("tests/samples/cross_page_table.pdf")
    print("跨页表格测试 PDF 已生成: tests/samples/cross_page_table.pdf")
