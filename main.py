import ctypes
import os
import struct
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# 隐藏 Windows 控制台窗口（双击运行时）
try:
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
except Exception:
    pass

from config import ConvertOptions, load_config, save_config
from engine import get_page_count, parse
from markdown_preview import MarkdownPreview, load_markdown_file
from markdown_writer import render
from output_path import resolve_unique_output_path
from word_engine import parse_docx

# 可选依赖：拖拽支持（tkinterdnd2）
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False
    DND_FILES = None
    TkinterDnD = object


# ── 配色方案 ──────────────────────────────────────────────
class Colors:
    BG = "#1e1e2e"
    CARD = "#2a2a3e"
    ACCENT = "#7c3aed"
    ACCENT_HOVER = "#8b5cf6"
    ACCENT_DISABLED = "#5b21b6"
    TEXT = "#e2e8f0"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"
    SUCCESS = "#22c55e"
    ERROR = "#ef4444"
    WARN = "#f59e0b"
    BORDER = "#3a3a52"
    INPUT_BG = "#1a1a2e"
    HIGHLIGHT = "#312e81"
    ROW_PENDING = "#1a1a2e"
    ROW_DONE = "#0a2a1a"
    ROW_FAIL = "#2a0a0a"
    ROW_ACTIVE = "#1a1a3e"


class LightColors:
    BG = "#f8fafc"
    CARD = "#ffffff"
    ACCENT = "#7c3aed"
    ACCENT_HOVER = "#8b5cf6"
    ACCENT_DISABLED = "#c4b5fd"
    TEXT = "#1e293b"
    TEXT_SECONDARY = "#475569"
    TEXT_MUTED = "#94a3b8"
    SUCCESS = "#16a34a"
    ERROR = "#dc2626"
    WARN = "#d97706"
    BORDER = "#cbd5e1"
    INPUT_BG = "#f1f5f9"
    HIGHLIGHT = "#ddd6fe"
    ROW_PENDING = "#f1f5f9"
    ROW_DONE = "#dcfce7"
    ROW_FAIL = "#fee2e2"
    ROW_ACTIVE = "#e0e7ff"


COLORS_DICT = {k: v for k, v in vars(Colors).items() if not k.startswith("_")}
LIGHT_COLORS_DICT = {k: v for k, v in vars(LightColors).items() if not k.startswith("_")}


# ── 图标生成 ──────────────────────────────────────────────

def _generate_icon_ico(filepath: str):
    """生成一个 32×32 的 ICO 图标文件（纯 Python，无外部依赖）"""
    W, H = 32, 32

    def pixel(x, y):
        cx, cy = 15.5, 15.5
        dx, dy = x - cx, y - cy
        corner_r = 13
        corner_dx = max(0, abs(dx) - (cx - corner_r))
        corner_dy = max(0, abs(dy) - (cy - corner_r))
        if (corner_dx * corner_dx + corner_dy * corner_dy) > corner_r * corner_r:
            return (0, 0, 0, 0)
        doc_left, doc_right = 8, 24
        doc_top, doc_bot = 5, 27
        if doc_left <= x <= doc_right and doc_top <= y <= doc_bot:
            if 8 <= y <= 10:
                return (237, 58, 124, 255)
            if y in (12, 14, 16):
                return (148, 163, 184, 255)
            if y == 18 and x <= 20:
                return (148, 163, 184, 255)
            if 20 <= y <= 26:
                if y == 20:
                    return (237, 58, 124, 255)
                if x in (8, 13, 18, 24):
                    return (100, 100, 120, 255)
                if y in (20, 23, 26):
                    return (100, 100, 120, 255)
                return (255, 255, 255, 255)
            return (250, 250, 252, 255)
        return (237, 58, 124, 255)

    pixel_data = bytearray()
    for y in range(H - 1, -1, -1):
        for x in range(W):
            b, g, r, a = pixel(x, y)
            pixel_data.extend([b, g, r, a])

    and_mask = bytearray()
    for y in range(H - 1, -1, -1):
        byte_val = 0
        for x in range(W):
            _, _, _, a = pixel(x, y)
            if a == 0:
                byte_val |= (1 << (7 - (x % 8)))
            if x % 8 == 7:
                and_mask.append(byte_val)
                byte_val = 0
        row_bytes = (W + 7) // 8
        padding = (4 - row_bytes % 4) % 4
        and_mask.extend([0] * padding)

    bih = struct.pack(
        "<IiiHHIIiiII",
        40, W, H * 2, 1, 32, 0, 0, 0, 0, 0, 0
    )
    image_data = bih + bytes(pixel_data) + bytes(and_mask)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        W if W < 256 else 0,
        H if H < 256 else 0,
        0, 0, 1, 32, len(image_data), 22
    )
    with open(filepath, "wb") as f:
        f.write(header)
        f.write(entry)
        f.write(image_data)


def _create_window_icon(root: tk.Tk):
    try:
        ico_path = os.path.join(tempfile.gettempdir(), "pdf2md_icon.ico")
        if not os.path.exists(ico_path):
            _generate_icon_ico(ico_path)
        root.iconbitmap(ico_path)
    except Exception:
        pass


# ── 自定义按钮 ────────────────────────────────────────────

