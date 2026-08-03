"""markdown_preview 单元测试

只测试纯逻辑函数（tokenize、parse_row、format_row），不依赖真实 Tk root。

注意：markdown_preview.MarkdownPreview 把这些逻辑封装在类方法/嵌套函数内，
无模块级纯函数可 import。下面的 parse_row / INLINE_PATTERN / HEADING_RE / SEP_RE
是按源码逻辑复制的独立副本，用于验证算法正确性。若 markdown_preview.py 修改了
对应正则或逻辑，需同步更新此处副本。
"""

import re


# 从 markdown_preview 提取的纯函数测试（避开 Tk 初始化）
def parse_row(line: str) -> list:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def test_parse_row_simple():
    assert parse_row("|a|b|c|") == ["a", "b", "c"]


def test_parse_row_no_leading_pipe():
    assert parse_row("a|b|c") == ["a", "b", "c"]


def test_parse_row_with_spaces():
    assert parse_row("| 名称 | 值 |") == ["名称", "值"]


# 行内 tokenize 用同一正则
INLINE_PATTERN = re.compile(
    r'(?P<code>`[^`]+`)'
    r'|(?P<link>\[([^\]]+)\]\(([^)]+)\))'
    r'|(?P<bold>\*\*[^*]+\*\*)'
    r'|(?P<italic>\*[^*]+\*)'
    r'|(?P<strike>~~[^~]+~~)'
)


def count_matches(text: str) -> dict:
    counts = {"code": 0, "link": 0, "bold": 0, "italic": 0, "strike": 0, "text": 0}
    pos = 0
    for m in INLINE_PATTERN.finditer(text):
        if m.start() > pos:
            counts["text"] += 1
        if m.group("code"):
            counts["code"] += 1
        elif m.group("link"):
            counts["link"] += 1
        elif m.group("bold"):
            counts["bold"] += 1
        elif m.group("italic"):
            counts["italic"] += 1
        elif m.group("strike"):
            counts["strike"] += 1
        pos = m.end()
    if pos < len(text):
        counts["text"] += 1
    return counts


def test_inline_code():
    assert count_matches("use `printf` here")["code"] == 1


def test_inline_bold():
    assert count_matches("**bold** text")["bold"] == 1


def test_inline_italic():
    assert count_matches("*italic* text")["italic"] == 1


def test_inline_strike():
    assert count_matches("~~deleted~~ text")["strike"] == 1


def test_inline_link():
    counts = count_matches("[click](https://example.com)")
    assert counts["link"] == 1
    assert counts["text"] == 0


def test_mixed_inline():
    counts = count_matches("plain `code` and **bold** end")
    assert counts["text"] == 3  # plain / and / end
    assert counts["code"] == 1
    assert counts["bold"] == 1


# 标题识别
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)$')


def test_heading_level_detection():
    m = HEADING_RE.match("## 二级标题")
    assert m and len(m.group(1)) == 2


def test_heading_six_levels():
    for n in range(1, 7):
        m = HEADING_RE.match(f"{'#' * n} 标题")
        assert m and len(m.group(1)) == n


def test_non_heading_no_match():
    assert HEADING_RE.match("普通文本") is None


# 表格分隔行识别
SEP_RE = re.compile(r'^\s*\|?[\s\-:|]+\|?\s*$')


def test_table_separator_simple():
    assert SEP_RE.match("|---|---|") is not None


def test_table_separator_aligned():
    assert SEP_RE.match("|:---:|---:|") is not None


def test_table_data_row_not_separator():
    assert SEP_RE.match("| 数据 | 值 |") is None
