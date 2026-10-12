# FlipMD 桌面客户端

FlipMD 是本项目的新桌面界面，沿用现有 PDF / DOCX 转换引擎，加入真实原文对照与本地任务历史。名称和 Logo 是可替换的展示资源，Python 包名、原有 CLI/MCP 入口和旧配置路径保持兼容。

## 启动

当前开发与验证环境为 macOS Apple Silicon、Python 3.12。

```sh
uv run --python 3.12 --frozen --extra desktop flipmd
```

可同时导入文件，或使用独立的数据目录检查功能：

```sh
uv run --python 3.12 --frozen --extra desktop flipmd --data-dir ./result/desktop-check report.pdf notes.docx
```

macOS 也可双击项目根目录的 `启动FlipMD.command`。Python >= 3.10 的原有命令行与 Tkinter 入口仍然保留；新桌面窗口的 Windows 代码尚未实机验证。

## macOS 应用包

当前本机开发包位于 `dist/0.4.0/FlipMD.app`，可直接双击打开，无需先启动终端或配置 Python。应用包包含运行时和桌面依赖，不包含可选的 PaddleOCR 组件。该产物针对当前 Apple Silicon 环境构建，尚未完成面向外部分发的开发者签名与公证。

重新构建：

```sh
uv run --python 3.12 --frozen --extra desktop --with pyinstaller==6.22.3 python scripts/build_desktop.py
```

构建脚本读取 `pyproject.toml` 的版本号，直接输出到 `dist/<版本号>/FlipMD.app`；同版本重新构建会更新同一路径，无需手动移动。Windows 的输出路径保持不变。

`dist/<版本号>/FlipMD/` 是 PyInstaller 在应用包旁生成的配套目录，正常保留。当前 `dist/` 只保留 `0.4.0/`；旧的根目录应用包与临时验证副本已移入废纸篓。

`dist/` 和 `build/` 为生成目录，不纳入 Git。

## Windows 安装包准备

Windows 打包脚本、Inno Setup 安装流程、WebView2 检测与手动 CI 构建定义已补齐。目前尚未在 Windows 上执行构建，不能将这些配置视为已生成或已验证的安装包。按用户要求，在完成本地脚本验证后暂停；恢复步骤见 [Windows 构建说明](windows-build.md)。

## 已接入的流程

- 单个/批量 PDF、DOCX 导入，文件夹只读取当前层；旧版 DOC 不支持。
- 转换参数、PDF 页码范围、图片提取、Markdown/HTML 输出、合并排序、大纲与摘要。
- 本次参数独立于全局默认值，历史保存提交时的参数快照。
- 任务在后台串行运行；停止请求在当前文件完成后生效，不伪造逐页百分比或预计耗时。
- SQLite 保存任务、文件子项、转换结果、摘要和日志；原文件缺失时，历史结果仍可阅读、复制和重新导出。
- PDF 左侧直接渲染源 PDF 页面。DOCX 左侧从原文件独立读取标题、正文、表格和内嵌图片，不宣称还原 Word 的分页、字体或复杂版式。
- 输出文件重名时增加序号；结果图片保存在独立目录，同时缓存到任务数据目录，以支持再次导出。
- 删除任务仅删除历史记录，不删除源文件、导出文件或缓存图片。缓存清理界面尚未提供。
- Markdown 为只读预览，编辑不在当前首版范围内。

## 设置

设置页修改后自动保存，无需点击保存按钮。主题立即切换；转换默认值用于之后导入的文件，已导入的文件和已建立任务的参数不受影响。“本次转换设置”仍通过“应用设置”确认。

页码范围在停止输入 350 毫秒、离开输入框或按回车时校验并保存。无效范围显示行内提示，继续使用上次有效值，也不阻止其他设置保存。页面显示保存状态；保存失败时可重试，连续修改按顺序保存，旧请求不会覆盖最新选择。

## OCR

OCR 仍然是可选能力。没有安装依赖时，客户端显示不可用；文字型 PDF 和 Word 可直接转换。需要扫描件识别时可使用项目已有的 `ocr` extra：

```sh
uv run --python 3.12 --extra desktop --extra ocr flipmd
```

首次识别可能下载 PaddleOCR 模型，具体行为继承现有 OCR 引擎。新客户端不将“依赖已检测到”等同于“模型已加载并完成识别验证”。

## 数据位置

默认目录为 `~/.pdf2md/desktop/`：

- `history.sqlite3`：任务、设置与结果快照。
- `results/<结果编号>/`：提取图片的缓存。
- `instance.lock`：同一数据目录的进程锁，避免两个实例错误恢复正在执行的任务。

首次启动读取旧版 `~/.pdf2md/config.json` 中的转换选项和输出目录，之后新桌面设置独立保存。旧文件不被覆盖。意外退出后，未完成任务显示为中断，不自动重复写出结果。

## 实现结构

- `desktop/app.py`：pywebview 原生窗口、文件对话框、拖入、剪贴板与打开输出位置。
- `desktop/service.py`：任务提交、后台处理、停止、结果查询和导出。
- `desktop/store.py`：SQLite 历史与恢复。
- `desktop/preview.py`：PDF 页面渲染、独立 DOCX 原文预览和安全 Markdown 阅读。
- `desktop/web/`：本地 HTML/CSS/JavaScript 界面及品牌图片，不依赖远程 CDN。

桌面界面通过 [pywebview 的 Python/JavaScript API](https://pywebview.flowrl.com/api/) 调用本机引擎。macOS 使用系统 WebKit 原生窗口；UI 静态资源由回环地址提供，文档原文不作为公共静态目录。文档文本经过转义，预览不会加载文档中的远程图片或通过文档链接导航到具有本地 API 的窗口外。

## 验证

```sh
uv run --python 3.12 --frozen --extra desktop --extra dev pytest -q
uv run --python 3.12 --frozen --extra desktop --extra dev ruff check desktop tests/test_desktop.py
```

新增集成测试使用真实 PDF/DOCX 引擎，覆盖结果持久化、原文缺失、独立原文读取、输出重名、图片导出、合并顺序及部分失败、停止后续文件、选项快照隔离、脚本/远程图片防护、意外退出恢复与进程锁。

2026-09-28 macOS 阶段验证：完整测试 244 项通过，新增代码 Ruff 检查通过。已在打包后的 macOS 原生窗口验证系统文件/文件夹导入、重复导入去重、PDF/DOCX 批量转换、PDF 真页预览、DOCX 独立内容对照、合并顺序、Markdown 源码、大纲统计、系统保存面板导出，以及关闭重启后历史保留。

后续 Windows 准备阶段补充检查后，完整测试增至 257 项通过；该阶段尚未进行 Windows 实机运行。当前按用户要求暂停，完整交接记录见 [项目工作总结](work-summary.md)。

实机发现并修复了原引擎的全文字表格遗漏：当表头启发式把所有行视为表头时，退回首个非空行作表头，其余行保留为数据。含数字或业务代码的既有多行表头处理保持原逻辑，相关回归测试通过。

当前为本地开发版本。扫描件 OCR、跨应用拖入、Windows、复杂文档的大规模兼容性尚未完成实机验收。
