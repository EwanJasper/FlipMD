"""通用后处理函数

对 list[Block] 进行清洗与修复，与输入格式（PDF/Word）无关。
PDF 引擎和 Word 引擎共用此模块。

每个函数接受可选的 options: ConvertOptions，按开关决定是否执行对应规则。
不传 options 时使用 ConvertOptions.default()（保守，业务规则默认关）。

注意：为保证黄金样本回归测试通过，业务文档需显式传 ConvertOptions.business()。
"""

import re

from block import Block
from config import ConvertOptions


def _opts(options: ConvertOptions | None) -> ConvertOptions:
    """options 为 None 时返回默认选项"""
    return options if options is not None else ConvertOptions.default()


def remove_cjk_spaces(text: str) -> str:
    """去除中文字符之间的空格（半角与全角）"""
    # 半角空格
    text = re.sub(r'(?<=[\u4e00-\u9fff]) +(?=[\u4e00-\u9fff])', '', text)
    # 全角空格
    text = re.sub(r'(?<=[\u4e00-\u9fff])\u3000+(?=[\u4e00-\u9fff])', '', text)
    return text


def merge_broken_paragraphs(blocks: list[Block], options: ConvertOptions | None = None) -> list[Block]:
    """过滤无用内容 + 合并断裂短行 + 跨页续行合并 + 去除中文间多余空格

    options.merge_broken_paragraphs=False 时仅做基础过滤（页码/罗马数字/点线），
    不做短行合并、跨页续行合并与 CJK 空格清理。
    """
    opts = _opts(options)
    result: list[Block] = []
    for b in blocks:
        if b.type == "paragraph":
            text = b.text.strip()
            # 丢弃页码（单独的数字）— 始终执行
            if re.match(r'^\d+$', text):
                continue
            # 丢弃罗马数字页码
            if re.match(r'^[IVXLCDM]{1,6}$', text):
                continue
            # 丢弃目录中的点线
            if re.match(r'^[\.\s]{3,}$', text):
                continue

            if opts.remove_cjk_spaces:
                cleaned = remove_cjk_spaces(text)
            else:
                cleaned = text
            b.text = cleaned

            # 合并短行（≤6字纯中文）到前一段 — 业务文档特定场景
            if (opts.merge_broken_paragraphs
                    and result
                    and result[-1].type == "paragraph"
                    and len(cleaned) <= 6
                    and re.search(r'\d+\.\s*$', result[-1].text.strip())):
                result[-1].text += cleaned
                continue

            # 跨页续行合并：上一段不以句末标点结尾，当前段不以段落标志开头
            if (opts.merge_broken_paragraphs
                    and result
                    and result[-1].type == "paragraph"
                    and _is_cross_page_continuation(result[-1].text, cleaned)):
                result[-1].text += cleaned
                continue

            result.append(b)
        else:
            result.append(b)

    return result


# 句末标点：行以这些结尾时不应与下一行合并
_SENTENCE_END_RE = re.compile(r'[。！？；;…」』\)\)]$')
# 段落起始标志：行以这些开头时不应与上一行合并
_PARAGRAPH_START_RE = re.compile(
    r'^（\d+[)）]|^\d+[.、]\s|^第\d+章|^【|^序号|^说明[:：]|^注[:：]|^#{1,6}\s|^\d+\.\d+'
)
# 章节号标题前缀（如 "3.1.1 数据查询"）— 作为上一行时不与下一行合并
_HEADING_NUM_PREFIX_RE = re.compile(r'^\d+(?:\.\d+)+\s')


def _is_cross_page_continuation(prev_text: str, curr_text: str) -> bool:
    """判断 curr 是否是 prev 的跨页续行

    条件（同时满足）：
    1. prev 不以句末标点结尾
    2. curr 不以段落起始标志开头
    3. prev 不是标题/章节号行
    4. 两段都足够长（>10 字符），避免误合并短句/标题
    """
    prev = prev_text.strip()
    curr = curr_text.strip()
    if len(prev) < 10 or len(curr) < 10:
        return False
    if _SENTENCE_END_RE.search(prev):
        return False
    if _PARAGRAPH_START_RE.match(curr):
        return False
    # prev 是章节标题（## / #### 等或纯章节号）→ 不合并
    if re.match(r'^#{1,6}\s', prev):
        return False
    if re.match(r'^第\d+章', prev):
        return False
    # prev 是章节号标题（如 "3.1.1 数据查询"）→ 不合并
    if _HEADING_NUM_PREFIX_RE.match(prev):
        return False
    return True


