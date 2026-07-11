# Assignment Dashboard

一个面向班委、课代表、教师和课程管理人员的 **本地化作业收集与提交追踪工具**。

Assignment Dashboard 可以监控微信文件目录及自定义作业目录，自动识别学生、科目和作业批次，并通过本地网页展示提交进度、未提交名单、未分类文件和作业文件预览。

项目的目标是把“收文件、核对名单、统计缺交、整理作业”等重复工作尽可能自动化。

> 所有学生名单、作业文件和提交记录默认保存在用户自己的电脑中。

---

## 功能特点

* 自动监控微信接收文件目录和自定义作业目录
* 根据文件名、学生名单和科目关键词识别提交记录
* 按学生、科目和作业批次整理文件
* 实时展示提交人数、未提交人数和完成率
* 查看作业详情及未提交学生名单
* 管理无法自动识别的未分类文件
* 支持 PDF、图片、Word 等文件预览
* 支持文件下载、批量打包和手动归类
* 支持学生名单、科目、扫描目录和截止日期管理
* 提供经典版和现代版两套前端界面
* 支持 GitHub Release 更新检查
* 更新前自动备份，失败时尝试回滚
* 支持本机访问和带口令的局域网访问
* 可选使用本地分类模块辅助识别文件

---

## 适用场景

Assignment Dashboard 适合以下场景：

* 班委或课代表收集班级作业
* 教师或助教统计课程提交情况
* 从微信接收目录中整理大量作业文件
* 快速生成未提交名单
* 在本地统一预览和管理学生提交文件

本项目不是微信插件，也不会修改微信客户端。它只读取用户配置的本地文件目录。

---

## 系统要求

* Windows 10 或 Windows 11
* Python 3.10 及以上版本
* 推荐使用 Python 3.12
* 推荐使用 Chrome、Edge 或其他现代浏览器

后端主要基于 Python 标准库 `http.server`，不依赖 Flask 或 FastAPI。

### 可选依赖

| 依赖            | 用途                           |
| ------------- | ---------------------------- |
| `python-docx` | 读取 DOCX 文档文本                 |
| `PyPDF2`      | 读取 PDF 文本                    |
| `pywin32`     | 调用 Microsoft Word 将文档转换为 PDF |
| LibreOffice   | 在没有 Microsoft Word 时转换文档预览   |

缺少可选依赖时，Dashboard 的核心功能仍可运行，但部分文档解析和预览功能会降级。

---

## 快速开始

### 方式一：下载发布版

普通用户建议从 GitHub Releases 页面下载最新发布包。

1. 下载最新版本的 ZIP 发布包
2. 将压缩包完整解压到一个普通目录
3. 运行安装程序或启动脚本
4. 浏览器会打开本地 Dashboard

不要直接在压缩包中运行程序。

### 方式二：从源码运行

```batch
git clone https://github.com/Trip1eY/Assignment-Dashboard.git
cd Assignment-Dashboard
python server.py
```

启动后访问：

```text
http://127.0.0.1:18765
```

其他页面入口：

```text
http://127.0.0.1:18765/dashboard
http://127.0.0.1:18765/modern
```

* `/dashboard`：经典版界面
* `/modern`：现代版界面

两个页面共用同一个后端和同一份运行数据。

---

## Windows 启动方式

如果发布包中包含以下脚本，也可以直接双击运行：

```text
启动作业追踪器.bat
```

开发调试时建议在命令行运行：

```batch
python server.py
```

终端会显示服务状态、扫描状态和错误信息。

---

## 常用命令

启动服务：

```batch
python server.py
```

指定其他端口：

```batch
python server.py --port 18766
```

启动安装向导：

```batch
python installer.py
```

生成更新包：

```batch
python pack.py --version 1.3.0
```

查看打包内容：

```batch
python pack.py --list
```

默认服务端口为：

```text
18765
```

如果提示端口已被占用或服务锁已存在，请先访问：

```text
http://127.0.0.1:18765
```

确认程序是否已经运行。

---

## 文件预览

### PDF 和图片

PDF 和常见图片格式会由浏览器直接显示。

### Word 文档

DOCX 和 DOC 文件首次预览时会进入后台转换队列。

系统会按以下顺序尝试转换：

1. Microsoft Word
2. LibreOffice
3. 文本预览降级

转换后的 PDF 会缓存在：

```text
data/preview_cache/
```

缓存文件会根据使用时间和容量自动清理。

即使预览转换失败，用户仍可下载或使用本机默认程序打开原文件。

---

## 本机与局域网访问

### 本机模式

默认情况下，服务只监听：

```text
127.0.0.1
```

只有运行程序的电脑可以访问 Dashboard。

这是推荐的默认模式。

### 局域网模式

用户可以在管理页面开启局域网访问。

开启后：

* 服务会重新绑定到局域网地址
* 系统会生成随机访问口令
* 手机或其他电脑需要验证后才能访问
* 访问模式和口令只能在服务所在电脑上修改

局域网模式只适用于可信的家庭、宿舍或校园内部网络。

**不要通过路由器端口映射、内网穿透或公网服务器直接暴露本项目。**

