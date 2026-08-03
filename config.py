"""配置模块

ConvertOptions：控制转换行为的开关（特定模式、后处理、OCR、页码范围等）
AppConfig：应用级配置（窗口尺寸、分隔位置、输出目录、主题、最近文件）

配置持久化到 ~/.pdf2md/config.json
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".pdf2md"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class ConvertOptions:
    """转换行为开关

    通用后处理（默认开，对中文文档普遍有益）：
        remove_cjk_spaces: 去除中文间空格
        merge_broken_paragraphs: 合并断裂短行
        fix_headings: 章节标题修复（总体说明 1.1 → 1.1 总体说明）
        merge_blank_lines: 压缩连续空行为单个（渲染层，默认开）
        add_front_matter: 输出 YAML front matter 元数据头（渲染层，默认关）

    业务特化（默认关，仅对当前业务文档开 business_mode）：
        business_mode: 总开关，启用下列所有业务规则
        fix_list_number_positions: 序号位置修复（6 条正则，硬编码 [A-Z]{2}\\d{3,}）
        infer_empty_headers: 空表头推断（通用启发式：列中所有值相同→用该值作表头）

    PDF 专用：
        merge_cross_page_tables: 跨页表格合并
        filter_footer: 页脚过滤

    OCR：
        enable_ocr: 扫描型 PDF 自动 OCR
        ocr_lang: OCR 语言（ch / en / ch_en）

    页码范围：
        page_range: (start, end) 元组，None=全部
    """
    # 通用
    remove_cjk_spaces: bool = True
    merge_broken_paragraphs: bool = True
    fix_headings: bool = True
    merge_blank_lines: bool = True  # 压缩连续空行为单个（渲染层）
    add_front_matter: bool = False  # 输出 YAML front matter 元数据头（渲染层）
    # 业务特化
    business_mode: bool = False
    fix_list_number_positions: bool = False
    infer_empty_headers: bool = False
    # PDF 专用
    merge_cross_page_tables: bool = True
    filter_footer: bool = True
    # 图片提取
    extract_images: bool = False  # 默认关（会增加体积、改变输出目录结构）
    # OCR
    enable_ocr: bool = True
    ocr_lang: str = "ch"
    # 页码范围
    page_range: tuple[int, int] | None = None

    @classmethod
    def default(cls) -> "ConvertOptions":
        """默认选项（保守，不启用业务规则）"""
        return cls()

    @classmethod
    def business(cls) -> "ConvertOptions":
        """业务文档模式（启用所有业务规则）"""
        opts = cls()
        opts.business_mode = True
        opts.fix_list_number_positions = True
        opts.infer_empty_headers = True
        return opts

    def with_overrides(self, **kwargs) -> "ConvertOptions":
        """返回覆盖部分字段的新实例"""
        new = ConvertOptions(**asdict(self))
        for k, v in kwargs.items():
            if hasattr(new, k):
                setattr(new, k, v)
        return new

    def to_dict(self) -> dict:
        d = asdict(self)
        # page_range tuple → list（JSON 兼容）
        if d.get("page_range") is not None:
            d["page_range"] = list(d["page_range"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ConvertOptions":
        opts = cls()
        for k, v in d.items():
            if k == "page_range" and v is not None:
                v = tuple(v)
            if hasattr(opts, k):
                setattr(opts, k, v)
        return opts


@dataclass
class AppConfig:
    """应用级配置（GUI 状态持久化）"""
    # 窗口
    window_width: int = 840
    window_height: int = 720
    # 分隔位置（文件列表高度占比，0-1）
    list_pane_ratio: float = 0.5
    preview_pane_ratio: float = 0.33  # 左侧文件列表占比（三栏布局）
    # 输出目录（空=与源文件同目录）
    output_dir: str = ""
    # 主题（dark / light）
    theme: str = "dark"
    # 最近文件列表（最多 10 个）
    recent_files: list[str] = field(default_factory=list)
    # 转换选项
    convert_options: ConvertOptions = field(default_factory=ConvertOptions)

    def add_recent_file(self, path: str) -> None:
        """添加到最近文件列表（去重，最多 10 个）"""
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:10]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["convert_options"] = self.convert_options.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        cfg = cls()
        opts_dict = d.pop("convert_options", {})
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.convert_options = ConvertOptions.from_dict(opts_dict)
        return cfg


def load_config() -> AppConfig:
    """加载配置，文件不存在或损坏时返回默认配置"""
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig.from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError):
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    """保存配置，自动创建配置目录"""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 配置保存失败不应影响主流程