class ModernButton(tk.Canvas):
    def __init__(self, master, text, command=None, width=160, height=38,
                 bg=Colors.ACCENT, fg=Colors.TEXT, font=("Microsoft YaHei UI", 10),
                 disabled=False, **kwargs):
        super().__init__(master, width=width, height=height,
                         bg=Colors.CARD, highlightthickness=0, **kwargs)
        self.text = text
        self.command = command
        self.bg = bg
        self.fg = fg
        self.font = font
        self.width = width
        self.height = height
        self._disabled = disabled
        self._hover = False

        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._draw()

    def _draw(self):
        self.delete("all")
        r = 8
        bg = Colors.ACCENT_DISABLED if self._disabled else (self.bg if not self._hover else Colors.ACCENT_HOVER)
        self.create_rounded_rect(1, 1, self.width - 1, self.height - 1, r,
                                 fill=bg, outline=bg, tags="btn")
        self.create_text(self.width // 2, self.height // 2,
                         text=self.text, fill=Colors.TEXT,
                         font=self.font, tags="txt")

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _on_click(self, event):
        if not self._disabled and self.command:
            self.command()

    def _on_enter(self, event):
        if not self._disabled:
            self._hover = True
            self._draw()

    def _on_leave(self, event):
        self._hover = False
        self._draw()

    def set_disabled(self, disabled: bool):
        self._disabled = disabled
        self._draw()

    def set_text(self, text: str):
        self.text = text
        self._draw()


# ── 文件项 ────────────────────────────────────────────────

class FileItem:
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"

    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)
        self.status = self.PENDING
        self.page_count = 0
        self.error = ""
        self.output_path = ""


# ── 转换选项对话框 ─────────────────────────────────────────

