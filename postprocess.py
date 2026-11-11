"""通用后处理函数

对 list[Block] 进行清洗与修复，与输入格式（PDF/Word）无关。
PDF 引擎和 Word 引擎共用此模块。

每个函数接受可选的 options: ConvertOptions，按开关决定是否执行对应规则。
不传 options 时使用 ConvertOptions.default()（保守，业务规则默认关）。

注意：为保证黄金样本回归测试通过，业务文档需显式传 ConvertOptions.business()。
"""

import re
import string
from collections import Counter

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


# CJK 汉字 + 全角标点（拼接时视为"连续文字"，不加空格）
_CJK_CHAR_RE = re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]')


def smart_join(left: str, right: str) -> str:
    """跨行拼接两段文本，按边界字符决定是否补空格

    - 任意一侧是 CJK（汉字/全角标点）→ 直接拼接（保持中文原行为）
    - 两侧都是 ASCII 字母/数字 → 补空格（修复 "of"+"different" → "of different"）
    - 左为句读/闭括号、右为字母数字 → 补空格（"low."+"But" → "low. But"）
    - 右以开括号/引号开头且左为字母数字 → 补空格
    - 其余（右以标点开头、URL 拼接等）→ 直接拼接
    """
    head = left.strip()
    tail = right.strip()
    if not head:
        return tail
    if not tail:
        return head
    lc, rc = head[-1], tail[0]
    if _CJK_CHAR_RE.match(lc) or _CJK_CHAR_RE.match(rc):
        return head + tail
    if lc.isdigit() and rc.isdigit():
        return head + tail  # 数字接数字（跨页断开的数值）不加空格
    wordish = set(string.ascii_letters + string.digits)
    if lc in wordish and rc in wordish:
        return head + " " + tail
    if lc in ".,;:!?%)])" and rc in wordish:
        return head + " " + tail
    if lc in wordish and rc in "(\"'\u201c\u2018[(\u300a":
        return head + " " + tail
    return head + tail


def _style_conflict(a: Block, b: Block) -> bool:
    """两个段落块的字号/粗体样式不一致 → 大概率是标题与正文的关系，不应合并

    仅当双方都带字号信息（PDF 流）时生效；Word 流（字号 0）保持原行为。
    """
    if a.font_size > 0 and b.font_size > 0:
        hi = max(a.font_size, b.font_size)
        lo = min(a.font_size, b.font_size)
        if hi >= lo * 1.15:
            return True
        if a.font_bold != b.font_bold:
            return True
    return False


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

            # 折叠目录点线（". . . . 8" → " 8"）— 始终执行
            text = _collapse_dot_leaders(text)

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
                    and re.search(r'\d+\.\s*$', result[-1].text.strip())
                    and not _style_conflict(result[-1], b)):
                result[-1].text = smart_join(result[-1].text, cleaned)
                continue

            # 跨页续行合并：上一段不以句末标点结尾，当前段不以段落标志开头
            if (opts.merge_broken_paragraphs
                    and result
                    and result[-1].type == "paragraph"
                    and not _style_conflict(result[-1], b)
                    and _is_cross_page_continuation(result[-1].text, cleaned)):
                result[-1].text = smart_join(result[-1].text, cleaned)
                continue

            result.append(b)
        else:
            result.append(b)

    return result


# 句末标点：行以这些结尾时不应与下一行合并
_SENTENCE_END_RE = re.compile(r'[。！？；;…」』\)\)]$')
# 段落起始标志：行以这些开头时不应与上一行合并（含 Markdown 列表与项目符号行）
_PARAGRAPH_START_RE = re.compile(
    r'^（\d+[)）]|^\d+[.、]\s|^第\d+章|^【|^序号|^说明[:：]|^注[:：]|^#{1,6}\s|^\d+\.\d+|^-\s|^[•●○◆◇▪‣◦]\s*'
)
# 章节号标题前缀（如 "3.1.1 数据查询"）— 作为上一行时不与下一行合并
_HEADING_NUM_PREFIX_RE = re.compile(r'^\d+(?:\.\d+)+\s')
# Markdown 列表 / 项目符号行（行首为 "- " 或常见 bullet 字符）
_BULLET_PREFIX_RE = re.compile(r'^[•●○◆◇▪‣◦]\s*')


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
    # 目录条目特征：两行都以页码数字结尾（如 "not a layout 8" + "comes later 12"）
    # → 是两条独立条目，不合并
    if re.search(r'\d$', prev) and re.search(r'\s\d{1,3}$', curr):
        return False
    # 上一段是 Markdown 列表项且当前段以大写字母开头 → 是新句不是列表续行，不合并
    # （列表项自身的换行续行通常以小写字母开头，同页内已由缩进合并处理）
    if prev.startswith("- ") and curr[:1].isupper():
        return False
    # prev 是标题（## / #### 等或纯章节号）→ 不合并
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


