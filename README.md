# PDF & Word → Markdown 转换工具

一款基于 Python 的 **PDF / Word（.docx）转 Markdown** 工具，专为**中文技术文档**（含复杂表格）设计。支持**批量处理**，提供现代化暗色主题 GUI，将文档中的文字段落和表格提取为规范的 Markdown 文件。

## 功能特性

- **双格式支持** — 同时支持 PDF（文本型）和 Word（.docx）文档
- **段落提取** — 提取文字段落，保留阅读顺序
- **表格检测** — 自动识别表格区域，提取为 GFM（GitHub Flavored Markdown）表格
- **跨页表格合并** — 自动合并 PDF 中跨页且表头相同的表格
- **智能表头处理** — 扁平化多级表头、自动推断空表头（列中所有值相同则用该值作表头）
- **中文排版优化** — 去除中文间的多余空格，修复 PDF 换行导致的断词
- **序号位置修复** — 将排版中错位的列表序号（如"删除表。 1. TB01"）自动移到句首
- **页码/页脚过滤** — 自动过滤 PDF 页脚区域的页码、罗马数字等干扰内容
- **章节标题修复** — 将"总体说明 1.1"自动修正为"1.1 总体说明"
- **错误容错** — 单页解析失败不影响其他页面，支持加密 PDF 检测和空 PDF 检测
- **批量处理** — 支持多文件添加、文件夹导入、批量一键转换
- **现代化 GUI** — 深色主题、圆角按钮、实时进度显示、分色日志
- **MCP Server** - 可作为 MCP server 运行，供 AI 助手（ZCode/Claude 等）通过标准协议调用转换能力

## 效果对比

| 原始文档问题 | 转换后修复 |
|---|---|
| `单位公 共基础 信息采 集` | `单位公共基础信息采集` |
| `删除表。 1. TB01` | `1. 删除TB01表。` |
| `信 1.息记录。` | `信息记录。` |
| `总体说明 1.1` | `1.1 总体说明` |
| `新增TB02...单位修改 2. TB02` | `2. 新增TB02...单位修改` |

## 快速开始

### 环境要求

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-username/pdf-to-markdown.git
cd pdf-to-markdown

# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install pdfplumber python-docx mcp
```

### 使用 GUI

```bash
# 通用（Windows / macOS / Linux）
uv run python launch.py

# 或直接用入口点
uv run pdf2md-gui
```

各平台双击启动：

| 平台 | 方式 |
|---|---|
| Windows | 双击 `启动工具.bat`（控制台模式，显示日志便于排障） |
| macOS / Linux | `chmod +x launch.sh && ./launch.sh` |

无控制台窗口启动（Windows，等价后台运行）：

```bash
python launch.py --no-console
```

#### 批量转换操作步骤

1. **添加文件** — 点击 **添加文件** 选择单个或多个 PDF / Word 文档，或点击 **添加文件夹** 导入整个目录
2. **文件列表** — 所有文件以列表展示，支持右键移除、清空
3. **输出设置** — （可选）点击 **选择目录** 指定输出目录，默认与源文件同目录
4. **开始转换** — 点击 **开始转换**，批量处理所有文件
   - 实时显示处理进度条和文件计数
   - 每个文件显示页数（Word 文档显示 `-`）、段落数、表格数、行数
   - 成功/失败以不同颜色标识（绿色成功/红色失败）
5. **停止** — 随时点击 **停止** 中断批量处理
6. **打开输出目录** — 处理完成后查看所有生成的 Markdown 文件

文件列表状态标识：
- `○` 灰色 — 待处理
- `◉` 高亮 — 正在处理
- `●` 绿色 — 已完成
- `●` 红色 — 失败

### 使用命令行/Python API

```python
from engine import parse          # PDF 解析
from word_engine import parse_docx  # Word 解析
from markdown_writer import render

# 解析 PDF
blocks = parse("文档.pdf")

# 或解析 Word（.docx）
blocks = parse_docx("文档.docx")

# 生成 Markdown（两种格式共用同一个渲染器）
title = "文档标题"
md_content = render(blocks, title=title)

# 写入文件
with open("输出.md", "w", encoding="utf-8") as f:
    f.write(md_content)
```

### 批量处理脚本示例

```python
import os
from engine import parse
from word_engine import parse_docx
from markdown_writer import render

