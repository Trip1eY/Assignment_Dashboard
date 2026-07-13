# Assignment Dashboard

一个面向班委、学委、课代表和老师的 Windows 本地作业分类与提交追踪工具。

Assignment Dashboard 可以监控微信接收文件夹和自定义作业目录，根据学生姓名、课程关键词、作业批次和人工修正规则自动分类文件，并在本地 Dashboard 中展示提交进度、未提交名单、待确认文件和最近提交记录。

## 主要功能

- 监控微信接收文件夹和自定义作业目录
- 根据学生姓名、文件名和课程关键词识别作业
- 按课程、作业和实验批次整理提交文件
- 展示总人数、已提交人数、未提交名单和完成率
- 支持待确认文件、冲突文件和手动分类
- 记录人工修正结果，优化后续分类
- 支持学生名单和作业批次管理
- 支持 PDF、图片和 Office 文档预览
- 支持批量打包和下载作业文件
- 提供经典版（旧版）和现代版（新版）两套 Dashboard
- 支持本机模式和带访问口令的局域网模式
- 支持加载 ZIP 更新包、自动备份和失败回滚
- 支持从 GitHub Releases 检查最新版本

## 运行环境

- Windows 10 或 Windows 11
- Python 3.10 及以上版本
- 推荐使用 Python 3.12
- 默认服务端口：`18765`

项目后端基于 Python 标准库 `http.server`，不依赖 Flask 或 FastAPI。

### 可选依赖

```bash
pip install python-docx PyPDF2 pywin32
```

| 依赖 | 用途 |
|---|---|
| `python-docx` | 读取 `.docx` 文档文本 |
| `PyPDF2` | 读取 PDF 文本 |
| `pywin32` | 调用 Microsoft Word，将 Word 文档转换为 PDF 预览 |

缺少这些依赖时，核心 Dashboard 仍可运行，但部分文档解析和预览功能会降级。

## 下载与安装

推荐普通用户从 [GitHub Releases](https://github.com/Trip1eY/Assignment-Dashboard-/releases) 下载最新安装程序。

安装程序通常命名为：

```text
微信作业追踪器_安装向导_v0.1.0.exe
```

运行安装向导，根据提示选择安装目录和班级配置即可。

> 安装程序目前未进行商业代码签名，Windows SmartScreen 可能显示未知发布者提示。请只从本项目的 GitHub Releases 页面下载。

## 从源码运行

```bash
git clone https://github.com/Trip1eY/Assignment-Dashboard-.git
cd Assignment-Dashboard-
python server.py
```

启动后访问：

```text
http://localhost:18765
```

前端入口：

```text
http://localhost:18765/dashboard
http://localhost:18765/modern
```

也可以在 Windows 中双击：

```text
启动作业追踪器.bat
```

## 首次使用

建议按照以下顺序完成初始化：

1. 添加或导入学生名单
2. 设置微信接收文件夹或作业扫描目录
3. 设置班级作业归档目录
4. 配置课程名称和识别关键词
5. 创建作业或实验批次
6. 执行首次扫描
7. 检查待确认和未分类文件

运行数据会自动保存在项目的 `data/` 目录中。

## 文件分类

系统主要根据以下信息识别文件：

- 学生姓名或学号
- 文件名中的课程关键词
- 作业或实验名称
- 已配置的课程规则
- 历史人工修正记录

识别结果可能分为：

- 已识别并归档
- 仅识别学生
- 仅识别课程
- 多课程冲突
- 待人工确认
- 未识别文件

遇到无法准确分类的文件时，可以在 Dashboard 中手动指定课程和作业。

## 文件预览

- PDF 和图片由浏览器直接预览
- DOCX/DOC 文件会尝试转换为 PDF
- 安装 Microsoft Word 时优先使用 Word 保持排版
- 没有 Word 时会尝试使用 LibreOffice
- 转换组件不可用时会降级为文本预览
- 预览缓存保存在 `data/preview_cache/`

## 本机与局域网访问

系统默认只允许本机访问：

```text
127.0.0.1:18765
```

其他设备无法直接连接。

需要在手机或另一台电脑访问时，可以在管理页开启“允许局域网访问”。系统会生成随机访问口令，远程设备验证后才能进入。

> 局域网模式只适用于可信私人网络。请勿通过路由器端口映射、内网穿透或云服务器将本项目直接暴露到公网。

## 系统更新

已有用户可以进入：

```text
管理页 → 系统更新
```

然后选择：

- 检查 GitHub 更新
- 下载并加载最新版本
- 手动加载本地 ZIP 更新包

更新前系统会备份当前程序和运行数据。更新失败时会尝试自动回滚。

GitHub Release 中的更新包必须采用以下命名方式：

```text
dashboard_update_v0.1.0.zip
```

无法联网时，可以手动下载更新包，再拖入“系统更新”模块。

## 发布更新包

生成完整更新包：

```bash
python pack.py --version 0.1.0
```

生成指定文件的修复包：

```bash
python pack.py --bugfix server.py dashboard.html dashboard_modern.html
```

查看打包文件列表：

```bash
python pack.py --list
```

发布 GitHub Release 时建议上传：

```text
微信作业追踪器_安装向导_v0.1.0.exe
dashboard_update_v0.1.0.zip
```

Release 标签应与程序版本一致：

```text
v0.1.0
```

## 项目结构

```text
Assignment-Dashboard-/
├── server.py
├── ai_classifier.py
├── dashboard.html
├── dashboard_modern.html
├── installer.py
├── pack.py
├── repair_update.py
├── restart_helper.py
├── config.json
├── 启动作业追踪器.bat
├── 更新修复工具.bat
├── 微信作业追踪器_安装向导.spec
├── scripts/
│   ├── secret_guard.py
│   ├── test_ai_classifier.py
│   ├── test_network_access.py
│   └── test_two_stage_classification.py
├── README.md
├── LICENSE
└── .gitignore
```

## 数据与隐私

运行数据保存在 `data/` 目录，通常包括：

```text
data/config.json
data/students.json
data/submissions.json
data/watcher_state.json
data/preview_cache/
```

这些文件可能包含：

- 学生姓名和学号
- 作业提交记录
- 本机文件路径
- 微信文件目录
- 文件预览缓存

`data/` 已被 `.gitignore` 排除，不应提交到 GitHub。

提交代码前可以运行敏感信息检查：

```bash
python scripts/secret_guard.py --all
```

## 开发与测试

Python 语法检查：

```bash
python -m py_compile server.py installer.py ai_classifier.py pack.py repair_update.py restart_helper.py
```

运行单元测试：

```bash
python -m unittest discover -s scripts -p "test_*.py"
```

修改前端后，建议检查：

```text
/dashboard
/modern
```

并确认浏览器控制台没有脚本错误。

## 已知限制

- 主要面向 Windows，不保证在 macOS 和 Linux 上完整运行
- 微信目录结构可能随微信版本变化
- 文件名信息不足时无法保证自动分类完全准确
- Word 高质量预览依赖 Microsoft Word 或 LibreOffice
- 不建议部署到公网
- 安装程序暂未进行商业代码签名

## 问题反馈

遇到问题时，请在仓库的 [Issues](https://github.com/Trip1eY/Assignment-Dashboard-/issues) 页面提交反馈。

建议提供：

- Windows 版本
- Python 版本
- 操作步骤
- 错误信息或截图
- 问题文件类型

请勿上传真实学生名单、作业文件、访问口令或其他敏感数据。

## 许可证

本项目使用 [MIT License](LICENSE)。

你可以使用、修改和分发本项目代码，但需要保留原始版权和许可证声明。