# ── 字号 → 标题级别检测 ─────────────────────────────────────────

# 目录点线（". . . . 8"）与超长省略号（"…….."）
_DOT_LEADER_SPACED_RE = re.compile(r'\s*(?:\.\s+){2,}\.[ \t]*')
_DOT_LEADER_UNSPACED_RE = re.compile(r'\.{6,}')
# 目录/索引条目特征检测：条目名与页码之间的引导点线（检测用，不替换）
_HAS_DOT_LEADER_RE = re.compile(r'(?:\.\s+){2,}\.|\.{4,}')


def _collapse_dot_leaders(text: str) -> str:
    """折叠目录引导点线："layout . . . . 8" → "layout 8"，超长点串归一为省略号

    仅处理 ≥3 个以空格间隔的点（正常省略号 "..." 无空格，不受影响）。
    """
    text = _DOT_LEADER_SPACED_RE.sub(' ', text)
    return _DOT_LEADER_UNSPACED_RE.sub('...', text)


# 纯装饰行：数字、点线、连字符、竖线等（章首页的巨型章号等）
_DECORATIVE_LINE_RE = re.compile(r'^[\d\s.\-–—•·|]+$')


def _apply_font_headings(blocks: list[Block]) -> list[Block]:
    """按字号/粗体特征补标题级别（面向无章节号的图书 / 英文文档）

    统计正文主字号（按字符数加权众数），满足以下条件的段落视为标题候选：
    - 字号 ≥ 正文 × 1.15；或
    - 粗体行且字号 ≥ 正文 × 0.9（目录章名等与正文同号的粗体标题）

    再用 _looks_like_heading_title 排除误判（含句号/过长/句末标点的行）。
    大字号候选按字号分层降序映射 H1..Hn；同号粗体标题排在字号层之后。
    已带 "# " 前缀的块（fix_headings 产出）跳过，编号标题让位于序号规则。

    由 engine.parse 在 fix_headings 之后调用；Word / OCR 流无字号信息，自动空转。
    """
    weighted: Counter[float] = Counter()
    for b in blocks:
        if b.type == "paragraph" and b.font_size > 0 and not b.font_bold:
            weighted[round(b.font_size, 1)] += len(b.text)
    if not weighted:
        return blocks
    body_size = weighted.most_common(1)[0][0]
    if body_size <= 0:
        return blocks

    candidates: list[tuple[Block, float, bool]] = []
    for b in blocks:
        if b.type != "paragraph" or b.font_size <= 0:
            continue
        text = b.text.strip()
        if not text or re.match(r'^#{1,6}\s', text):
            continue
        if _DECORATIVE_LINE_RE.match(text):
            continue
        is_large = b.font_size >= body_size * 1.15
        is_bold = b.font_bold and b.font_size >= body_size * 0.9
        if not (is_large or is_bold):
            continue
        if not _looks_like_heading_title(text):
            continue
        candidates.append((b, round(b.font_size, 1), is_large))

    if not candidates:
        return blocks

    size_tiers = sorted({size for _, size, is_large in candidates if is_large}, reverse=True)
    tier_level = {size: min(i + 1, 6) for i, size in enumerate(size_tiers)}
    bold_level = min(len(size_tiers) + 1, 6)

    for b, size, is_large in candidates:
        level = tier_level.get(size, bold_level) if is_large else bold_level
        text = b.text.strip()
        # 去掉标题行尾携带的页码（如 "Layout and Spacing 65"）；
        # 词数 <3 时不处理，避免误伤 "iOS 13" 这类以数字结尾的真标题
        if len(text.split()) >= 3:
            text = re.sub(r'\s+\d{1,3}$', '', text)
        b.text = f"{'#' * level} {text}"
        b.heading_level = level
    return blocks


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