class OptionsDialog(tk.Toplevel):
    """转换选项对话框（阶段 2.2）"""

    def __init__(self, parent, options: ConvertOptions):
        super().__init__(parent)
        self.title("转换选项")
        self.configure(bg=Colors.BG)
        self.options = ConvertOptions(**options.__dict__)
        self.result: ConvertOptions | None = None

        # 模态
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        # 增大窗口 + 允许调整大小（内容超出时可滚动）
        self.geometry("480x640")
        self.minsize(420, 520)
        self.resizable(True, True)

        # 居中到父窗口
        self.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + (pw - 480) // 2
            y = py + (ph - 640) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _build_ui(self):
        # 外层：标题 + 滚动区 + 底部按钮
        outer = tk.Frame(self, bg=Colors.BG, padx=20, pady=14)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="转换选项", fg=Colors.TEXT, bg=Colors.BG,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", pady=(0, 10))

        # 滚动容器：Canvas + 内 Frame + Scrollbar
        scroll_frame = tk.Frame(outer, bg=Colors.BG)
        scroll_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(scroll_frame, bg=Colors.BG,
                                 highlightthickness=0, borderwidth=0)
        vbar = tk.Scrollbar(scroll_frame, orient="vertical",
                            command=self._canvas.yview,
                            bg=Colors.BORDER, troughcolor=Colors.CARD)
        self._canvas.configure(yscrollcommand=vbar.set)

        vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        # 内部容器（所有选项挂这里）
        container = tk.Frame(self._canvas, bg=Colors.BG)
        self._inner_window = self._canvas.create_window((0, 0), window=container, anchor="nw")

        # 内容变化时更新 scrollregion
        def _on_inner_config(event):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        container.bind("<Configure>", _on_inner_config)

        # canvas 宽度跟随窗口，让内容横向撑满
        def _on_canvas_config(event):
            self._canvas.itemconfig(self._inner_window, width=event.width)
        self._canvas.bind("<Configure>", _on_canvas_config)

        # 鼠标滚轮
        def _on_wheel(event):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _on_wheel))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # 通用后处理组
        self._section(container, "通用后处理")
        self.var_remove_cjk = self._check(container, "去除中文间空格", self.options.remove_cjk_spaces)
        self.var_merge_broken = self._check(container, "合并断裂短行", self.options.merge_broken_paragraphs)
        self.var_fix_headings = self._check(container, "章节标题修复", self.options.fix_headings)

        # 业务模式组
        self._section(container, "业务文档模式")
        self.var_business = self._check(container, "启用业务模式（社会保单等特定文档）", self.options.business_mode)
        self.var_fix_list_num = self._check(container, "序号位置修复", self.options.fix_list_number_positions)
        self.var_infer_headers = self._check(container, "空表头推断", self.options.infer_empty_headers)

        # PDF 专用
        self._section(container, "PDF 专用")
        self.var_merge_tables = self._check(container, "跨页表格合并", self.options.merge_cross_page_tables)
        self.var_filter_footer = self._check(container, "页脚过滤", self.options.filter_footer)

        # OCR
        self._section(container, "OCR")
        # 检测 PaddleOCR 是否安装，未装则禁用 OCR 开关
        ocr_available = True
        try:
            from ocr import is_paddleocr_available
            ocr_available = is_paddleocr_available()
        except Exception:
            ocr_available = False
        if ocr_available:
            self.var_enable_ocr = self._check(container, "扫描型 PDF 自动 OCR", self.options.enable_ocr)
        else:
            self.var_enable_ocr = self._check(
                container, "扫描型 PDF 自动 OCR（未安装 PaddleOCR）", False, disabled=True
            )
            self.var_enable_ocr.set(False)
        ocr_lang_row = tk.Frame(container, bg=Colors.BG)
        ocr_lang_row.pack(fill="x", pady=(4, 0))
        tk.Label(ocr_lang_row, text="OCR 语言:", fg=Colors.TEXT_SECONDARY, bg=Colors.BG,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_ocr_lang = tk.StringVar(value=self.options.ocr_lang)
        lang_box = ttk.Combobox(ocr_lang_row, textvariable=self.var_ocr_lang, width=10,
                                values=["ch", "en", "ch_en"], state="readonly")
        lang_box.pack(side="left", padx=(8, 0))

        # 图片
        self._section(container, "图片")
        self.var_extract_images = self._check(container, "提取图片到 images/ 目录", self.options.extract_images)

        # 页码范围
        self._section(container, "页码范围")
        pr_row = tk.Frame(container, bg=Colors.BG)
        pr_row.pack(fill="x", pady=(4, 0))
        tk.Label(pr_row, text="范围 (如 5-10，留空=全部):", fg=Colors.TEXT_SECONDARY, bg=Colors.BG,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        pr_str = ""
        if self.options.page_range:
            pr_str = f"{self.options.page_range[0]}-{self.options.page_range[1]}"
        self.var_page_range = tk.StringVar(value=pr_str)
        tk.Entry(pr_row, textvariable=self.var_page_range, width=12,
                 bg=Colors.INPUT_BG, fg=Colors.TEXT, insertbackground=Colors.TEXT,
                 relief="flat", font=("Microsoft YaHei UI", 9)).pack(side="right")

        # 底部留点空白
        tk.Frame(container, bg=Colors.BG, height=8).pack(fill="x")

        # 按钮区（固定在底部，不滚动）
        btn_row = tk.Frame(outer, bg=Colors.BG)
        btn_row.pack(fill="x", pady=(10, 0))
        ModernButton(btn_row, text="确定", command=self._on_ok,
                     width=100, height=34, bg=Colors.ACCENT,
                     font=("Microsoft YaHei UI", 10)).pack(side="right")
        ModernButton(btn_row, text="取消", command=self._on_cancel,
                     width=100, height=34, bg=Colors.HIGHLIGHT,
                     font=("Microsoft YaHei UI", 10)).pack(side="right", padx=(0, 8))

    def _section(self, parent, title: str):
        tk.Label(parent, text=title, fg=Colors.ACCENT_HOVER, bg=Colors.BG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        sep = tk.Frame(parent, bg=Colors.BORDER, height=1)
        sep.pack(fill="x", pady=(0, 4))

    def _check(self, parent, label: str, initial: bool, disabled: bool = False) -> tk.BooleanVar:
        var = tk.BooleanVar(value=initial)
        cb = tk.Checkbutton(parent, text=label, variable=var,
                            bg=Colors.BG, fg=Colors.TEXT,
                            activebackground=Colors.BG, activeforeground=Colors.TEXT,
                            selectcolor=Colors.INPUT_BG,
                            font=("Microsoft YaHei UI", 9),
                            highlightthickness=0, bd=0)
        cb.pack(anchor="w", padx=(8, 0))
        if disabled:
            cb.configure(state="disabled")
        return var

    def _on_ok(self):
        opts = ConvertOptions()
        opts.remove_cjk_spaces = self.var_remove_cjk.get()
        opts.merge_broken_paragraphs = self.var_merge_broken.get()
        opts.fix_headings = self.var_fix_headings.get()
        opts.business_mode = self.var_business.get()
        opts.fix_list_number_positions = self.var_fix_list_num.get()
        opts.infer_empty_headers = self.var_infer_headers.get()
        opts.merge_cross_page_tables = self.var_merge_tables.get()
        opts.filter_footer = self.var_filter_footer.get()
        opts.enable_ocr = self.var_enable_ocr.get()
        opts.extract_images = self.var_extract_images.get()
        opts.ocr_lang = self.var_ocr_lang.get()
        pr = self.var_page_range.get().strip()
        if pr:
            try:
                a, b = pr.split("-")
                opts.page_range = (int(a.strip()), int(b.strip()))
            except (ValueError, AttributeError):
                messagebox.showwarning("页码范围", "页码范围格式错误，应为 5-10 这种形式", parent=self)
                return
        else:
            opts.page_range = None
        self.result = opts
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


# ── 主应用 ────────────────────────────────────────────────

class PdfToMarkdownApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF & Word → Markdown")
        self.root.configure(bg=Colors.BG)

        _create_window_icon(self.root)

        self.output_dir = tk.StringVar(value="")
        self.files: list[FileItem] = []
        self._converting = False
        self._stop_requested = False
        self._preview_job = None  # 防抖

        # 加载配置
        self.app_config = load_config()
        # 主题（暗/亮）—— 下次启动生效
        self.theme = self.app_config.theme or "dark"
        # 默认保持业务模式（兼容现有文档）；用户可通过选项面板切换
        self.convert_options = self.app_config.convert_options or ConvertOptions.business()
        if not self.convert_options.business_mode and not self._has_business_rules(self.convert_options):
            # 首次启动默认业务模式
            self.convert_options = ConvertOptions.business()
        if self.app_config.output_dir:
            self.output_dir.set(self.app_config.output_dir)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.resizable(True, True)
        self.root.minsize(1000, 640)
        w = self.app_config.window_width or 1000
        h = self.app_config.window_height or 720
        self.root.geometry(f"{w}x{h}")

    @staticmethod
    def _has_business_rules(opts: ConvertOptions) -> bool:
        return opts.business_mode or opts.fix_list_number_positions or opts.infer_empty_headers

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self):
        # 标题栏
        header = tk.Frame(self.root, bg=Colors.ACCENT, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="PDF & Word → Markdown", fg="white", bg=Colors.ACCENT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=(20, 0), pady=10)
        tk.Label(header, text="批量转换 + 实时预览", fg="#c4b5fd", bg=Colors.ACCENT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 0), pady=10)

        # 设置按钮
        ModernButton(header, text="⚙ 选项", command=self._open_options,
                     width=90, height=32, bg=Colors.HIGHLIGHT,
                     font=("Microsoft YaHei UI", 9)).pack(side="right", padx=(0, 16), pady=10)

        # 主题切换按钮
        theme_label = "☀ 亮色" if self.theme == "dark" else "🌙 暗色"
        ModernButton(header, text=theme_label, command=self._toggle_theme,
                     width=90, height=32, bg=Colors.HIGHLIGHT,
                     font=("Microsoft YaHei UI", 9)).pack(side="right", padx=(0, 8), pady=10)

        # 主容器：水平 PanedWindow（左：文件列表+操作栏；右：预览）
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill="both", expand=True, padx=12, pady=(8, 8))

        # 左侧：上下两段（文件列表 + 日志）+ 底部操作栏
        left_frame = tk.Frame(self.paned, bg=Colors.BG)
        self.paned.add(left_frame, weight=2)

        # ── 操作栏（放最底层，独立于 vpaned，拖动不影响）──
        action_card = tk.Frame(left_frame, bg=Colors.CARD, padx=12, pady=8)
        action_card.pack(fill="x", side="bottom", pady=(8, 0))
        action_card.config(highlightbackground=Colors.ACCENT, highlightthickness=1)

        dir_row = tk.Frame(action_card, bg=Colors.CARD)
        dir_row.pack(fill="x")

        tk.Label(dir_row, text="输出目录:", fg=Colors.TEXT_SECONDARY, bg=Colors.CARD,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")

        self.dir_label = tk.Label(dir_row, text="与源文件相同目录", anchor="w",
                                  fg=Colors.TEXT_SECONDARY, bg=Colors.CARD,
                                  font=("Microsoft YaHei UI", 9))
        self.dir_label.pack(side="left", fill="x", expand=True, padx=(10, 0))

        ModernButton(dir_row, text="选择目录", command=self._select_output_dir,
                     width=90, height=28, bg=Colors.HIGHLIGHT,
                     font=("Microsoft YaHei UI", 9)).pack(side="right")

        sep = tk.Frame(action_card, bg=Colors.BORDER, height=1)
        sep.pack(fill="x", pady=(8, 6))

        btn_row = tk.Frame(action_card, bg=Colors.CARD)
        btn_row.pack(fill="x")

        # ── vpaned（文件列表 + 日志），上下拖动只影响这两块 ──
        self.vpaned = ttk.PanedWindow(left_frame, orient=tk.VERTICAL)
        self.vpaned.pack(fill="both", expand=True)

        # 文件列表卡片
        list_card = self._make_card(self.vpaned, "文件列表")
        self.vpaned.add(list_card, weight=3)

        # 文件列表顶部操作栏（添加/清空）
        toolbar = tk.Frame(list_card, bg=Colors.CARD)
        toolbar.pack(fill="x", pady=(0, 8))

        btn_w = 110
        ModernButton(toolbar, text="添加文件", command=self._add_files,
                     width=btn_w, height=30, font=("Microsoft YaHei UI", 9)).pack(side="left")
        ModernButton(toolbar, text="添加文件夹", command=self._add_folder,
                     width=btn_w, height=30, bg=Colors.HIGHLIGHT,
                     font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(6, 0))

        self._clear_btn = ModernButton(toolbar, text="清空列表", command=self._clear_list,
                                       width=btn_w, height=30, bg=Colors.ERROR,
                                       font=("Microsoft YaHei UI", 9), disabled=True)
        self._clear_btn.pack(side="left", padx=(6, 0))

        self._count_label = tk.Label(toolbar, text="共 0 个文件", anchor="e",
                                     fg=Colors.TEXT_SECONDARY, bg=Colors.CARD,
                                     font=("Microsoft YaHei UI", 9))
        self._count_label.pack(side="right", fill="x", expand=True)

        # 文件列表
        list_frame = tk.Frame(list_card, bg=Colors.INPUT_BG)
        list_frame.pack(fill="both", expand=True)

        self._listbox = tk.Listbox(
            list_frame, bg=Colors.INPUT_BG, fg=Colors.TEXT,
            selectbackground=Colors.HIGHLIGHT, selectforeground=Colors.TEXT,
            relief="flat", highlightthickness=0, borderwidth=0,
            font=("Microsoft YaHei UI", 10)
        )
        self._listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame, bg=Colors.BORDER, troughcolor=Colors.CARD)
        scrollbar.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self._listbox.yview)

        # 选中文件 → 加载预览
        self._listbox.bind("<<ListboxSelect>>", self._on_select_file)
        self._listbox.bind("<Double-Button-1>", self._on_double_click_file)

        # 右键菜单
        self._ctx_menu = tk.Menu(self.root, tearoff=0, bg=Colors.CARD, fg=Colors.TEXT,
                                 activebackground=Colors.HIGHLIGHT, activeforeground=Colors.TEXT)
        self._ctx_menu.add_command(label="移除选中", command=self._remove_selected)
        self._ctx_menu.add_command(label="清空列表", command=self._clear_list)
        self._listbox.bind("<Button-3>", self._on_context_menu)

        self.convert_btn = ModernButton(
            btn_row, text="开始转换", command=self._start_convert,
            width=130, height=38, bg=Colors.ACCENT,
            font=("Microsoft YaHei UI", 11, "bold"), disabled=True
        )
        self.convert_btn.pack(side="left")

        self.stop_btn = ModernButton(
            btn_row, text="停止", command=self._stop_convert,
            width=80, height=34, bg=Colors.ERROR,
            font=("Microsoft YaHei UI", 9), disabled=True
        )
        self.stop_btn.pack(side="left", padx=(8, 0))

        self.open_btn = ModernButton(
            btn_row, text="打开输出目录", command=self._open_output_dir,
            width=120, height=34, bg=Colors.SUCCESS,
            font=("Microsoft YaHei UI", 9), disabled=True
        )
        self.open_btn.pack(side="left", padx=(8, 0))

        self._progress_frame = tk.Frame(btn_row, bg=Colors.CARD)
        self._progress_frame.pack(side="right", fill="x", expand=True, padx=(10, 0))

        self._progress_label = tk.Label(self._progress_frame, text="", anchor="e",
                                        fg=Colors.TEXT_SECONDARY, bg=Colors.CARD,
                                        font=("Microsoft YaHei UI", 9))
        self._progress_label.pack(side="bottom", fill="x")

        self.progress = ttk.Progressbar(self._progress_frame, mode="determinate", length=160)
        self.progress.pack(side="bottom", pady=(0, 2))
        self.progress.pack_forget()

        # 日志卡片
        log_card = self._make_card(self.vpaned, "处理日志")
        self.vpaned.add(log_card, weight=2)

        self.log_area = tk.Text(
            log_card, wrap=tk.WORD, state="disabled",
            bg=Colors.INPUT_BG, fg=Colors.TEXT_SECONDARY,
            font=("Cascadia Code", 10, "normal"),
            relief="flat", padx=8, pady=6,
            insertbackground=Colors.TEXT,
            highlightthickness=0, borderwidth=0
        )
        self.log_area.pack(side="left", fill="both", expand=True)

        scrollbar2 = tk.Scrollbar(log_card, bg=Colors.BORDER, troughcolor=Colors.CARD)
        scrollbar2.pack(side="right", fill="y")
        self.log_area.config(yscrollcommand=scrollbar2.set)
        scrollbar2.config(command=self.log_area.yview)

        # 日志右键菜单（复制/复制全部/导出）
        self._log_menu = tk.Menu(self.root, tearoff=0, bg=Colors.CARD, fg=Colors.TEXT,
                                 activebackground=Colors.HIGHLIGHT, activeforeground=Colors.TEXT)
        self._log_menu.add_command(label="复制选中", command=self._copy_log_selection)
        self._log_menu.add_command(label="复制全部", command=self._copy_log_all)
        self._log_menu.add_separator()
        self._log_menu.add_command(label="导出到文件", command=self._export_log)
        self.log_area.bind("<Button-3>", self._on_log_context_menu)

        # 右侧：Markdown 预览面板
        preview_card = self._make_card(self.paned, "Markdown 预览（选中已完成文件查看）")
        self.paned.add(preview_card, weight=3)

        # 预览工具栏
        preview_toolbar = tk.Frame(preview_card, bg=Colors.CARD)
        preview_toolbar.pack(fill="x", pady=(0, 4))

        self._preview_path_label = tk.Label(
            preview_toolbar, text="（未选择文件）", anchor="w",
            fg=Colors.TEXT_MUTED, bg=Colors.CARD,
            font=("Microsoft YaHei UI", 9)
        )
        self._preview_path_label.pack(side="left", fill="x", expand=True)

        ModernButton(preview_toolbar, text="刷新", command=self._refresh_preview,
                     width=70, height=26, bg=Colors.HIGHLIGHT,
                     font=("Microsoft YaHei UI", 9)).pack(side="right")

        # 预览 Text widget
        preview_frame = tk.Frame(preview_card, bg=Colors.INPUT_BG)
        preview_frame.pack(fill="both", expand=True)

        self.preview_text = tk.Text(
            preview_frame, wrap=tk.WORD, state="disabled",
            bg=Colors.INPUT_BG, fg=Colors.TEXT,
            font=("Microsoft YaHei UI", 10),
            relief="flat", padx=12, pady=8,
            insertbackground=Colors.TEXT,
            highlightthickness=0, borderwidth=0,
            cursor="arrow"
        )
        self.preview_text.pack(side="left", fill="both", expand=True)

        preview_scroll = tk.Scrollbar(preview_frame, bg=Colors.BORDER, troughcolor=Colors.CARD)
        preview_scroll.pack(side="right", fill="y")
        self.preview_text.config(yscrollcommand=preview_scroll.set)
        preview_scroll.config(command=self.preview_text.yview)

        self.preview = MarkdownPreview(self.preview_text, COLORS_DICT)
        self.preview.render("")

        # 恢复分隔位置
        try:
            ratio = self.app_config.preview_pane_ratio or 0.33
            self.root.after(150, lambda: self._restore_pane_ratio(ratio))
        except Exception:
            pass

    def _restore_pane_ratio(self, ratio: float):
        """恢复左右分隔位置"""
        try:
            total = self.paned.winfo_width()
            if total > 100:
                left_w = int(total * ratio)
                self.paned.sashpos(0, left_w)
        except Exception:
            pass

    # ── 辅助方法 ──────────────────────────────────────────

    def _make_card(self, parent, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=Colors.CARD, padx=14, pady=10)
        card.config(highlightbackground=Colors.BORDER, highlightthickness=1)
        if title:
            tk.Label(card, text=title, fg=Colors.TEXT_SECONDARY, bg=Colors.CARD,
                     font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        return card

    def _log(self, message: str, tag: str = "info"):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n", tag)
        self.log_area.tag_config("warn", foreground=Colors.WARN)
        self.log_area.tag_config("success", foreground=Colors.SUCCESS)
        self.log_area.tag_config("error", foreground=Colors.ERROR)
        self.log_area.tag_config("divider", foreground=Colors.TEXT_MUTED)
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")
        self.root.update_idletasks()

    def _on_log_context_menu(self, event):
        self._log_menu.post(event.x_root, event.y_root)

    def _copy_log_selection(self):
        try:
            text = self.log_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass

    def _copy_log_all(self):
        text = self.log_area.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _export_log(self):
        path = filedialog.asksaveasfilename(
            title="导出日志",
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_area.get("1.0", tk.END))
            self._log(f"✓ 日志已导出到 {path}", "success")
        except OSError as e:
            self._log(f"✗ 导出失败: {e}", "error")

    def _format_size(self, size_bytes: float) -> str:
        for unit in ["B", "KB", "MB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} GB"

    # ── 文件列表管理 ──────────────────────────────────────

    def _refresh_list(self):
        self._listbox.delete(0, tk.END)
        for f in self.files:
            icon = self._status_icon(f.status)
            pages = str(f.page_count) if f.page_count else "-"
            result = f.error[:40] if f.status == FileItem.FAILED else ("✓" if f.status == FileItem.DONE else "")
            display = f"{icon}  {f.name:<55s} {pages:>4s}  {result}"
            self._listbox.insert(tk.END, display)

            bg_map = {
                FileItem.PENDING: Colors.ROW_PENDING,
                FileItem.PROCESSING: Colors.ROW_ACTIVE,
                FileItem.DONE: Colors.ROW_DONE,
                FileItem.FAILED: Colors.ROW_FAIL,
            }
            self._listbox.itemconfig(tk.END, bg=bg_map.get(f.status, Colors.ROW_PENDING))

        count = len(self.files)
        done = sum(1 for f in self.files if f.status == FileItem.DONE)
        self._count_label.config(text=f"共 {count} 个文件  (已完成 {done})")
        self.convert_btn.set_disabled(count == 0 or self._converting)
        self._clear_btn.set_disabled(count == 0)

    def _status_icon(self, status: str) -> str:
        return {"pending": "○", "processing": "◉", "done": "●", "failed": "●"}.get(status, "○")

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择文档文件",
            filetypes=[
                ("文档文件", "*.pdf *.docx"),
                ("PDF 文件", "*.pdf"),
                ("Word 文件", "*.docx"),
                ("所有文件", "*.*"),
            ]
        )
        if not paths:
            return
        existing = {f.path for f in self.files}
        added = 0
        for p in paths:
            if p not in existing:
                self.files.append(FileItem(p))
                existing.add(p)
                added += 1
        if added:
            self._log(f"✓ 添加 {added} 个文件")
            self._refresh_list()

    def _add_folder(self):
        folder = filedialog.askdirectory(title="选择包含文档的文件夹")
        if not folder:
            return
        existing = {f.path for f in self.files}
        added = 0
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith((".pdf", ".docx")):
                path = os.path.join(folder, fname)
                if path not in existing:
                    self.files.append(FileItem(path))
                    existing.add(path)
                    added += 1
        if added:
            self._log(f"✓ 从文件夹添加 {added} 个文档文件")
            self._refresh_list()

    def _remove_selected(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.files):
            self.files.pop(idx)
            self._refresh_list()

    def _clear_list(self):
        if not self.files:
            return
        if not messagebox.askyesno("确认", "确定清空文件列表？"):
            return
        self.files.clear()
        self._refresh_list()
        self._log("已清空文件列表")

    def _on_context_menu(self, event):
        self._ctx_menu.post(event.x_root, event.y_root)

    def _on_select_file(self, event):
        """选中文件 → 加载预览"""
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if not (0 <= idx < len(self.files)):
            return
        f = self.files[idx]
        if f.status == FileItem.DONE and f.output_path and os.path.exists(f.output_path):
            self._load_preview(f.output_path)
        elif f.status == FileItem.FAILED:
            self.preview.render(f"*[转换失败: {f.error}]*")
            self._preview_path_label.config(text=f"{f.name} — 失败", fg=Colors.ERROR)
        else:
            self.preview.render(f"*[{f.name} 尚未转换]*")
            self._preview_path_label.config(text=f"{f.name} — 未转换", fg=Colors.TEXT_MUTED)

    def _on_double_click_file(self, event):
        """双击已完成文件 → 打开输出目录"""
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.files):
            f = self.files[idx]
            if f.output_path and os.path.exists(f.output_path):
                if sys.platform == "win32":
                    os.startfile(f.output_path)

    def _load_preview(self, md_path: str):
        md = load_markdown_file(md_path)
        if md is None:
            self.preview.render("*[无法读取 Markdown 文件]*")
            return
        self._preview_path_label.config(text=os.path.basename(md_path), fg=Colors.TEXT)
        self.preview.render(md)

    def _refresh_preview(self):
        """刷新当前预览"""
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.files):
            f = self.files[idx]
            if f.output_path and os.path.exists(f.output_path):
                self._load_preview(f.output_path)

    # ── 选项面板 ──────────────────────────────────────────

    def _open_options(self):
        dlg = OptionsDialog(self.root, self.convert_options)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.convert_options = dlg.result
            self._log(f"⚙ 选项已更新（业务模式: {'开' if dlg.result.business_mode else '关'}）")

    def _toggle_theme(self):
        """切换主题（下次启动生效）"""
        new_theme = "light" if self.theme == "dark" else "dark"
        self.theme = new_theme
        self.app_config.theme = new_theme
        try:
            save_config(self.app_config)
        except Exception:
            pass
        if messagebox.askyesno("主题已切换",
                               f"主题已切换为「{'亮色' if new_theme == 'light' else '暗色'}」。\n"
                               f"需要重启应用才能生效。\n\n是否立即重启？"):
            # 重启：新开进程后退出当前
            try:
                subprocess.Popen([sys.executable, os.path.abspath(__file__)])
            except Exception:
                pass
            self.root.destroy()

    # ── 输出设置 ──────────────────────────────────────────

    def _select_output_dir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)
            self.dir_label.config(text=path, fg=Colors.TEXT)

    def _get_output_path(self, src_path: str) -> str:
        out_dir = self.output_dir.get() or None
        return resolve_unique_output_path(out_dir, src_path, ext=".md")

    # ── 转换逻辑 ──────────────────────────────────────────

    def _start_convert(self):
        pending = [f for f in self.files if f.status != FileItem.DONE]
        if not pending:
            messagebox.showinfo("提示", "没有待处理的文件")
            return

        self._converting = True
        self._stop_requested = False
        self.convert_btn.set_disabled(True)
        self.convert_btn.set_text("转换中...")
        self.stop_btn.set_disabled(False)
        self.progress.pack(side="bottom", pady=(0, 2))
        self.progress["maximum"] = len(pending)
        self.progress["value"] = 0

        self._log("=" * 50)
        self._log(f"开始批量转换，共 {len(pending)} 个文件")

        thread = threading.Thread(target=self._do_batch_convert, daemon=True)
        thread.start()

    def _stop_convert(self):
        self._stop_requested = True
        self._log("⚠ 用户请求停止...")

    def _do_batch_convert(self):
        pending = [f for f in self.files if f.status != FileItem.DONE]
        total = len(pending)
        done_count = 0

        for idx, f in enumerate(pending):
            if self._stop_requested:
                break

            f.status = FileItem.PROCESSING
            self.root.after(0, self._refresh_list)
            self.root.after(0, lambda i=idx, t=total, n=f.name: self._progress_label.config(
                text=f"正在处理: {n}  ({i + 1}/{t})"))

            try:
                file_size = os.path.getsize(f.path)
                size_str = self._format_size(file_size)

                self._log(f"[{idx + 1}/{total}] {f.name}  ({size_str})")

                ext = os.path.splitext(f.path)[1].lower()
                if ext == ".pdf":
                    try:
                        f.page_count = get_page_count(f.path)
                    except Exception:
                        f.page_count = 0
                    blocks = parse(f.path, self.convert_options)
                elif ext == ".docx":
                    f.page_count = 0
                    blocks = parse_docx(f.path, self.convert_options)
                elif ext == ".doc":
                    raise ValueError("不支持 .doc 格式，请先用 Word 另存为 .docx")
                else:
                    raise ValueError(f"不支持的文件格式: {ext}")

                # 图片提取（受选项开关控制）
                img_count = 0
                if self.convert_options.extract_images:
                    try:
                        from image_extract import extract_images
                        # 先确定输出路径，图片导出到同级 images/
                        tmp_output = self._get_output_path(f.path)
                        img_blocks = extract_images(f.path, tmp_output)
                        if img_blocks:
                            blocks = blocks + img_blocks
                            blocks.sort(key=lambda b: b.y_top)
                            img_count = len(img_blocks)
                            self._log(f"  📷 提取 {img_count} 张图片到 images/")
                    except Exception as img_e:
                        self._log(f"  ⚠ 图片提取失败: {img_e}", "warn")

                title = os.path.splitext(f.name)[0]
                md_content = render(blocks, title=title)

                output_path = self._get_output_path(f.path)
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as out_f:
                    out_f.write(md_content)

                f.output_path = output_path
                f.status = FileItem.DONE
                done_count += 1

                # 加入最近文件
                self.app_config.add_recent_file(f.path)

                total_tables = sum(1 for b in blocks if b.type == "table")
                total_paras = sum(1 for b in blocks if b.type == "paragraph")
                line_count = len(md_content.splitlines())
                page_info = f"{f.page_count} 页" if f.page_count else "-"
                self._log(f"  ✓ {page_info} | {total_paras} 段 | {total_tables} 表 | {line_count} 行", "success")

            except Exception as e:
                f.status = FileItem.FAILED
                f.error = str(e)[:60]
                self._log(f"  ✗ 失败: {e}", "error")
                import traceback
                self._log(traceback.format_exc(), "error")

            self.root.after(0, self._refresh_list)
            self.root.after(0, lambda: self.progress.step(1))

        self.root.after(0, self._on_batch_done, done_count, total)

    def _on_batch_done(self, done_count: int, total: int):
        self._converting = False
        self.stop_btn.set_disabled(True)
        self.convert_btn.set_text("开始转换")
        self.convert_btn.set_disabled(len(self.files) == 0)

        if self._stop_requested:
            self._log(f"⏹ 已停止，已完成 {done_count}/{total} 个文件", "warn")
        else:
            failed = total - done_count
            if failed == 0:
                self._log(f"✓ 全部完成！{done_count}/{total} 个文件转换成功", "success")
            else:
                self._log(f"✓ 完成 {done_count}/{total} 个，{failed} 个失败", "warn")

        self.progress.pack_forget()
        self._progress_label.config(text="")

        if done_count > 0:
            self.open_btn.set_disabled(False)

        # 自动预览第一个完成的文件
        for f in self.files:
            if f.status == FileItem.DONE and f.output_path:
                # 选中该文件触发预览
                idx = self.files.index(f)
                self._listbox.selection_clear(0, tk.END)
                self._listbox.selection_set(idx)
                self._load_preview(f.output_path)
                break

    # ── 其他 ──────────────────────────────────────────────

    def _open_output_dir(self):
        done_files = [f for f in self.files if f.status == FileItem.DONE and f.output_path]
        if done_files:
            out_dir = os.path.dirname(done_files[0].output_path)
        else:
            out_dir = self.output_dir.get() or os.getcwd()
        if not os.path.exists(out_dir):
            return
        if sys.platform == "win32":
            os.startfile(out_dir)
        elif sys.platform == "darwin":
            subprocess.run(["open", out_dir], check=False)
        else:
            subprocess.run(["xdg-open", out_dir], check=False)

    def _on_close(self):
        """关闭窗口时保存配置"""
        try:
            self.app_config.output_dir = self.output_dir.get()
            self.app_config.window_width = self.root.winfo_width()
            self.app_config.window_height = self.root.winfo_height()
            # 保存左右分隔比例
            try:
                total = self.paned.winfo_width()
                if total > 100:
                    self.app_config.preview_pane_ratio = self.paned.sashpos(0) / total
            except Exception:
                pass
            self.app_config.convert_options = self.convert_options
            save_config(self.app_config)
        except Exception:
            pass
        self.root.destroy()


