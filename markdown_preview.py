"""Markdown 简易预览渲染器

用 tkinter Text widget + tag 实现 Markdown 渲染，无外部依赖。
支持：标题（H1-H6）、有序/无序列表、表格、代码块、引用、加粗/斜体/删除线。
"""

from __future__ import annotations

import re
import tkinter as tk


class MarkdownPreview:
    """将 Markdown 文本渲染到 tkinter Text widget"""

    def __init__(self, text_widget: tk.Text, colors: dict):
        """
        :param text_widget: 已创建的 Text widget
        :param colors: 配色字典，需含 BG/TEXT/TEXT_SECONDARY/ACCENT/BORDER/CODE_BG 等键
        """
        self.text = text_widget
        self.colors = colors
        self._setup_tags()

    def _setup_tags(self):
        c = self.colors
        # 标题
        self.text.tag_config("h1", font=("Microsoft YaHei UI", 18, "bold"),
                             foreground=c.get("ACCENT", "#7c3aed"), spacing1=10, spacing3=6)
        self.text.tag_config("h2", font=("Microsoft YaHei UI", 16, "bold"),
                             foreground=c.get("ACCENT", "#7c3aed"), spacing1=8, spacing3=4)
        self.text.tag_config("h3", font=("Microsoft YaHei UI", 14, "bold"),
                             foreground=c.get("TEXT", "#e2e8f0"), spacing1=6, spacing3=3)
        self.text.tag_config("h4", font=("Microsoft YaHei UI", 12, "bold"),
                             foreground=c.get("TEXT", "#e2e8f0"), spacing1=4, spacing3=2)
        self.text.tag_config("h5", font=("Microsoft YaHei UI", 11, "bold"),
                             foreground=c.get("TEXT_SECONDARY", "#94a3b8"), spacing1=4, spacing3=2)
        self.text.tag_config("h6", font=("Microsoft YaHei UI", 10, "bold"),
                             foreground=c.get("TEXT_SECONDARY", "#94a3b8"), spacing1=4, spacing3=2)
        # 普通段落
        self.text.tag_config("p", font=("Microsoft YaHei UI", 10),
                             foreground=c.get("TEXT", "#e2e8f0"), spacing1=2, spacing3=2)
        # 列表
        self.text.tag_config("li", font=("Microsoft YaHei UI", 10),
                             foreground=c.get("TEXT", "#e2e8f0"), lmargin1=24, lmargin2=24,
                             spacing1=1, spacing3=1)
        self.text.tag_config("li_nested", font=("Microsoft YaHei UI", 10),
                             foreground=c.get("TEXT_SECONDARY", "#94a3b8"), lmargin1=48, lmargin2=48,
                             spacing1=1, spacing3=1)
        # 表格
        mono = ("Cascadia Code", 10)
        self.text.tag_config("table_header", font=mono,
                             foreground=c.get("ACCENT", "#7c3aed"), spacing1=2, spacing3=2)
        self.text.tag_config("table_row", font=mono,
                             foreground=c.get("TEXT", "#e2e8f0"), spacing1=1, spacing3=1)
        self.text.tag_config("table_sep", font=mono,
                             foreground=c.get("TEXT_MUTED", "#64748b"))
        # 引用
        self.text.tag_config("quote", font=("Microsoft YaHei UI", 10, "italic"),
                             foreground=c.get("TEXT_SECONDARY", "#94a3b8"),
                             lmargin1=20, lmargin2=20, spacing1=2, spacing3=2)
        # 代码块
        self.text.tag_config("code", font=mono,
                             foreground=c.get("SUCCESS", "#22c55e"),
                             background=c.get("INPUT_BG", "#1a1a2e"),
                             lmargin1=12, lmargin2=12, spacing1=2, spacing3=2)
        # 分隔线
        self.text.tag_config("hr", font=("Microsoft YaHei UI", 9),
                             foreground=c.get("TEXT_MUTED", "#64748b"))
        # 行内格式（叠加 tag）
        self.text.tag_config("bold", font=("Microsoft YaHei UI", 10, "bold"))
        self.text.tag_config("italic", font=("Microsoft YaHei UI", 10, "italic"))
        self.text.tag_config("strike", font=("Microsoft YaHei UI", 10, "overstrike"))
        self.text.tag_config("link", font=("Microsoft YaHei UI", 10, "underline"),
                             foreground=c.get("ACCENT_HOVER", "#8b5cf6"))

    def render(self, md_text: str):
        """渲染 Markdown 文本到 Text widget（清空旧内容）"""
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        if not md_text.strip():
            self.text.insert(tk.END, "(空文档)", "p")
            self.text.config(state="disabled")
            return

        lines = md_text.splitlines()
        i = 0
        in_code_block = False
        code_lines: list[str] = []

        while i < len(lines):
            line = lines[i]

            # 代码块
            if line.strip().startswith("```"):
                if in_code_block:
                    self._insert_code_block("\n".join(code_lines))
                    code_lines.clear()
                    in_code_block = False
                else:
                    in_code_block = True
                    code_lines.clear()
                i += 1
                continue
            if in_code_block:
                code_lines.append(line)
                i += 1
                continue

            # 分隔线
            if re.match(r'^---+\s*$', line) or re.match(r'^\*\*\*+\s*$', line):
                self.text.insert(tk.END, "─" * 60 + "\n", "hr")
                i += 1
                continue

            # 标题
            m = re.match(r'^(#{1,6})\s+(.*)$', line)
            if m:
                level = len(m.group(1))
                content = m.group(2).strip()
                tag = f"h{level}"
                self._insert_inline(content, base_tag=tag)
                self.text.insert(tk.END, "\n")
                i += 1
                continue

            # 引用
            if line.startswith(">"):
                content = line.lstrip(">").strip()
                self._insert_inline(content, base_tag="quote")
                self.text.insert(tk.END, "\n")
                i += 1
                continue

            # 表格（连续 | ... | 行）
            if "|" in line and i + 1 < len(lines) and re.match(r'^\s*\|?[\s\-:|]+\|?\s*$', lines[i + 1]):
                table_lines = []
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                self._insert_table(table_lines)
                continue

            # 无序列表
            m = re.match(r'^(\s*)[-*+]\s+(.*)$', line)
            if m:
                indent = len(m.group(1))
                content = m.group(2)
                tag = "li_nested" if indent >= 2 else "li"
                prefix = "• " if indent == 0 else "◦ "
                self.text.insert(tk.END, prefix, tag)
                self._insert_inline(content, base_tag=tag)
                self.text.insert(tk.END, "\n")
                i += 1
                continue

            # 有序列表
            m = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)
            if m:
                indent = len(m.group(1))
                num = m.group(2)
                content = m.group(3)
                tag = "li_nested" if indent >= 2 else "li"
                self.text.insert(tk.END, f"{num}. ", tag)
                self._insert_inline(content, base_tag=tag)
                self.text.insert(tk.END, "\n")
                i += 1
                continue

            # 空行
            if not line.strip():
                self.text.insert(tk.END, "\n", "p")
                i += 1
                continue

            # 普通段落
            self._insert_inline(line, base_tag="p")
            self.text.insert(tk.END, "\n")
            i += 1

        # 处理末尾未闭合的代码块
        if in_code_block and code_lines:
            self._insert_code_block("\n".join(code_lines))

        self.text.config(state="disabled")

    def _insert_inline(self, text: str, base_tag: str):
        """渲染行内格式（加粗/斜体/删除线/链接/代码），叠加到 base_tag"""
        # 处理顺序：先代码（避免内部被再次解析），再链接，再加粗/斜体/删除线
        # 用 token 化避免嵌套 tag 错位
        tokens = self._tokenize_inline(text)
        for tok in tokens:
            if tok["type"] == "text":
                self.text.insert(tk.END, tok["content"], base_tag)
            elif tok["type"] == "code":
                self.text.insert(tk.END, tok["content"], (base_tag, "code"))
            elif tok["type"] == "link":
                # 显示文字
                self.text.insert(tk.END, tok["text"], (base_tag, "link"))
            elif tok["type"] == "bold":
                self.text.insert(tk.END, tok["content"], (base_tag, "bold"))
            elif tok["type"] == "italic":
                self.text.insert(tk.END, tok["content"], (base_tag, "italic"))
            elif tok["type"] == "strike":
                self.text.insert(tk.END, tok["content"], (base_tag, "strike"))

    def _tokenize_inline(self, text: str) -> list[dict]:
        """将行内文本切成 token"""
        tokens: list[dict] = []
        # 顺序：`code` → [text](url) → **bold** → *italic* → ~~strike~~
        # 简化：用单一正则一次性匹配所有格式
        pattern = re.compile(
            r'(?P<code>`[^`]+`)'
            r'|(?P<link>\[([^\]]+)\]\(([^)]+)\))'
            r'|(?P<bold>\*\*[^*]+\*\*)'
            r'|(?P<italic>\*[^*]+\*)'
            r'|(?P<strike>~~[^~]+~~)'
        )
        pos = 0
        for m in pattern.finditer(text):
            if m.start() > pos:
                tokens.append({"type": "text", "content": text[pos:m.start()]})
            if m.group("code"):
                tokens.append({"type": "code", "content": m.group("code")[1:-1]})
            elif m.group("link"):
                tokens.append({"type": "link", "text": m.group(3), "url": m.group(4)})
            elif m.group("bold"):
                tokens.append({"type": "bold", "content": m.group("bold")[2:-2]})
            elif m.group("italic"):
                tokens.append({"type": "italic", "content": m.group("italic")[1:-1]})
            elif m.group("strike"):
                tokens.append({"type": "strike", "content": m.group("strike")[2:-2]})
            pos = m.end()
        if pos < len(text):
            tokens.append({"type": "text", "content": text[pos:]})
        return tokens

    def _insert_table(self, table_lines: list[str]):
        """渲染 Markdown 表格"""
        if len(table_lines) < 2:
            for line in table_lines:
                self.text.insert(tk.END, line + "\n", "table_row")
            return

        def parse_row(line: str) -> list[str]:
            line = line.strip()
            if line.startswith("|"):
                line = line[1:]
            if line.endswith("|"):
                line = line[:-1]
            return [c.strip() for c in line.split("|")]

        headers = parse_row(table_lines[0])
        # table_lines[1] 是分隔行（|---|---|），跳过
        rows = [parse_row(line) for line in table_lines[2:]]

        # 计算每列最大宽度
        col_count = len(headers)
        widths = [len(h) for h in headers]
        for row in rows:
            for j, cell in enumerate(row[:col_count]):
                widths[j] = max(widths[j], len(cell))

        def format_row(cells: list[str]) -> str:
            parts = []
            for j in range(col_count):
                cell = cells[j] if j < len(cells) else ""
                parts.append(cell.ljust(widths[j]))
            return "| " + " | ".join(parts) + " |"

        # 表头
        self.text.insert(tk.END, format_row(headers) + "\n", "table_header")
        # 分隔
        sep = "| " + " | ".join("-" * w for w in widths) + " |"
        self.text.insert(tk.END, sep + "\n", "table_sep")
        # 数据行
        for row in rows:
            self.text.insert(tk.END, format_row(row) + "\n", "table_row")

    def _insert_code_block(self, code: str):
        """渲染代码块"""
        for line in code.splitlines():
            self.text.insert(tk.END, line + "\n", "code")


def load_markdown_file(path: str) -> str | None:
    """加载 Markdown 文件内容"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None
