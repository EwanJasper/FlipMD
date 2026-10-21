# FlipMD

**FlipMD** 是一款把 **PDF / Word（.docx）转换为 Markdown** 的本地工具，专为中文技术文档优化：复杂表格、跨页表格、错位的序号与章节标题都能被正确处理。全程本地运行，不上传任何文件。

提供四种使用方式：

| 方式 | 适合场景 | 入口 |
|---|---|---|
| 桌面应用 | 日常转换：可视化预览、原文对照、任务历史 | `FlipMD.exe` / `flipmd` |
| 命令行 | 脚本化、批量处理 | `pdf2md` |
| MCP Server | 接入 ZCode / Claude 等 AI 助手 | `flipmd-mcp` |
| Python API | 集成到自己的代码 | `engine.parse` + `render` |

## 功能特性

**转换核心**

- 双格式支持：文本型 PDF 与 Word（.docx），保留阅读顺序
- 表格提取为 GFM 表格，自动合并跨页表格，扁平化多级表头并推断空表头
- 自动过滤页码 / 页脚干扰内容，单页解析失败不影响整体

**中文排版优化**

- 去除中文间多余空格，合并 PDF 换行导致的断裂段落
- 修复错位的列表序号与章节标题，并按章节号深度输出 H2–H6 标题级别

**实用功能**

- 批量转换、文件夹导入、多文档合并为单个 Markdown（每文档独立章节）
- 文档智能摘要（大纲 + 每章预览）、可选 YAML 元数据头、图片提取、HTML 输出
- 桌面应用支持拖拽导入、原文 / Markdown 对照、连续滚动预览与双向同步滚动、任务历史
- MCP Server 提供 5 个工具，供 AI 助手通过标准协议调用

## 效果对比

| 原始文档问题 | 转换后修复 |
|---|---|
| `单位公 共基础 信息采 集` | `单位公共基础信息采集` |
| `删除表。 1. TB01` | `1. 删除TB01表。` |
| `信 1.息记录。` | `信息记录。` |
| `总体说明 1.1` | `1.1 总体说明` |
| `新增TB02...单位修改 2. TB02` | `2. 新增TB02...单位修改` |

## 快速开始

环境要求：Python ≥ 3.10，推荐使用 [uv](https://docs.astral.sh/uv/)。

### 方式一：桌面应用（推荐）

**Windows**：从 [Releases](https://github.com/EwanJasper/FlipMD/releases) 下载便携版压缩包，解压后运行 `FlipMD\FlipMD.exe`。需要 WebView2 Runtime（Windows 11 自带；缺失时应用会给出明确提示）。

**macOS / 从源码运行**：

```bash
git clone https://github.com/EwanJasper/FlipMD.git
cd FlipMD
uv run --python 3.12 --frozen --extra desktop flipmd
```

macOS 也可在克隆后直接双击 `启动FlipMD.command`。

### 方式二：命令行

```bash
uv sync

# 转换单个文件（--business-mode 针对中文技术文档开启序号 / 表头修复）
uv run pdf2md convert input.pdf -o output.md --business-mode

# 批量转换目录
uv run pdf2md batch docs/ -o output/ --recursive --name-template "{name}_{date}"

# 合并多个文档
uv run pdf2md merge a.pdf b.docx -o 合并文档.md --title "合并文档"

# 生成文档摘要 / 查看文档信息
uv run pdf2md summarize input.pdf
uv run pdf2md info input.pdf
```

常用选项：`--business-mode`、`--format md|html`、`--page-range 5-10`、`--extract-images`、`--no-ocr`、`--ocr-lang ch|en|ch_en`。

### 方式三：MCP Server

在 MCP 客户端配置（如 ZCode / Claude Desktop 的 `mcp.json`）中添加：

```json
{
  "mcpServers": {
    "flipmd": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/FlipMD", "python", "mcp_server.py"]
    }
  }
}
```

提供 5 个工具：`convert_to_markdown`（转换单个文档）、`batch_convert`（目录批量）、`merge_documents`（合并）、`summarize_document`（摘要）、`get_document_info`（文档信息）。所有错误以结构化 `{"success": false, "error": "..."}` 返回，不中断会话。

### 方式四：Python API

```python
from engine import parse            # PDF
from word_engine import parse_docx  # Word (.docx)
from markdown_writer import render

blocks = parse("文档.pdf")           # 或 parse_docx("文档.docx")
md = render(blocks, title="文档标题")
```

## 可选依赖

```bash
uv sync --extra ocr   # 扫描型 PDF 自动 OCR（PaddleOCR，体积较大）
uv sync --extra gui   # 传统 Tkinter GUI 的拖拽支持（uv run pdf2md-gui 启动）
uv sync --all-extras  # 全部安装
```

## 已知限制

- 加密 PDF 无法解析；旧版 `.doc` 格式需先另存为 `.docx`
- 扫描型 PDF 依赖可选 OCR 组件，未安装时回退文本提取，内容可能不完整
- 表头识别与序号修复为启发式规则，极少数复杂排版可能误判
- Word 原文预览为内容预览，不还原 Word 分页

## 文档

- [桌面客户端说明](docs/desktop.md) — 功能、数据位置、自检
- [Windows 构建说明](docs/windows-build.md) — 从源码构建安装包
- [v0.4.0 完整 README](docs/README-archive-v0.4.0.md) — 架构设计、实现细节与历史版本记录

## 许可证

MIT