def convert(path: str, output_dir: str = ""):
    """转换单个 PDF / Word 文件"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        blocks = parse(path)
    elif ext == ".docx":
        blocks = parse_docx(path)
    else:
        raise ValueError(f"不支持的格式: {ext}")

    basename = os.path.splitext(os.path.basename(path))[0]
    md = render(blocks, title=basename)

    out_dir = output_dir or os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, basename + ".md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return out_path

# 批量转换（混合 PDF + DOCX）
src_dir = "docs/"
for fname in os.listdir(src_dir):
    if fname.lower().endswith((".pdf", ".docx")):
        convert(os.path.join(src_dir, fname), "output/")
```

### 作为 MCP Server 使用

本项目可作为 **MCP（Model Context Protocol）server** 运行，让 AI 助手（如 ZCode、Claude Desktop）通过标准协议调用文档转换能力。传输方式为 **stdio**，由 MCP 客户端以子进程方式启动。

#### 安装

MCP 依赖已包含在默认依赖中，无需额外安装：

```bash
uv sync
```

#### 配置客户端

在 MCP 客户端的配置文件中添加 `pw-to-markdown` server（以 ZCode / Claude Desktop 的 `mcp.json` 为例）：

```json
{
  "mcpServers": {
    "pw-to-markdown": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/GetPDFInfo", "python", "mcp_server.py"]
    }
  }
}
```

也可通过项目入口点启动：`pw-to-markdown-mcp`（等价于 `python mcp_server.py`）。

#### 提供的工具

| 工具 | 说明 | 关键参数 |
|---|---|---|
| `convert_to_markdown` | 转换单个 PDF/Word 文档 | `file_path`、`output_path`（可选）、`format`（md/html）、`page_range`、`business_mode`、`max_content_chars` 等 |
| `batch_convert` | 批量转换目录下所有文档 | `directory`、`output_dir`、`recursive`、`name_template` 等 |
| `get_document_info` | 获取文档基本信息 | `file_path` |

`convert_to_markdown` 返回 Markdown 文本内容与统计信息（页数/段落数/表格数/行数/`page_errors`/`ocr_status`）；指定 `output_path` 时同时写入文件；内容超长时按 `max_content_chars`（默认 50000）截断并标记 `truncated`。`batch_convert` 返回每个文件的处理结果明细（含 `stats` 和 `ocr_status`）。`get_document_info` 返回格式、大小、页数、是否扫描件等，便于转换前判断是否需要 OCR。

`ocr_status` 字段取值：`disabled`（用户关闭）/ `not_applicable`（非 PDF）/ `not_scanned`（文本型）/ `unavailable`（扫描型但未装 PaddleOCR）/ `applied`（已尝试 OCR）。

所有工具的错误均以结构化 `{"success": false, "error": "..."}` 返回，不会中断会话。

#### 调试

用 MCP Inspector 交互式测试工具：

```bash
uv run mcp dev mcp_server.py
```

## 架构设计

### 目录结构

```
pdf-to-markdown/
├── main.py                # tkinter GUI 入口（三栏布局 + 实时 Markdown 预览）
├── cli.py                 # CLI 入口（convert / batch / info 子命令）
├── mcp_server.py          # MCP server 入口（stdio，供 AI 助手调用转换能力）
├── engine.py              # PDF 解析引擎（含扫描型 PDF 自动 OCR 分发）
├── word_engine.py         # Word（.docx）解析引擎（样式/合并单元格/超链接）
├── ocr.py                 # PaddleOCR 集成（扫描型 PDF 识别 + 触发检测）
├── image_extract.py       # 图片提取（PDF page.images / Word a:blip）
├── block.py               # Block 数据结构 + 异常定义
├── postprocess.py         # 通用后处理（段落合并/序号修复/章节标题级别识别）
├── table_utils.py         # 表格处理（表头推断/列压缩）
├── markdown_writer.py     # Markdown 渲染器（默认输出格式）
├── html_writer.py         # HTML 渲染器（可选输出格式，含 XSS 转义）
├── markdown_preview.py    # GUI Markdown 实时预览面板（Text + tag 渲染）
├── output_path.py         # 输出路径解析（文件名模板 + 重名保护）
├── config.py              # ConvertOptions + AppConfig + ~/.pdf2md/config.json 持久化
├── pyproject.toml         # 项目配置（依赖 / scripts / ruff / mypy / pytest）
├── uv.lock                # 依赖锁定
├── launch.py              # 跨平台启动脚本（uv 检测 + 降级 + --no-console）
├── launch.sh              # macOS / Linux 启动脚本（chmod +x 后双击运行）
├── 启动工具.bat           # Windows 启动脚本（双击打开 GUI，调 launch.py）
│
├── result/                # 黄金样本（真实 PDF + 转换结果，用于回归测试）
│   ├── sample-1.pdf
│   ├── sample-1.md          # 主黄金样本
│   ├── sample-1_1.md        # 副本（重名保护测试残留）
│   ├── sample-1_2.md        # 副本
│   ├── sample-2.pdf
│   ├── sample-2.md
│   ├── sample-2_1.md
│   └── sample-2_2.md
│
├── tests/                 # 测试套件（205 passed / 0 skipped）
│   ├── conftest.py                    # 公共 fixture + 黄金样本路径
│   ├── samples/                       # 测试样本（PDF + Word + 黄金样本基线）
│   │   ├── simple_test.pdf
│   │   ├── simple_test_golden.md      # 黄金样本 1 基线（回归测试用）
│   │   ├── cross_page_table.pdf
│   │   ├── cross_page_table_golden.md # 黄金样本 2 基线
│   │   ├── table.docx                 # Word 表格样本
│   │   └── styled.docx                # Word 样式样本
│   ├── test_postprocess.py            # 后处理规则（44 用例，含章节级别识别）
│   ├── test_table_utils.py            # 表格处理
│   ├── test_engine_pdf.py             # PDF 解析 + 黄金样本回归 + page_range
│   ├── test_word_engine.py            # Word 解析 + 合并单元格 + 集成测试
│   ├── test_markdown_writer.py        # Markdown 渲染
│   ├── test_html_writer.py            # HTML 渲染
│   ├── test_markdown_preview.py       # 预览面板
│   ├── test_output_path.py            # 文件名模板 / 重名保护
│   ├── test_ocr.py                    # OCR 可用性 / 扫描型检测
│   ├── test_cli.py                    # CLI 子命令
│   └── test_mcp_server.py             # MCP server 工具（转换/批量/信息/注册）
│
├── scripts/               # 辅助脚本
│   └── create_test_pdf.py             # 生成测试样本 PDF（simple / cross_page_table）
│
└── docs/                  # 文档
    └── superpowers/       # superpowers skill 生成的计划/规格文档
        ├── plans/
        └── specs/
```

### 模块依赖关系

```
            ┌─────────────┐
            │  main.py    │  GUI 入口
            │  cli.py     │  CLI 入口
            └──────┬──────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌───────────────┐     ┌────────────────┐
│  engine.py    │     │ word_engine.py │  格式专用解析
│  (PDF)        │     │ (Word .docx)   │
└──────┬────────┘     └────────┬───────┘
       │                       │
       │   ┌───────────────────┘
       ▼   ▼
┌──────────────────────────────────────────┐
│  postprocess.py  通用后处理（两格式共用）  │
│  table_utils.py  表格处理                 │
│  block.py        Block 数据结构           │
│  config.py       ConvertOptions           │
│  ocr.py          扫描型 PDF OCR           │
│  image_extract.py 图片提取                │
└──────────────────┬───────────────────────┘
                   │
                   ▼
       ┌───────────────────────┐
       │ markdown_writer.py    │  输出渲染
       │ html_writer.py        │
       │ markdown_preview.py   │  GUI 预览
       │ output_path.py        │  路径解析
       └───────────────────────┘
```

### 数据流

```
PDF / Word 文件
    │
    ▼
┌────────────────────────────────────────┐
│  解析器（按扩展名分发）                   │
│                                        │
│  .pdf  → engine.py  parse()            │
│     ├── 逐页解析                        │
│     │   ├── page.find_tables() → 表格   │
│     │   └── page.extract_words() → 文字 │
│     └── 每页生成 Block，按 y_top 排序    │
│                                        │
│  .docx → word_engine.py  parse_docx()  │
│     └── 遍历 body 子元素（保留文档顺序） │
│         ├── w:p  → paragraph Block      │
│         └── w:tbl → table Block         │
│                                        │
│  共享后处理（两格式共用）                 │
│     ├── _merge_consecutive_tables()     │
│     ├── _merge_broken_paragraphs()      │
│     ├── _fix_list_number_positions()    │
│     └── _fix_headings()                 │
│                                        │
│  ▼ 输出: list[Block]                    │
└────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────┐
│  markdown_writer.py  render()           │
│                                        │
│  1. 写入标题                            │
│  2. 遍历 Block 列表                     │
│     ├── paragraph → 直接写入文本         │
│     └── table → 渲染 GFM 表格           │
│     └── 段落与表格间自动空行分隔          │
│                                        │
│  ▼ 输出: Markdown 字符串                │
└────────────────────────────────────────┘
    │
    ▼
Markdown 文件
```

### 核心数据结构

```python
@dataclass
class Block:
    type: str            # "paragraph" / "table" / "image"
    y_top: float = 0.0   # 在页面中的 Y 坐标（用于排序，确保阅读顺序）
    text: str = ""       # 段落文本（type="paragraph" 时使用）
    headers: list[str]   # 表头（type="table" 时使用）
    rows: list[list]     # 数据行（type="table" 时使用）
    image_path: str = "" # 图片相对路径（type="image" 时使用，如 "images/page1_0.png"）
```

所有内容块统一为 `Block` 类型，通过 `y_top` 坐标排序确保段落、表格、图片的阅读顺序正确。

## 核心实现详解

### 1. 表格检测与处理 (`_process_table_data`)

使用 `pdfplumber.page.find_tables()` 检测表格区域，然后进行一系列清洗：

**表头/数据行分离**：通过 `is_header_row()` 启发式判断——如果某行包含特定代码（如 `TB01`、`TC02` 等 `[A-Z]{2}\d{3,}` 模式），则判定为数据行；否则根据平均字符长度判断是否为表头行。

**多级表头扁平化**：PDF 中的 colspan/rowspan 合并单元格在 pdfplumber 中表现为多行表头。算法会：
1. 收集所有表头行
2. 逐列合并（按空格拼接）
3. 对空表头列，从数据行推断列名

**空表头推断**（通用启发式，不硬编码特定业务关键词）：当表头列为空时：
- 列中所有非空值相同（含单行表）→ 用该值作表头
- 列中有多个不同值 → 留空

> v0.2.0 曾硬编码特定业务关键词（"是/否"→"是否必须" 等），v0.2.2 起改为通用启发式，避免对非目标文档误判。

**空列压缩**：去除全空列，确保输出表格紧凑。

### 2. 文字提取与表格区域排除 (`_extract_text_outside_tables`)

使用 `page.extract_words()` 获取每个单词的位置信息：
1. 将单词按 Y 坐标聚类为行（间距 < 3pt 视为同一行）
2. 对每行检查是否与表格边界框（bbox）重叠
3. 重叠的行判定为"在表格内"，跳过
4. 不在表格内的行作为段落文本保留

**页脚过滤**：Y 坐标超过 `page_height - FOOTER_MARGIN`（默认 60pt）的行被丢弃，去除页码和页脚文字。

### 3. 跨页表格合并 (`_merge_consecutive_tables`)

PDF 中跨页的大表格会被拆分为多个表格块。算法检查连续两个 Block 是否都是表格且表头相同（忽略大小写和空格差异），如果是则合并行数据。

### 4. 段落后处理 (`_merge_broken_paragraphs`)

- 过滤单独的数字行（页码）、罗马数字（`Ⅰ`、`Ⅱ` 等）、目录点线
- 去除中文间的 CJK 空格
- 合并断裂的短行：当一段以数字+点结尾且下一段很短（≤6字）时，合并为同一段落

### 5. 序号位置修复 (`_fix_list_number_positions`)

PDF 排版中列表序号常被放在行尾（如 `删除表。 1. TB01`），本工具通过 6 条正则规则自动修复：

| 规则 | 匹配模式 | 修复结果 |
|------|---------|---------|
| 1 | 中文间的页码（`信 1.息`） | 移除页码（`信息`） |
| 2 | `操作表。 N. 表代码` | `N. 操作表代码表。` |
| 3 | `中文内容。 N. 表代码` | `N. 中文内容` |
| 4 | `中文内容 N. 表代码` | `N. 中文内容表代码` |
| 5 | `句子。 N.` | `N. 句子。` |
| 6 | `中文 N.` | `N. 中文` |

### 6. 章节标题修复 (`_fix_headings`)

匹配 `标题名 N.N` 模式（如 `总体说明 1.1`），交换顺序为 `N.N 标题名`。

### 7. Markdown 渲染 (`markdown_writer.py`)

- **段落**：直接写入文本，段落间以空行分隔
- **表格**：渲染为 GFM 表格语法，支持 `|` 转义
- **段落与表格交替**：自动处理段落与表格间的空行分隔

## 已知限制

- **扫描型 PDF 需 OCR**：扫描件/图片型 PDF 自动 OCR，但 PaddleOCR 为可选依赖（未安装时回退文本提取，内容可能不完整）。安装：`uv sync --extra ocr`
- **不支持加密 PDF**：密码保护的 PDF 无法解析
- **Word 仅支持 .docx**：旧版 `.doc` 二进制格式不支持，需先用 Word 另存为 `.docx`
- **Word 无页数**：文件列表中 Word 文档的页数列显示 `-`
- **表格检测依赖 pdfplumber**：部分复杂布局的 PDF 表格可能无法完美识别
- **表头识别为启发式**：`is_header_row` 基于单元格特征（含纯数字判数据行、业务代码 `[A-Z]{2}\d{3,}` 判数据行）区分表头/数据。纯短中文数据行（无数字、无业务代码）可能被误判为表头导致表格数据丢失
- **序号修复依赖启发式规则**：极少数情况下可能误判

## 依赖项

**核心依赖**（随 `uv sync` 安装）：

- [pdfplumber](https://github.com/jsvine/pdfplumber) ≥ 0.11 - PDF 解析核心库
- [python-docx](https://github.com/python-openxml/python-docx) ≥ 1.1 - Word（.docx）解析库
- [mcp](https://github.com/modelcontextprotocol/python-sdk) ≥ 1.0 - MCP server 依赖（含 MCPServer）
- Python 标准库：`tkinter`（GUI）、`re`、`os`、`threading`、`dataclasses`

**可选依赖**：

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) + [PaddlePaddle](https://github.com/PaddlePaddle/PaddlePaddle) - 扫描型 PDF OCR（`uv sync --extra ocr`）
- [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) - GUI 拖拽文件支持（`uv sync --extra gui`）

## 开发指南

```bash
# 克隆并进入目录
git clone https://github.com/your-username/pdf-to-markdown.git
cd pdf-to-markdown

# 创建虚拟环境
uv sync

# 运行测试（在 result/ 目录放一个 test.pdf 或 test.docx）
uv run python -c "
import os
from engine import parse
from word_engine import parse_docx
from markdown_writer import render

path = 'result/test.pdf' if os.path.exists('result/test.pdf') else 'result/test.docx'
blocks = parse(path) if path.endswith('.pdf') else parse_docx(path)
md = render(blocks, title='Test')
with open('result/output.md', 'w', encoding='utf-8') as f:
    f.write(md)
print(f'转换完成，共 {len(md.splitlines())} 行')
"
```

## 许可证

MIT

---

# 版本更新日志

## v0.2.0 — 工程化全面升级（2026-06-17）

在 v0.1.0 双格式转换能力的基础上，完成 5 个阶段共 18 项升级，把工具从「针对特定文档的脚本」进化为**通用、工程化、功能完整的文档转换工具**。测试从 0 增长到 **169 passed / 4 skipped**，ruff 与 mypy 全部通过，黄金样本零回归。

### 阶段 0：工程基建

- **架构解耦（0.1）**：拆分 `engine.py` → `block.py` / `postprocess.py` / `table_utils.py` / `engine.py`。Word 引擎不再 import PDF 引擎的私有函数。
- **后处理开关（0.2）**：引入 `ConvertOptions` dataclass（`config.py`），特定规则（序号修复、空表头推断）默认关，通过 `ConvertOptions.business()` 启用。普通文档不再被特定正则误伤。
- **配置持久化（0.3）**：`AppConfig` 保存窗口尺寸、分隔位置、输出目录、主题、最近文件、转换选项到 `~/.pdf2md/config.json`。
- **测试框架（0.4）**：新建 `tests/` 目录，覆盖 6 条序号正则、表头推断、跨页合并、CJK 空格、Word 样式、OCR 判定等。
- **Lint/类型（0.5）**：ruff（line-length=120）+ mypy 全过；补全类型注解，修复 B904/E741/F841/B007 等问题。

### 阶段 1：核心能力补强

- **跨页表格合并改进（1.1）**：三级策略——表头完全一致 / 第二页无表头（首行像数据行）/ 表头相似度 ≥ 0.8（字符集合 Jaccard），支持链式合并。中文表头略改（多空格）也能合并。
- **自适应页脚检测（1.2）**：扫描前 N 页底部 100pt 区域，归一化（去数字）后统计指纹，取重复文字最高 y 坐标作为页脚带上界。检测不到时回退固定 `FOOTER_MARGIN=60`。
- **Word 核心样式提取（1.3）**：Heading 1-6 → `#`~`######` 前缀；List Bullet → `-`；List Number → `1.`（从 `numPr` 推断序号）；Bold/Italic/Strike run → `**text**`/`*text*`/`~~text~~`；Hyperlink → `[text](url)`（通过 `doc.part.rels` 解析真实 URL）。
- **Word 合并单元格（1.4）**：遍历 `tr`/`tc` XML，按 `gridSpan`（横向）/ `vMerge`（纵向）构建真实二维网格，合并格只取左上角值。修复 python-docx `row.cells` 对合并单元格重复填充导致列数虚增的问题。
- **扫描型 PDF OCR（1.5）**：集成 PaddleOCR（可选依赖 `uv sync --extra ocr`）。`is_scanned_pdf()` 抽样前 5 页检测文字密度（< 10 字/页判定扫描型），自动 OCR 并回退到普通文本提取（OCR 失败时不中断）。GUI 检测未安装 PaddleOCR 时禁用 OCR 开关。

### 阶段 2：GUI 升级

- **三栏布局 + 实时预览（2.1）**：左文件列表 + 中操作栏 + 右 Markdown 预览。水平 `PanedWindow` 可拖拽调整宽度。预览用 `Text + tag` 简易渲染（无外部依赖），支持标题加粗变大、列表缩进、表格等宽对齐、代码块、引用、加粗/斜体/删除线/链接。选中已完成文件自动加载预览。
- **转换选项面板（2.2）**：右上角「⚙ 选项」按钮弹出对话框，分组展示所有开关（通用后处理 / 特定模式 / PDF 专用 / OCR / 图片 / 页码范围）。Canvas + Scrollbar 容纳全部选项，可调整窗口大小、支持鼠标滚轮、居中到父窗口。
- **配置持久化集成（2.3）**：启动恢复窗口尺寸/分隔/输出目录/选项，关闭自动保存。
- **日志可复制 + 导出（2.4）**：日志区右键菜单——复制选中 / 复制全部 / 导出到文件。
- **拖拽文件添加（2.5）**：集成 `tkinterdnd2`（可选依赖 `uv sync --extra gui`），拖 PDF/DOCX 到窗口自动添加。未安装时优雅降级。
- **暗/亮主题（2.6）**：右上角主题切换按钮，重启生效（保存到配置）。

### 阶段 3：完整 CLI（`cli.py`）

三个子命令，与 GUI 共享引擎：

```bash
# 转换单个文件
uv run python cli.py convert input.pdf -o output.md --business-mode

# 批量转换目录
uv run python cli.py batch docs/ -o output/ --recursive --name-template "{name}_{date}"

# 显示文档信息（页数/段数/表数/扫描型判定）
uv run python cli.py info input.pdf
```

通用选项：`--no-postprocess` / `--business-mode` / `--no-ocr` / `--ocr-lang {ch|en|ch_en}` / `--extract-images` / `--format md|html` / `--page-range 5-10`。

Windows GBK 终端兼容：启动时强制 stdout/stderr 用 UTF-8，避免 `✓`/`✗` 等字符输出崩溃。

`pyproject.toml` 注册入口：`pdf2md = "cli:main"` / `pdf2md-gui = "main:main"`。

### 阶段 4：功能扩展

- **图片提取（4.1）**：`image_extract.py` 模块。
  - PDF：`pdfplumber` 的 `page.images` + `extract_image()` 提取，导出到 `output/images/`。
  - Word：遍历 `a:blip r:embed` 元素，通过 `doc.part.rels` 解析图片 part，按 `content_type` 推断扩展名。
  - 新增 `Block(type="image", image_path="images/xxx.png")`，渲染为 `![](images/xxx.png)`。
  - 受 `ConvertOptions.extract_images` 控制（默认关，避免增加体积/改变输出目录结构）。
- **文件名模板 + 重名保护（4.2）**：`output_path.py` 模块。
  - 模板变量：`{name}`（源文件名）、`{date}`（YYYY-MM-DD）、`{seq}`（序号）。
  - 重名自动加序号：`report.md` → `report_1.md` → `report_2.md`；模板含 `{seq}` 时由模板自身递增。
  - GUI 与 CLI 共用同一逻辑。
- **HTML 输出（4.3）**：`html_writer.py` 模块，输出完整 HTML 文档（含 CSS、行内格式渲染）。所有文本经 `html.escape` 转义防 XSS。CLI `--format html` 启用。

### 修复

- **GUI 操作栏被拖动遮挡**：操作栏从文件列表卡片内部抽出到 vpaned 之外，上下拖动不再遮挡。
- **GUI 选项对话框展示不全**：改用 Canvas + Scrollbar 容纳所有选项，窗口可调整大小。

### 模块清单

```
pdf-to-markdown/
├── main.py              # GUI 入口（三栏 + 预览 + 选项 + 主题 + 拖拽）
├── cli.py               # CLI 入口（convert / batch / info）
├── engine.py            # PDF 解析（pdfplumber）+ OCR 集成
├── word_engine.py       # Word 解析（python-docx）+ 样式提取
├── ocr.py               # PaddleOCR 集成
├── image_extract.py     # 图片提取（PDF / Word）
├── postprocess.py       # 通用后处理（CJK / 序号 / 标题 / 表格合并）
├── table_utils.py       # 表格数据清洗
├── markdown_writer.py   # Markdown 渲染
├── html_writer.py       # HTML 渲染
├── markdown_preview.py  # GUI 预览面板渲染
├── output_path.py       # 输出路径计算 + 重名保护
├── block.py             # Block 数据结构
├── config.py            # ConvertOptions + AppConfig + 持久化
├── pyproject.toml       # 项目配置（含 optional-dependencies: dev/ocr/gui）
└── tests/               # 16 个测试文件，135 tests
```

### 可选依赖

```bash
uv sync                 # 核心依赖（pdfplumber + python-docx）
uv sync --extra dev     # 加 pytest/ruff/mypy
uv sync --extra ocr     # 加 paddleocr/paddlepaddle（扫描型 PDF OCR）
uv sync --extra gui     # 加 tkinterdnd2（拖拽支持）
uv sync --all-extras    # 全部安装
```

### 验证

- **测试**：`uv run pytest tests/` → 169 passed, 4 skipped
- **Lint**：`uv run ruff check .` → All checks passed
- **类型**：`uv run mypy .` → Success, no issues in 14 source files
- **黄金样本回归**：CLI 转换 `result/` 下的两个真实 PDF，输出与 v0.1.0 的 `.md` 文件 `diff` 为空

### 已知限制（v0.2.0 更新）

- **加密 PDF**：仍不支持，会抛 `PdfEncryptedError`
- **`.doc` 旧版二进制格式**：不支持，提示用户另存为 `.docx`
- **Word 无页数**：文件列表中页数列显示 `-`
- **图片提取**：默认关。开启后会增加输出体积、在输出目录创建 `images/` 子目录
- **OCR 依赖较重**：PaddleOCR + PaddlePaddle 安装包较大（数百 MB），放可选依赖
- **主题切换需重启**：暗/亮主题切换后需重启应用生效

---


---

## v0.3.0 - MCP Server + 全面优化（2026-08-03）

新增 MCP server 支持，并完成 11 项功能缺陷修复与健壮性优化。测试从 198 passed / 4 skipped 提升到 **205 passed / 0 skipped**。

### 新增：MCP Server

- 新增 `mcp_server.py`，基于 MCP Python SDK 提供 stdio server，供 AI 助手（ZCode/Claude 等）通过标准协议调用转换能力
- 三个工具：`convert_to_markdown`（单文件）、`batch_convert`（目录批量）、`get_document_info`（文档信息）
- 返回 Markdown 文本 + 可选写文件；异常以结构化 `{"success": false, "error": "..."}` 返回，不中断会话
- 入口点 `pw-to-markdown-mcp`，配置示例见上方「作为 MCP Server 使用」章节

### 功能缺陷修复

| 修复 | 说明 |
|---|---|
| **page_range 对文本型 PDF 无效** | `engine.parse` 主循环现在真正按 page_range 切片页面（此前仅 OCR 路径生效） |
| **OCR 不可用时静默跳过** | 扫描型 PDF 未装 PaddleOCR 时加 warning 日志；MCP 返回 `ocr_status` 字段；GUI 未装时禁用 OCR 复选框 |
| **黄金样本回归测试永久 skip** | 黄金样本改用 `tests/samples/` 内置样本，`TestGoldenRegression` 现在真正运行 |
| **Word 集成测试永久 skip** | 补 `table.docx` + `styled.docx` 样本，Word 端到端测试现在真正运行 |

### 健壮性优化

| 优化 | 说明 |
|---|---|
| **image_extract 静默吞异常** | 4 处裸 except 加 `logging.warning` + 失败计数，图片提取失败可观测 |
| **单页解析失败无日志** | `engine.parse` 单页异常加 warning；MCP stats 加 `page_errors` 列表单独报告 |
| **MCP 大文件 content 撑爆上下文** | `convert_to_markdown` 加 `max_content_chars` 参数（默认 50000），超长截断并标记 `truncated` |

### 代码质量与文档

- 统一测试样本目录到 `tests/samples/`，删除冗余的 `test_samples/`
- `test_markdown_preview.py` 加注释说明测试的是独立副本正则
- README 依赖项补充 `mcp`；已知限制修正过时描述；MCP 工具描述补全返回值字段

### 验证

- `pytest`: **205 passed / 0 skipped**
- `ruff check`: All checks passed
- 黄金样本回归测试通过（`tests/samples/*_golden.md`）

## v0.2.4 — Word 表格 vMerge 列错位修复（2026-07-16）

修复 Word 表格中纵向合并单元格（vMerge）导致续接行数据列错位的问题，同时将合并单元格的值向下填充到所有续接行。

### 问题

Word 表格中某列使用纵向合并（vMerge）跨多行时，第二行起的所有单元格向右错位一列。例如：

```
原始表格：
报文    元素名称          是否必填  说明
请求头  1.  S-Token      N        令牌
(合并)  2.  S-Req-Id     Y        请求编号

修复前（错位）：
| 请求头 |  | S-Token | N | 令牌 |
|  |  |  | S-Req-Id | Y | 请求编号 |   ← S-Req-Id 跑到了“是否必填”列

修复后（正确）：
| 请求头 | 1. | S-Token | N | 令牌 |
|  | 2. | S-Req-Id | Y | 请求编号 |
```

### 根因

`word_engine._extract_table_grid` 函数的 vMerge 续接快速路径只推进了输出列索引 `col_idx`，但没有从输入迭代器 `tc_iter` 中消费掉对应的物理 `<w:tc>` 元素。由于 vMerge "continue" 在 Word XML 中是真实存在的 `<w:tc>` 元素，下次 `next(tc_iter)` 取到的是这个该跳过的单元格，导致后续所有单元格右移。此外，vMerge 续接格填空字符串而非 restart 格的值，导致合并单元格的值未向下填充到续接行。

### 修复

| 文件 | 改动 |
|---|---|
| `word_engine.py` | vMerge continue 快速路径中消费物理 `<w:tc>` 元素（核心修复）；vMerge continue 续接格用 restart 格的值向下填充（而非留空）；`tr.iter` 改为 `tr.findall` 避免递归进入嵌套表格；vMerge restart + gridSpan 组合时注册所有覆盖列 |
| `tests/test_word_engine.py` | 新增 `TestExtractTableGrid` 测试类，6 个用例覆盖 vMerge 基本场景、多行续接、普通表格不回归、gridSpan 横向合并、vMerge+gridSpan 组合、双列独立 vMerge |

### 验证

- `pytest`: **176 passed / 4 skipped**（新增 6 个 Word 表格合并单元格用例）
- 原有 169 个测试全部通过，无回归

---

## v0.2.3 — PDF 续行合并修复（2026-06-18）

针对 v0.2.2 中 PDF 提取把同一段落拆成多行的问题进行修复。现在同页内的缩进续行与跨页续行会被合并为完整段落，同时防止章节号标题被误并入正文。

### 1. 同页续行合并（`_merge_indented_continuations`）

**问题**：pdfplumber 按物理行提取，中文排版的「首行缩进 + 续行顶格」段落被拆成多行。例如：

```
（2）如原记录明细表TB01 的状态标志（FD001）为"01-正常"，则
新增记录写"02-变更"； 如原记录明细表TB01 的状态标志（FD001）
为"04-已处理"，则新增记录写"03-已处理变更"；
```

应为一行，却被拆成三行。

**修复**：`engine._extract_text_outside_tables` 收集 `(y_top, x0, text)` 后调用新增的 `_merge_indented_continuations`，把续行合并回首行。判断条件（同时满足才合并）：
1. 上一行不以句末标点结尾（。！？；等）
2. 当前行不以段落起始标志开头（（N）、N.、第N章等）
3. 上一行不是章节号标题（如 `3.1.1 xxx`）—— 防止标题被并入正文
4. 行间距 ≤ 25pt（排除标题/表格间隔）
5. 当前行不比上一行缩进更多（排除新缩进段落）

### 2. 跨页续行合并（`_is_cross_page_continuation`）

**问题**：段落跨页时，上半段在上一页末尾、下半段在下一页开头，被分成两个 Block。

**修复**：`postprocess.merge_broken_paragraphs` 新增跨页续行合并。判断条件（同时满足）：
1. 上一段不以句末标点结尾
2. 当前段不以段落起始标志开头
3. 上一段不是 Markdown 标题（`## `）或章节号标题（`3.1.1 xxx`）或章标题（`第N章`）
4. 两段都足够长（>10 字符），避免误合并短句/标题

### 3. 防过度合并保护

章节号标题行（如 `3.1.1 数据查询`、`2.1.5.21.1 操作涉及的数据库表`）在 `fix_headings` 添加 `#####` 前缀之前是纯文本，易被当作普通上一行与后续正文合并。两个合并函数都新增了 `_HEADING_NUM_PREFIX_RE` 检查（匹配 `^\d+(?:\.\d+)+\s`），确保章节号标题不与下一行合并。

### 验证

- `pytest`: **169 passed / 4 skipped**（新增 5 个跨页续行用例 + 7 个同页续行用例）
- `ruff check .` / `mypy .`: 全部通过
- 黄金样本重新生成：sample-1 由 1394 行降至 1219 行（-12.5%），sample-2 由 4252 行降至 3202 行（-24.8%），均为段落续行合并，标题/列表项/表格无回归

### 涉及文件

| 文件 | 改动 |
|---|---|
| `engine.py` | 新增 `_merge_indented_continuations` 同页续行合并；`_extract_text_outside_tables` 收集 x0 并调用之；新增 `_HEADING_NUM_PREFIX_RE` |
| `postprocess.py` | `merge_broken_paragraphs` 增加跨页续行合并；新增 `_is_cross_page_continuation`；新增 `_HEADING_NUM_PREFIX_RE` 防标题误合并 |
| `tests/test_postprocess.py` | 新增 5 个跨页续行用例（合并/句末标点/段落起始/章节号标题/短文本） |
| `tests/test_engine_pdf.py` | 新增 `TestMergeIndentedContinuations`（7 个用例） |
| `result/*.md` | 黄金样本重新生成 |

---

## v0.2.2 — 表头推断通用化 + 安全/质量修复（2026-06-18）

### 1. 表头推断：去除硬编码特定业务关键词，改为通用启发式

**问题**：`table_utils.process_table_data` 的空表头推断硬编码了特定业务关键词（"是/否"→"是否必须"、`[A-Za-z]{2}\d+`→"涉及编号"、"新增/修改/删除/更新"→"涉及操作"），对非目标文档不适用，违背通用工具定位。

**改动**：删除 3 个特定业务关键词分支，只保留通用启发式：
- 列中所有非空值相同（含单行表）→ 用该值作表头
- 列中有多个不同值 → 留空

`infer_empty_headers` 开关保留（控制是否启用），但规则内容不再含特定领域特化逻辑。

### 2. html_writer XSS 修复

`_render_inline_html` 链接 URL 未过滤危险 scheme，`[click](javascript:alert(1))` 会生成可执行 XSS 链接。新增 `_safe_url()` 白名单（http/https/mailto/ftp/tel + 相对路径/#），过滤 `javascript:`/`data:` 等。

### 3. OCR 失败可观测

`engine.parse` 中 OCR 分发的 `except Exception: pass` 改为 `logging.warning(..., exc_info=True)`，回退到文本提取时有日志可查。

### 4. Word 引擎补跨页表格合并

`word_engine.parse_docx` 原遗漏 `merge_consecutive_tables` 调用，与 PDF 引擎不对齐。已补上。

### 5. engine.py options 风格统一

OCR 路径用 `opts`（已解析默认值），非 OCR 路径用原始 `options`（可能 None）。统一为 `opts`。

### 6. PDF 行内文字顺序修复（中文/西文 baseline 微差）

**问题**：`_cluster_words_into_lines` 按 `(top, x0)` 排序后聚类成行，但中文与西文/数字的 `top` 坐标常有 <1pt 的微差（如中文 696.1、TB01 697.0）。排序时 696.1 的词先排、697.0 的词后排，导致 TB01 等代码被排到行尾堆叠（如 `新增表，在记录明细中新增原数据的变更。 1. TB01 TB01 TB01`）。

**修复**：聚类成行后，行内词按 `x0` 重新排序，恢复阅读顺序。修复后与 pdfplumber 原生 `extract_text` 输出一致。

**效果示例**：
- 修复前：`新增表，在记录明细中新增原数据的变更TB01 TB01 TB01`
- 修复后：`1. 新增 TB01 表，在记录明细 TB01 中新增原数据 TB01 的变更。`

同时修复了目录页码错位、年月日期乱序等问题。

### 7. PDF 合并单元格表头列对齐修复

**问题**：PDF 多行表头的合并单元格文字 anchor 在合并区域左上角列，而数据落在合并区域内另一列，产生相邻的「有表头无数据」列与「有数据无表头」列，导致表头与数据错位（如表头「涉及编号」列无数据，相邻列有 TB01 数据）。

**修复**：
1. `keep`（保留列）改为同时考虑表头行，不再丢弃只有表头的错位列
2. 新增 `_align_headers_to_data`：扁平化后、空表头推断前，把「有表头无数据」列的表头移到相邻的「有数据无表头」列（优先左邻），通用启发式不依赖特定业务关键词

### 验证

- `pytest`: **169 passed / 4 skipped**（table_utils 13 用例含列对齐、engine 4 个聚类用例、html_writer 4 个 XSS 用例）
- `ruff check .` / `mypy .`: 全部通过
- 黄金样本重新生成：行内顺序修复影响 sample-1 的 681 行、sample-2 的 1470 行，均为阅读顺序归位（代码穿插、目录页码、日期顺序），无回退

### 涉及文件

| 文件 | 改动 |
|---|---|
| `table_utils.py` | 删除特定业务关键词分支只留通用启发式；`keep` 考虑表头行；新增 `_align_headers_to_data` 列对齐修复 |
| `engine.py` | `_cluster_words_into_lines` 行内按 x0 重排修复 baseline 微差；OCR 异常改 `logging.warning`；后处理统一用 `opts` |
| `html_writer.py` | 新增 `_safe_url()`，链接渲染调用它 |
| `word_engine.py` | 补 `merge_consecutive_tables` 调用 |
| `config.py` | `infer_empty_headers` 注释更新 |
| `tests/test_table_utils.py` | 重构为通用启发式 + 列对齐用例（13 个） |
| `tests/test_engine_pdf.py` | 新增 `_cluster_words_into_lines` 单元测试（4 个） |
| `tests/test_html_writer.py` | 新增 XSS scheme 过滤用例 |
| `result/*.md` | 黄金样本重新生成 |

---

## v0.2.1 — 章节标题级别识别（2026-06-17）

针对 v0.2.0 中 `fix_headings` 仅做章节号位置调换（`总体说明 1.1` → `1.1 总体说明`）、**不输出 Markdown 标题前缀**的缺陷进行修复。现在 PDF / Word 转换会自动识别章节号深度并输出对应的 Markdown 标题级别，让目录树、TOC 生成、阅读器导航真正可用。

### 改动

#### `postprocess.fix_headings` 升级为两阶段处理

1. **位置调换**（原有，保留）：`总体说明 1.1` → `1.1 总体说明`
2. **级别识别 + Markdown 前缀**（新增）：
   - `1.1` → `## 1.1 标题`（H2）
   - `1.1.1` → `### 1.1.1 标题`（H3）
   - `1.1.1.1` → `#### 1.1.1.1 标题`（H4）
   - `1.1.1.1.1` → `##### 1.1.1.1.1 标题`（H5，**用户反馈场景**）
   - `1.1.1.1.1.1` → `###### 1.1.1.1.1.1 标题`（H6，Markdown 上限）

#### 保守约束（防止正文被误判为标题）

- 章节号必须含至少一个点（不识别 `1.` 或 `1`，避免与列表序号冲突）
- 标题文字长度 ≤ 60 字符
- 标题文字不以 `。？！.；;` 结尾
- 标题文字内部不含 `。`（句号是段落标志）
- 级别限定 `[H2, H6]`（H1 留给文档标题）

#### 影响范围

- 真实文档黄金样本（sample-1 / sample-2）共 **612 个章节**被正确识别为 H2-H5 标题
- 默认选项与特定模式选项均生效（`fix_headings` 是通用规则，不受 `business_mode` 控制）
- 可通过 `--no-postprocess` 或选项面板「章节标题修复」开关关闭

### 验证

- `pytest`: **169 passed / 4 skipped**（新增 8 个 `fix_headings` 边界用例）
- `ruff check .`: All checks passed
- `mypy .`: no issues in 14 source files
- 黄金样本回归测试通过（`result/*.md` 已同步重新生成）

### 涉及文件

| 文件 | 改动 |
|---|---|
| `postprocess.py` | `fix_headings` 重构为两阶段处理，新增 `_heading_level` / `_looks_like_heading_title` 辅助函数 |
| `tests/test_postprocess.py` | `TestFixHeadings` 扩展为 14 个用例（覆盖 2-6 级标题、单数字防误判、长标题防误判、句号防误判、`fix_headings=False` 开关） |
| `result/sample-1.md`、`result/sample-2.md`（含 `_1`/`_2` 副本） | 黄金样本重新生成，612 个章节加上 Markdown 标题前缀 |

---

## v0.1.0 — 初始版本

双格式（PDF + Word .docx）转 Markdown 工具，支持表格检测、跨页表格合并、智能表头处理、中文排版优化、序号位置修复、章节标题修复、页脚过滤、批量处理、暗色 GUI。详见上方「功能特性」「核心实现详解」章节。