def fix_list_number_positions(blocks: list[Block], options: ConvertOptions | None = None) -> list[Block]:
    """修复列表序号位置（特定模式规则）

    options.fix_list_number_positions=False 时直接返回原列表（不执行）。
    """
    opts = _opts(options)
    if not opts.fix_list_number_positions:
        return blocks

    for b in blocks:
        if b.type != "paragraph":
            continue

        text = b.text

        # 1) 移除嵌在中文之间的 "N."（页码泄漏）
        text = re.sub(r'(?<=[\u4e00-\u9fff])[ 　]*\d+\.\s*(?=[\u4e00-\u9fff])', '', text)
        b.text = text

        # 2) 修复 "操作表。 N. 表代码" → "N. 操作表代码表。"
        m = re.match(r'^([\u4e00-\u9fff]{2,4})(表[。，])\s*(\d+)\.\s+([A-Z]{2}\d+)$', text)
        if m:
            action = m.group(1)
            punct_char = m.group(2)[1]
            num = m.group(3)
            code = m.group(4)
            text = f"{num}. {action}{code}表{punct_char}"
            b.text = text
            continue

        # 3) 修复 "中文内容。 N. 表代码" → "N. 中文内容"
        m = re.search(r'([。，])\s*(\d+)\.\s+([A-Z]{2}\d+)', text)
        if m:
            num = m.group(2)
            code = m.group(3)
            before = text[:m.start()].strip()
            after = text[m.end():].strip()
            if code in before:
                text = f"{num}. {before}"
            else:
                text = f"{num}. {before}{code}"
            if after and after.strip() != code:
                text += " " + after.strip()
            b.text = text
            continue

        # 4) 修复 "中文内容 N. 表代码" → "N. 中文内容"
        m = re.search(r'([\u4e00-\u9fff])\s+(\d+)\.\s+([A-Z]{2}\d+)', text)
        if m:
            num = m.group(2)
            code = m.group(3)
            before = text[:m.start()].strip()
            last_char = m.group(1)
            after = text[m.end():].strip()
            if code in before:
                text = f"{num}. {before}{last_char}"
            else:
                text = f"{num}. {before}{last_char}{code}"
            if after and after.strip() != code:
                text += " " + after.strip()
            b.text = text
            continue

        # 5) 修复句末序号 "。 N." → "N. "（无表代码跟随）
        m = re.search(r'([。，])\s*(\d+)\.\s*$', text)
        if m:
            num = m.group(2)
            before = text[:m.start()].strip()
            text = f"{num}. {before}"
            b.text = text
            continue

        # 6) 修复 "中文 N." 在行末（无标点）
        m = re.search(r'([\u4e00-\u9fff])\s+(\d+)\.\s*$', text)
        if m:
            num = m.group(2)
            last_char = m.group(1)
            before = text[:m.start()].strip()
            text = f"{num}. {before}{last_char}"
            b.text = text

    return blocks


# 章节号正则：1.1 / 1.1.1 / 1.1.1.1 / 1.1.1.1.1 / 1.1.1.1.1.1（2~6 级）
# 不接受单独的 "1." 或 "1"（避免与列表序号冲突）
_HEADING_NUM_RE = re.compile(r'^(\d+(?:\.\d+)+)\s+(\S.*?)\s*$')
# 位置调换正则：「总体说明 1.1」 → 「1.1 总体说明」（标题在前、章节号在后）
_HEADING_SWAP_RE = re.compile(r'^(.+?)[ 　]*(\d+\.\d+(?:\.\d+)*)$')
# 章节标题文字的保守约束：不能以句号/问号/感叹号/分号结尾
_HEADING_BAD_TAIL_RE = re.compile(r'[。？！?!.;；]\s*$')
# 标题文字内部不应包含句号（避免段落首行被误判）
_HEADING_BAD_INNER_RE = re.compile(r'。')
# 标题文字最大长度（章节标题通常短，过长提示是正文）
_HEADING_MAX_TITLE_LEN = 60


def _heading_level(num: str) -> int:
    """章节号 → 标题级别：1.1→2, 1.1.1→3, 1.1.1.1.1→5"""
    return num.count('.') + 1


def _looks_like_heading_title(title: str) -> bool:
    """判断标题文字是否符合章节标题特征（保守，防误判正文）"""
    if not title:
        return False
    if len(title) > _HEADING_MAX_TITLE_LEN:
        return False
    if _HEADING_BAD_TAIL_RE.search(title):
        return False
    if _HEADING_BAD_INNER_RE.search(title):
        return False
    return True