def _apply_theme(theme: str):
    """启动时根据主题覆盖 Colors 类属性"""
    if theme == "light":
        for k, v in LIGHT_COLORS_DICT.items():
            setattr(Colors, k, v)
        # 同步 COLORS_DICT（传给 MarkdownPreview 的字典）
        COLORS_DICT.update(LIGHT_COLORS_DICT)


def main():
    # 先加载配置以决定主题
    cfg = load_config()
    _apply_theme(cfg.theme or "dark")

    # 优先用 TkinterDnD.Tk（支持拖拽），否则普通 Tk
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    # ttk 样式（让 PanedWindow 与暗色主题协调）
    style = ttk.Style()
    try:
        style.theme_use("clam")
        style.configure("TPanedwindow", background=Colors.BG)
        style.configure("Sash", background=Colors.BORDER, borderwidth=2, sashthickness=6)
    except Exception:
        pass

    app = PdfToMarkdownApp(root)

    # 拖拽支持：拖文件到窗口添加
    if HAS_DND:
        def _on_drop(event):
            # event.data 形如 {C:/path/to/file.pdf} {C:/path/to/another.docx}
            raw = event.data
            # 去掉花括号，按 } { 切分
            paths = []
            for piece in raw.split("}"):
                p = piece.strip().lstrip("{").strip()
                if p:
                    paths.append(p)
            existing = {f.path for f in app.files}
            added = 0
            for p in paths:
                if p.lower().endswith((".pdf", ".docx")) and p not in existing:
                    app.files.append(FileItem(p))
                    existing.add(p)
                    added += 1
            if added:
                app._log(f"✓ 拖拽添加 {added} 个文件")
                app._refresh_list()
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", _on_drop)

    root.mainloop()


if __name__ == "__main__":
    main()