---

## 数据与隐私

运行时数据默认保存在项目目录下的 `data/` 中，包括：

```text
data/config.json
data/students.json
data/submissions.json
data/watcher_state.json
data/preview_cache/
```

这些文件可能包含：

* 学生姓名
* 学号
* 作业提交情况
* 本机绝对路径
* 微信文件目录
* 作业文件名
* 文件预览缓存

因此：

* 不要将 `data/` 提交到 GitHub
* 不要在公开 Issue 中上传真实学生数据
* 不要公开包含个人路径的配置文件
* 分享日志前应先删除姓名、路径和文件名
* 卸载或迁移前应自行备份 `data/`

项目默认不会将学生名单、提交记录和作业文件上传到云端。

以下功能可能访问互联网：

* 检查 GitHub Release 更新
* 下载 GitHub Release 更新包

---

## GitHub Release 更新

Assignment Dashboard 支持从 GitHub Releases 检查和安装更新。

### 发布流程

1. 修改代码并更新版本号
2. 生成更新包：

```batch
python pack.py --version 1.3.0
```

3. 在 GitHub 创建标签：

```text
v1.3.0
```

4. 创建对应 Release
5. 上传更新包：

```text
dashboard_update_v1.3.0.zip
```

更新包中应包含：

```text
manifest.json
```

其中记录版本号及更新信息。

### 用户更新流程

用户可在 Dashboard 的“系统更新”页面中：

1. 点击“检查 GitHub 更新”
2. 查看最新版本信息
3. 下载更新包
4. 确认安装更新

系统会依次执行：

* 检查更新包格式
* 校验 ZIP 内容
* 备份当前程序和运行数据
* 替换程序文件
* 重启服务
* 更新失败时尝试回滚

无法访问 GitHub 时，也可以提前下载 ZIP 文件，然后在系统更新页面中手动加载。

请只使用本项目官方 GitHub Releases 页面发布的更新包。

---

## 项目结构

```text
Assignment-Dashboard/
├── server.py
├── dashboard.html
├── dashboard_modern.html
├── installer.py
├── pack.py
├── repair_update.py
├── 启动作业追踪器.bat
├── config.example.json
├── requirements.txt
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── tests/
└── data/
```

主要文件说明：

| 文件                      | 作用              |
| ----------------------- | --------------- |
| `server.py`             | 后端服务、文件监控和 API  |
| `dashboard.html`        | 经典版前端           |
| `dashboard_modern.html` | 现代版前端           |
| `installer.py`          | Windows 图形化安装向导 |
| `pack.py`               | 发布包和更新包生成工具     |
| `repair_update.py`      | 更新失败后的修复工具      |
| `config.example.json`   | 默认配置示例          |
| `tests/`                | 自动化测试           |
| `data/`                 | 用户运行数据，不提交到公开仓库 |

---

## 安全说明

本项目会访问本地作业文件，因此使用时应注意以下事项：

* 不要将服务直接暴露到公网
* 不要关闭或绕过文件路径安全检查
* 不要加载来源不明的更新包
* 不要提交包含学生信息的配置和数据
* 不要在代码中写入密码、Cookie 或访问令牌
* 不要在公开 Issue 中粘贴完整日志
* 定期备份 `data/` 目录

发现安全问题时，请不要直接在公开 Issue 中披露详细利用方式。

请按照 `SECURITY.md` 中的方式提交安全报告。

---

## 开发与测试

创建虚拟环境：

```batch
python -m venv .venv
.venv\Scripts\activate
```

安装依赖：

```batch
pip install -r requirements.txt
```

运行后端：

```batch
python server.py
```

运行测试：

```batch
python -m unittest discover -s tests
```

执行编译检查：

```batch
python -m py_compile server.py installer.py pack.py repair_update.py
```

修改前端后，应至少检查：

```text
/dashboard
/modern
```

修改更新功能后，还应测试：

* 更新包生成
* `manifest.json` 读取
* ZIP 文件校验
* 更新备份
* 更新回滚
* `data/` 是否被保留

---

## 贡献

欢迎提交 Bug 报告、功能建议和 Pull Request。

提交贡献前请阅读：

```text
CONTRIBUTING.md
```

请不要在 Issue、Pull Request 或测试文件中包含：

* 真实学生名单
* 真实作业文件
* 微信聊天文件
* 本机用户目录
* 私人日志
* 访问令牌或密码

---

## 已知限制

* 当前主要面向 Windows 平台
* Word 高质量预览依赖 Microsoft Word 或 LibreOffice
* 自动分类准确率会受到文件命名方式影响
* 本项目适合本地或可信局域网使用
* 当前不适合作为公网多人协作服务部署

---

## 许可证

本项目计划采用 MIT License。

完整许可条款请查看：

```text
LICENSE
```

---

## 免责声明

本项目按现状提供，不保证能够识别所有文件命名方式，也不保证在任何环境下都不会发生文件分类错误。

在批量整理、更新或迁移数据前，请先做好备份。

项目维护者不对因误操作、配置错误、第三方软件异常或数据未备份造成的损失承担责任。