def fix_headings(blocks: list[Block], options: ConvertOptions | None = None) -> list[Block]:
    """修复章节标题格式并添加 Markdown 标题级别前缀

    两阶段处理：
    1. 位置调换：「总体说明 1.1」 → 「1.1 总体说明」（兼容 PDF 提取顺序错乱）
    2. 级别识别：根据章节号深度添加 Markdown 前缀
       - 1.1           → H2  (## )
       - 1.1.1         → H3  (### )
       - 1.1.1.1       → H4  (#### )
       - 1.1.1.1.1     → H5  (##### )
       - 1.1.1.1.1.1   → H6  (###### )

    保守约束（避免误判正文）：
    - 章节号必须包含至少一个点（不识别单独的 "1." 或 "1"）
    - 标题文字长度 ≤ 60
    - 标题文字不以 。？！.；; 结尾
    - 标题文字内部不含 。

    options.fix_headings=False 时不执行。
    """
    opts = _opts(options)
    if not opts.fix_headings:
        return blocks

    for b in blocks:
        if b.type != "paragraph":
            continue
        text = b.text.strip()
        if not text:
            continue

        # 阶段 1：位置调换（标题在前 + 章节号在后 → 章节号在前）
        m = _HEADING_SWAP_RE.match(text)
        if m:
            title = m.group(1).strip()
            num = m.group(2).strip()
            text = f"{num} {title}"
            b.text = text

        # 阶段 2：章节号级别识别 → 添加 Markdown 前缀
        m = _HEADING_NUM_RE.match(text)
        if m:
            num = m.group(1)
            title = m.group(2).strip()
            level = _heading_level(num)
            if 2 <= level <= 6 and _looks_like_heading_title(title):
                b.text = f"{'#' * level} {num} {title}"

    return blocks


def headers_match(a: list[str], b: list[str]) -> bool:
    """判断两个表头是否一致（忽略大小写与空格）"""
    a_clean = [h.strip().lower() for h in a if h.strip()]
    b_clean = [h.strip().lower() for h in b if h.strip()]
    return a_clean == b_clean


def _header_similarity(a: list[str], b: list[str]) -> float:
    """计算两个表头的相似度（基于字符集合的 Jaccard，0-1）

    用于跨页表格第二页表头略有差异时的合并判断。
    用字符而非分词，对中文友好（"序号" 与 "序 号" 字符集合相同）。
    """
    def chars(headers: list[str]) -> set[str]:
        s = set()
        for h in headers:
            for c in h.strip().lower():
                if not c.isspace():
                    s.add(c)
        return s

    ca, cb = chars(a), chars(b)
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0
    return len(ca & cb) / len(ca | cb)


def _looks_like_data_row(block: Block) -> bool:
    """判断表格的首行是否像数据行（而非表头）——用于跨页表格第二页无表头的情况"""
    if not block.rows:
        return False
    first = block.rows[0]
    non_empty = [c.strip() for c in first if c.strip()]
    if not non_empty:
        return False
    # 含业务代码 → 数据行
    for t in non_empty:
        if CODE_PATTERN_RE.match(t):
            return True
    return False


# 特定代码正则（与 table_utils.CODE_PATTERN 一致）
CODE_PATTERN_RE = re.compile(r'[A-Za-z]{2}\d{3,}')


def merge_consecutive_tables(blocks: list[Block], options: ConvertOptions | None = None) -> list[Block]:
    """合并连续出现的表格（跨页表格）

    合并策略（按优先级）：
    1. 表头完全一致（headers_match）→ 直接合并，保留第一表头
    2. 第二个表格无表头（首行像数据行）→ 直接追加行，保留第一表头
    3. 表头相似度 ≥ 0.8（_header_similarity）→ 合并，保留第一表头
    4. 否则不合并

    options.merge_cross_page_tables=False 时不执行。
    """
    opts = _opts(options)
    if not opts.merge_cross_page_tables:
        return blocks

    if len(blocks) < 2:
        return blocks

    result: list[Block] = []
    i = 0
    while i < len(blocks):
        current = blocks[i]
        if current.type != "table" or i + 1 >= len(blocks):
            result.append(current)
            i += 1
            continue

        nxt = blocks[i + 1]
        if nxt.type != "table":
            result.append(current)
            i += 1
            continue

        # 判断是否应合并
        should_merge = False
        merged_rows = nxt.rows

        if headers_match(current.headers, nxt.headers):
            # 1. 完全一致
            should_merge = True
        elif _looks_like_data_row(nxt):
            # 2. 第二个表格无表头（首行像数据行）→ 全部当数据行追加
            should_merge = True
        elif _header_similarity(current.headers, nxt.headers) >= 0.8:
            # 3. 相似度高 → 合并，但第二个表格的首行若像表头则跳过
            if _looks_like_data_row(nxt) or not headers_match(nxt.headers, nxt.rows[0] if nxt.rows else []):
                should_merge = True
            # 若第二个表格首行像表头，跳过首行
            if should_merge and nxt.rows and not _looks_like_data_row(nxt):
                # 首行与表头相似 → 跳过
                if _header_similarity(nxt.headers, list(nxt.rows[0])) >= 0.8:
                    merged_rows = nxt.rows[1:]

        if should_merge:
            merged = Block(
                type="table",
                y_top=current.y_top,
                headers=current.headers,
                rows=current.rows + merged_rows,
            )
            # 尝试继续合并后续相同表头的表格（链式合并）
            i += 2
            while i < len(blocks) and blocks[i].type == "table" and headers_match(current.headers, blocks[i].headers):
                merged.rows += blocks[i].rows
                i += 1
            result.append(merged)
        else:
            result.append(current)
            i += 1
    return result

