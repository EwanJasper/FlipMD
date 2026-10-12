# FlipMD Windows 构建准备

状态（2026-09-28）：打包脚本、安装器定义和手动构建工作流已补齐；当前只有 macOS 环境，尚未运行 Windows 构建、编译安装器或实机验收。按用户要求，完成本地验证后暂停，尚未上传代码或触发云构建。

## 预期产物

在 Windows 构建成功后，`dist/installers/` 应生成以下文件（版本读取自 `pyproject.toml`）：

- `FlipMD-0.4.0-windows-x64-setup.exe`：安装程序。
- `FlipMD-0.4.0-windows-x64-portable.zip`：解压后运行 `FlipMD/FlipMD.exe`。
- `FlipMD-0.4.0-windows-x64-sha256.txt`：两份产物的校验值。

这些是预期文件名，不代表本机已经存在可用的 Windows 安装包。目标为 Windows 10 1809 及以上 / Windows 11 x64；ARM64 模拟运行尚未验证。当前脚本不生成签名安装包，也不包含可选 OCR 组件。

## 在 Windows 构建

构建机需要 PowerShell 7.3+、uv 和 Inno Setup 6.3+。uv 负责 Python 3.12 与项目环境；构建使用 x64 Python。取得完整项目代码后，在项目根目录执行：

```powershell
pwsh -File .\scripts\build_windows.ps1
```

只需要便携目录压缩包时可执行：

```powershell
pwsh -File .\scripts\build_windows.ps1 -PortableOnly
```

脚本先运行测试，再调用 PyInstaller，最后打包便携版与 Inno Setup 安装器。依赖由 `uv.lock` 固定；PyInstaller 构建必须在目标系统上运行，参见 [官方说明](https://pyinstaller.org/en/stable/operating-mode.html)。

## 安装行为

- 默认安装到当前用户的 `%LOCALAPPDATA%\Programs\FlipMD`，不要求管理员权限。
- 添加开始菜单入口，桌面快捷方式可选；卸载程序不删除源文件、导出文件或 `%USERPROFILE%\.pdf2md` 历史。
- 从微软官方下载 WebView2 bootstrapper，并在构建时检查其 Authenticode 签名。安装器检测到缺少 WebView2 时才运行它；这一步需要联网。完全离线且尚无 WebView2 的机器需先安装微软提供的离线 Runtime。
- 应用运行前再次检查 WebView2，缺少依赖时显示明确提示。日常文档转换由本地引擎处理。
- 安装器界面当前使用 Inno Setup 的英文界面，应用界面为中文；安装器中文本地化可在 Windows 实机验收时继续整理。

WebView2 分发与注册表检测方式依据 [微软官方文档](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)。

## GitHub Actions 备选路径

`.github/workflows/build-windows.yml` 仅设置手动触发，使用 `windows-2022`。它准备执行：

1. 运行项目测试并构建安装器。
2. 将安装器实际安装到 runner 的临时目录。
3. 执行安装后的 `FlipMD.exe --self-test <报告路径>`，验证 WebView2 / pythonnet 依赖、界面资源、真实 PDF/DOCX 转换、PDF 渲染、Word 原文预览、HTML 导出和历史恢复。
4. 所有检查成功后上传安装包、便携版和校验值；失败时保存可用的诊断报告。

`--self-test` 不打开交互窗口，报告明确记录 `ui_tested: false`。这不能替代 Windows 窗口、拖入、系统对话框和实际文档的人工验收。

仓库目前仍是本地克隆，远端为原作者仓库。恢复工作后，先确定 Windows 构建环境；如选择 GitHub Actions，需要用户同意上传当前代码并指定自己的仓库，再执行构建。不要重新创建已被用户要求删除的 fork。

## 本次本地验证与暂停记录

- macOS 上完整测试：257 项通过；Ruff 检查和 `git diff --check` 通过。
- 源码自检已通过真实 PDF/DOCX 转换、PDF 渲染、Word 原文预览、HTML 导出、界面资源及 SQLite 历史恢复检查。
- Windows 构建参数预演通过；跨系统实际构建会明确拒绝执行。
- PowerShell 脚本及工作流中的 PowerShell 片段通过 tree-sitter 静态语法解析，工作流 YAML 可解析；这不是在 PowerShell 或 Windows 上执行成功的证明。
- Inno Setup 编译、Windows 依赖加载、安装与卸载、Windows 原生界面均待验证。没有生成 Windows `.exe`，没有上传代码或运行 GitHub Actions。
- 已按用户要求暂停，后续从下面的构建与验收清单恢复。

## 恢复时从这里继续

- 确定可用的 Windows 构建机或获准使用的自有 GitHub 仓库。
- 执行一次真实构建，处理安装器编译、依赖收集和 Windows 测试结果。
- 验证安装、启动、导入、原文预览、导出、重启历史、卸载保留数据。
- 只有真实产物生成并验证后，才向用户提供 `.exe` 下载或路径。
