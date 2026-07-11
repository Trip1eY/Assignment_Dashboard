# Assignment Dashboard

一个面向 Windows 本地使用的课程作业提交追踪器。它用于监控微信接收文件和班级作业目录，自动识别学生、科目与作业批次，并在本地网页中展示提交进度、未提交名单、未归类文件和最近文件。

项目主要服务班委、课代表和老师，目标是把“收文件、对名单、找缺交、归档作业”这些重复工作自动化。

## 主要功能

- 监控微信文件目录和自定义作业目录，发现新增提交文件。
- 根据学生名单、文件名和科目关键词自动匹配提交记录。
- 将已识别文件归档到已收作业目录，便于后续整理和公示。
- 在 Dashboard 中查看总览统计、作业详情、未提交学生和未归类文件。
- 支持文件预览、下载、批量打包和手动归类。
- 支持学生名单、扫描目录、作业批次、科目关键词和主题配置管理。
- 提供旧版稳定界面和现代版试用界面。
- 提供 Tkinter 安装向导、更新包生成和修复工具。

## 运行环境

- Windows
- Python 3.10+，推荐 Python 3.12
- 后端基于 Python 标准库 `http.server`，不依赖 Flask/FastAPI

可选依赖：

| 依赖 | 用途 |
|---|---|
| `python-docx` | 读取 `.docx` 文本 |
| `PyPDF2` | 读取 PDF 文本 |
| `pywin32` | 调用 Word COM，将 Word 文档转换为 PDF 预览 |

缺少可选依赖时，核心 Dashboard 仍可运行，但对应的文档解析或预览能力会降级。

## 文件预览

- PDF 和图片使用浏览器直接渲染。
- DOCX/DOC 首次预览会进入后台转换队列，转换完成后缓存为 PDF，再次打开会更快。
- 已安装 Microsoft Word 时优先使用 Word 保持排版质量；没有 Word 时尝试使用系统中的 LibreOffice。
- 两种转换组件都不可用时，系统会降级为文本预览，并保留直接打开原文件的入口。
- 预览缓存保存在 `data/preview_cache/`，会自动清理长期未使用或超过容量的缓存。

## 本机与局域网访问

- 默认只监听 `127.0.0.1`，其他设备无法直接访问。
- 普通用户可以在管理页开启局域网访问；切换后服务会自动重启。
- 开启时会生成随机访问口令，手机和其他电脑验证后才能进入。
- 访问模式和口令只能在运行服务的电脑上修改。
- 局域网模式只适用于可信私人网络，不应通过路由器端口映射暴露到公网。

## 快速开始

```batch
git clone https://github.com/Trip1eY/Assignment-Dashboard-.git
cd Assignment-Dashboard-
python server.py
```

启动后访问：

```text
http://localhost:18765
http://localhost:18765/dashboard   旧版稳定前端
http://localhost:18765/modern      现代版试用前端
```

也可以在 Windows 上双击：

```text
启动作业追踪器.bat
```

开发调试时建议直接运行 `python server.py`，终端会显示扫描和服务状态。

## 常用命令

```batch
python server.py
python server.py --port 18766
python installer.py
python pack.py
python pack.py --list
```

如果提示端口或服务锁已存在，先访问 `http://localhost:18765` 确认是否已经有服务在运行。异常退出后可以关闭旧命令行窗口，再重新启动。

## 发布与系统更新

项目支持通过 GitHub Releases 发布更新包：

1. 修改代码并更新版本号，例如 `1.3.0`。
2. 使用管理页生成更新包，或运行 `python pack.py --version 1.3.0`。
3. 在 GitHub 创建标签 `v1.3.0` 的 Release，并将生成的 `dashboard_update_v1.3.0.zip` 上传到 Release Assets。
4. 用户进入“系统更新”，点击“检查 GitHub 更新”，确认版本后即可下载并加载更新包。

更新包会先备份当前代码和 `data/`，再校验 ZIP、替换程序文件并重启。更新失败时会尝试自动回滚。GitHub Release 必须包含命名为 `dashboard_update_v*.zip` 的 ZIP 文件；手动选择本地 ZIP 的更新方式仍然可用。

系统更新检查依赖访问 GitHub API 和 Release 下载地址；无法联网时，可以直接下载 ZIP 后在“系统更新”模块中手动加载。

## 项目结构

```text
Assignment-Dashboard/
  server.py                  后端服务和 API
  dashboard.html             旧版稳定前端
  dashboard_modern.html      现代版试用前端
  installer.py               图形化安装向导
  pack.py                    更新包/发布包打包工具
  repair_update.py           更新修复工具
  启动作业追踪器.bat          用户启动脚本
  config.json                默认配置样例
  AGENTS.md                  Agent 接手说明
  HANDOVER.md                项目维护交接文档
  CONVERSATION_LOG.md        开发记录
  data/                      运行态数据，默认不提交
```

## 数据与配置

运行时数据保存在 `data/` 目录，通常包括：

- `data/config.json`：真实运行配置
- `data/students.json`：学生名单
- `data/submissions.json`：提交记录
- `data/watcher_state.json`：文件监控状态
- `data/preview_cache/`：预览缓存

`data/` 已在 `.gitignore` 中排除，不应提交到 GitHub。仓库根目录的 `config.json` 是默认配置样例，不代表用户真实运行数据。

## 前端入口

- `/dashboard`：旧版稳定入口，适合日常使用。
- `/modern`：现代版试用入口，用于新的界面和主题系统迭代。

两个前端共用同一个 Python 后端和 API。

## 安全说明

- 不要提交 `data/` 中的学生名单、提交记录、本机路径或预览缓存。
- 不要把 token、Cookie、带认证信息的远程地址写入文档、日志或提交记录。
- 新增文件相关接口时，应通过后端路径白名单校验，避免任意文件读取或下载。

## 开发说明

本项目当前是单文件后端和单文件前端为主的本地工具。修改时建议保持改动范围小，优先复用现有 API 和页面结构。

修改后建议至少运行：

```batch
python -m py_compile server.py installer.py
```

如果修改了前端，还应启动服务并检查 `/dashboard` 和 `/modern` 是否能正常打开。

## 许可证

当前仓库尚未声明开源许可证。如需公开分发或复用，请先补充 `LICENSE`。
