# Y7000P 三应用启动故障诊断报告（供多 Agent 会诊）

> 报告日期：2026-08-20 15:00 (GMT+8)
> 排查执行：m10-home 上的 WorkBuddy（经 SSH 远程）
> 目标机器：**Y7000P**（LAPTOP-ISOTBGN1，用户 `y`，Tailscale 100.71.146.32，局域网 192.168.1.17）
> 通道：`ssh -i ~/.ssh/m10_to_main y@100.71.146.32`（m10-home → Y7000P，Tailscale 直连）
> 状态：**诊断完成，未执行修复**（待会诊确认）

---

## 0. 结论摘要（一页看懂）

| 应用 | 一句话根因 | 责任人 | 可修复性 |
|---|---|---|---|
| WorkBuddy 打不开 | 8-18 自动更新（5.3.13→5.3.14）在卸载旧组件 qm 时失败、NSIS 安装中断，导致 `resources\qm\scripts` 缺失，主进程启动加载授权模块 `workbuddy-auth-product-coordinator.js` 失败（MODULE_NOT_FOUND）→ 启动即崩 | WorkBuddy 更新器自身 | ✅ 高（重装/官方修复） |
| dsh 打不开 | pnpm 依赖仓库 `D:\.pnpm-store\v11` 被清理（只剩 3 项），`node_modules\tsx` 等符号链接悬空 → tsx 加载失败 → 启动脚本抛错 | 疑似 8-16 前后 D 盘清理/杀毒误删 | ✅ 高（pnpm install 重建） |
| Sunshine 未正常自启 | SunshineService 服务进程崩溃循环（事件 7031 意外终止），端口 47989/47990 从未监听；sunshine.exe 每 2 分钟被拉起又 3 秒退出 | Sunshine 服务自身（NvEnc/驱动/配置待查） | ✅ 中（需查 7031 详情） |

**共同根因：无单一共同根因**，三条因果链相互独立。共同表象（非根因）：① 两机（m10-home / Y7000P）都缺 `crashpad_handler.exe` 且都装火绒（疑火绒统一隔离）；② 异常事件集中在 8-16 ~ 8-18 三天。

---

## 1. 机器拓扑

| 机器 | 主机名 | 用户 | Tailscale | 局域网 | 角色 |
|---|---|---|---|---|---|
| m10-home（本机） | DESKTOP-LTR7NS3 | admin | 100.103.7.4 | 192.168.1.21 | 排查执行机（M10 控制面板） |
| Y7000P（目标） | LAPTOP-ISOTBGN1 | y | 100.71.146.32 | 192.168.1.17 | 被排查机 |

架构：Y7000P 跑 DeepSeek-Harness (dsh web, 127.0.0.1:3080)、WorkBuddy 5.3.13、Sunshine（D:\Apps\Sunshine 服务模式）；m10-home 负责远程运维（WOL/SSH 已打通，密钥 `m10_to_main` 免密）。

---

## 2. 用户报告的症状

1. **WorkBuddy** 点击图标后无反应（启动不了）
2. **dsh** 打不开（用户记忆"设置了开机自启动"）
3. **Sunshine** 未能正常开机自启动

---

## 3. 详细诊断

### 3.1 WorkBuddy（主进程启动即崩）

**症状现场**（8-20 04:04~04:05）：
- 3 个 WorkBuddy.exe 僵尸进程：PID 27268(24MB) / 17848(7.8MB) / 12280(5.3MB)，创建于 04:04:59 / 04:05:01 / 04:05:01 —— 正常实例应数百 MB，这些是启动早期就卡死的残留
- 桌面快捷方式指向 `C:\Users\y\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe`（路径正确）

**核心日志证据**（`%LOCALAPPDATA%\WorkBuddy\logs\renderer.log` 尾部，8-20 03:47~04:05 连续 5 次）：
```
"code":"MODULE_NOT_FOUND","requireStack":[
"C:\Users\y\AppData\Local\Programs\WorkBuddy\resources\app.asar\main\workbuddy-auth-product-coordinator.js",
"C:\Users\y\AppData\Local\Programs\WorkBuddy\resources\app.asar\main\index.js",null]
```
→ 主进程入口 index.js 加载授权/产品协调模块失败，未捕获异常，进程卡死在初始化。

**版本与文件完整性**：
- app.asar：283,047,928 字节，8-17 22:55，SHA256 = `466c8a91a5ff2665d94f0506e66015bfa31a40996dc6780bac5d1f00bbc1d640`
- WorkBuddy.exe：204,626,984 字节，8-17 22:55
- **与 m10-home（能正常运行的机器）字节级完全一致** → 核心文件未损坏、版本相同（5.3.13）
- **差异点**：Y7000P 的 `resources\` 缺 `qm\`、`scripts\` 目录（m10-home 有）；Y7000P 多了 `WorkBuddyRepair.exe`、`startup-report.html`、`System.ValueTuple.dll`

**更新日志证据**（`C:\Users\y\.workbuddy\logs\update\update-20260816.log` 尾部，8-18 14:29Z=22:29 本地）：
```
[14:29:41] QmProtector: helperExe=...\resources\qm\qm-helper.exe exists=true
[14:29:41] QmProtector: dllDir=...\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\weixinpay\prebuilds\win32-x64 dllExists=true
[14:29:42] [WARN] QmProtector suspend failed: Command failed: ...\qm-helper.exe suspend ...
[14:29:42] installerPath=C:\Users\y\AppData\Local\Temp\workbuddy-update-x64\WorkBuddy-Setup-5.3.14.36279234.exe
[14:29:43] Using NSIS silent mode (/S --updated /UPDATE=1 /D=C:\Users\y\AppData\Local\Programs\WorkBuddy)
[14:29:45] Calling app.quit() now
[14:29:50] [WARN] app.quit() did not exit after 5 seconds, forcing exit
```
→ **日志在此戛然而止，NSIS 安装器没有任何后续执行记录** = 更新流程在"强制退出主进程"后中断，安装未完成。
→ 8-16 14:57 的同日日志也出现一次 `QmProtector suspend failed`，说明该组件反复失败。
→ **QmProtector 是更新前卸载旧 qm（企微授权 SDK）组件的步骤：suspend 失败 → qm 组件被清理但未恢复**。当前 Y7000P `resources\` 无 qm 目录印证了这一点。`workbuddy-auth-product-coordinator.js` 正是依赖 qm 的授权模块。

**崩溃报告证据**：
- `crash-report-sidecar-3748-20260818T222948.json`：8-18 22:29:54，appVersion 5.3.13，`EPIPE: broken pipe, write`（更新退出时 sidecar 管道断裂——更新流程的连带崩溃，非独立故障）
- `crash-report-main-28228-20260816T225953.json`：8-16 22:59~8-17 20:03，renderer 层 `An object could not be cloned.` + ResizeObserver 噪音

**根因判定（高置信）**：WorkBuddy 5.3.13 的自动更新器在 8-18 22:29 执行 5.3.14 更新时，QmProtector 卸载 qm 组件失败 → 安装流程中断（无 NSIS 执行记录）→ qm/scripts 被删未恢复 → 主进程启动 require 授权模块失败 → 启动即崩。

---

### 3.2 dsh（DeepSeek-Harness web）

**症状**：3080 无监听（netstat 无输出）、无 dsh/harness 相关进程。

**部署现状**：
- 源码：`C:\Users\y\Documents\Codex\2026-08-14\ban\outputs\DeepSeek-Harness`（完整，含 node_modules 顶层 37 项）
- 会话目录：`C:\Users\y\.dsh`（profiles/sessions/settings.yaml/storages 均在）
- 启动脚本：`start-dsh.ps1`（UTF-16LE 编码，ASCII-only 设计）
  - 命令：`node --import tsx/esm apps/cli/src/bin.ts web --trusted-host laptop-isotbgn1.tailb66da0.ts.net`
  - node 路径硬编码：`C:\Users\y\.workbuddy\binaries\node\versions\22.22.2\node.exe`（**该文件存在**，87MB；先前误判为缺失）
  - 幂等：3080 已监听则退出
- 设计定位：由 M10 控制面板 SSH 远程触发；**无任何开机自启动项**（注册表 Run / 计划任务 / 启动文件夹均无 dsh 条目——用户"设过自启动"的记忆与实际不符，或指 M10 远程触发机制）

**根因证据**：
- `node_modules\tsx` 目录存在但内容**读不到**（`dir` 无输出、`package.json` 不存在）→ 悬空符号链接
- `D:\.pnpm-store\v11` 仅剩 3 个条目，**不含 tsx** → pnpm 全局 store 被清理/移动，项目符号链接全部失联
- 佐证同类型异常：`.workbuddy\` 下 `AI-Brain-broken-20260816`（8-16 损坏标记）、`binaries\node\versions\22.12.0.installing.*.extract_temp` 中断残留（4-7）、`D:\New Folder\node.exe` 等目录移动痕迹

**根因判定（高置信）**：`D:\.pnpm-store` 被清理（时间窗口 8-16 前后）→ 项目 node_modules 符号链接悬空 → tsx 加载失败 → `start-dsh.ps1` 抛错退出。node.exe 本身存在，**无需拷 node**。

---

### 3.3 Sunshine

**症状**：SunshineService 显示 RUNNING，但 47989/47990/47984/47986 全部无监听；`sunshine.exe` 每 2 分钟新增一个 32K 僵尸进程（8-20 04:04→04:21 已十余个）；串流（Moonlight）连不上。

**证据**：
- 服务：`D:\Apps\Sunshine\tools\sunshinesvc.exe`，START_TYPE=AUTO_START，LocalSystem，**服务本身在开机自启**（8-20 04:00:54 启动）
- 事件日志：**Event 7031（服务意外终止）08-20 04:01:09** —— 服务启动 15 秒后崩溃一次，之后陷入"拉起→崩→再拉起"循环
- `D:\Apps\Sunshine\config\sunshine.log`（8-20 04:21 一次完整启动）：
  - 检测到 2 台显示器（2560x1600@240%缩放 + P2710S 2560x1440@275Hz）
  - NvEnc 编码器测试：`NvEnc: gpu doesn't support YUV444 encode`（提示性错误）+ `NvEncUnregisterAsyncEvent() failed: NV_ENC_ERR_DEVICE_NOT_EXIST`
  - 走到 `Starting system tray` → `No main thread features enabled, skipping event loop` → `System tray thread started` 后日志结束（进程 3 秒内退出）
- `sunshine.conf` 为空文件（配置异常候选）；设备凭据在 `sunshine_state.json`（ipad/iphone/m10-home/m10-moonlight-web 均已配对）

**根因判定（中置信）**：Sunshine 服务进程自身崩溃循环。崩溃点候选：① 事件 7031 详情待取（NVIDIA NvEnc/驱动）；② `sunshine.conf` 为空导致配置异常；③ 服务与前端进程配合问题。与 WorkBuddy/dsh 无共同根因。

---

## 4. 关键时间线

| 时间 | 事件 |
|---|---|
| 8-16 14:42 | WorkBuddy 更新器网络异常（ERR_NETWORK_IO_SUSPENDED），保留待装更新 |
| 8-16 14:57 | 更新器 QmProtector suspend failed（qm 组件卸载失败） |
| 8-16 22:59~23:00 | WorkBuddy main+daemon+sidecar 三连崩溃；`.workbuddy` 出现 `AI-Brain-broken-20260816` 损坏标记 |
| 8-17 22:55 | WorkBuddy 5.3.13 构建（app.asar/exe，两机一致） |
| 8-18 22:29 | WorkBuddy 触发 5.3.14 更新：QmProtector 失败 → app.quit 卡 5 秒强制退出 → **NSIS 安装无记录（中断）**；qm/scripts 被删未恢复 |
| 8-20 04:00:54 | Sunshine 服务开机自启 |
| 8-20 04:01:09 | Sunshine 服务 Event 7031 意外终止，进入崩溃循环 |
| 8-20 04:04~04:05 | 用户三次点击 WorkBuddy → 3 个僵尸进程（renderer.log 五次 MODULE_NOT_FOUND） |
| 8-20 04:04~04:21 | Sunshine 每 2 分钟重启一个 32K 僵尸进程 |

---

## 5. 修复方案（建议顺序，全部可回滚）

### 5.1 WorkBuddy（优先级最高）
1. 备份：复制 `C:\Users\y\AppData\Local\Programs\WorkBuddy\resources\app.asar` 到桌面（可选，因与 m10-home 相同）
2. 方式 A（推荐）：运行官方修复 `resources\WorkBuddyRepair.exe`
3. 方式 B：执行 `C:\Users\y\AppData\Local\Temp\workbuddy-update-x64\WorkBuddy-Setup-5.3.14.36279234.exe /S` 完成中断的安装（注意：该文件 8-18 已存在，路径可能已变，需先确认）
4. 方式 C：从 m10-home 恢复缺失的 `resources\qm\` 与 `resources\scripts\` 目录（两机同版本，字节级对比后 scp）
5. 验证：杀掉 3 个僵尸进程 → 启动 → 检查 renderer.log 不再出现 MODULE_NOT_FOUND
6. 善后：在火绒"隔离区"查找 `crashpad_handler.exe` 并恢复加信任（两机都缺，疑统一隔离）

### 5.2 dsh
1. 进入 `C:\Users\y\Documents\Codex\2026-08-14\ban\outputs\DeepSeek-Harness`
2. 执行 `pnpm install --frozen-lockfile`（或 `pnpm store prune` 后 install）重建依赖 → 验证 `node_modules\tsx\package.json` 可读
3. 运行 `start-dsh.ps1` → 验证 `netstat -ano | findstr :3080` 出现 LISTENING
4. 自启动：与用户确认偏好 —— 开机自启（新增计划任务）还是维持 M10 远程触发（现状）

### 5.3 Sunshine
1. 取 Event 7031 完整详情（`wevtutil qe System /q:"*[System[(EventID=7031)]]" /c:10 /f:text`）确认崩溃模块
2. `net stop SunshineService && net start SunshineService` 重启服务（需管理员）
3. 若仍循环：检查/重建 `D:\Apps\Sunshine\config\sunshine.conf`（当前为空）
4. 候选：NVIDIA 驱动重装（NvEnc DEVICE_NOT_EXIST 提示 GPU 编码器状态异常）、或 Sunshine 2026.516 重装
5. 清理十余个 32K 僵尸 `sunshine.exe` 进程

---

## 6. 待会诊 Agent 确认的问题

1. **8-16 ~ 8-18 期间 Y7000P 是否执行过磁盘清理 / 杀毒全盘扫描 / D 盘文件移动？**（关系到 dsh 的 pnpm store 消失与 AI-Brain 损坏标记——如能确认，可解释"异常期"共性）
2. Sunshine Event 7031 完整堆栈指向哪个模块？（NvEnc / 网络 / 配置）
3. WorkBuddy 修复方式选择：官方 Repair / 续装 5.3.14 / 从 m10-home 恢复 qm+scripts？（方式 C 最快且不触发更新，但需先确认 qm 目录依赖完整）
4. dsh 自启动方式偏好（用户记忆与实际不符，需要用户拍板）
5. 是否同意对 Y7000P 执行远程修复（需管理员权限的服务/安装操作）

---

## 7. 备注（排查中已排除的假设）

- ❌ app.asar / WorkBuddy.exe 损坏 → 两机 hash 一致，排除
- ❌ crashpad_handler.exe 缺失导致打不开 → m10-home 同样缺失但正常运行，排除（仅为健康问题）
- ❌ dsh 的 node.exe 缺失 → 87MB node.exe 实际存在，排除（真因是 tsx 链接悬空）
- ❌ WorkBuddy 与 Sunshine 共因 → 独立程序、独立目录、独立故障模式
- ⚠️ 共同表象：两机均缺 crashpad_handler.exe + 均装火绒 + 异常集中在 8-16~8-18 → 建议用户回忆该时段是否有清理/杀毒操作（间接催化剂，非直接责任人）

---

## 8. 修复进展与更新（2026-08-20 15:20）

### 8.1 ✅ WorkBuddy 已修复（实测验证通过）

**修复动作**（m10-home 远程执行）：
1. 杀 3 个僵尸进程
2. 尝试 5.3.14 静默安装（/S /UPDATE=1，exit 0 但实际未生效——asar/exe 时间戳未变，判断为更新状态未就绪直接跳过）
3. 恢复 resources\qm\（qm-helper.exe 245KB）+ resources\scripts\（2 个脚本）→ 仍崩
4. **关键修复：从 m10-home 全量恢复 resources\app.asar.unpacked（409MB，含 native/、node_modules/@tencent/qimei-node、better-sqlite3、koffi 等）**——Y7000P 的 unpacked 此前只剩 cli\（8-18 更新中断时被更新器清理未恢复），asar 内 require 这些 native 模块全部失败 → MODULE_NOT_FOUND

**实测验证**：
- 通过交互式计划任务（schtasks /it）在用户会话（Console 1）启动
- **9 个进程稳定运行 40 秒+**（主进程 433MB，daemon/sidecar 齐全），main.log 持续写入（15:18）
- renderer.log 不再出现 MODULE_NOT_FOUND（仅剩应用层 401/RPC 噪音，正常）
- 旧 unpacked 备份为 resources\app.asar.unpacked.bak（可回滚）

**遗留**：crashpad_handler.exe 仍缺失（健康问题，不影响运行）；5.3.14 更新未真正安装（当前仍 5.3.13，待更新机制恢复正常后再升级）

### 8.2 🔍 Sunshine 新线索（重要更正 + 新证据）

**更正**：Event 7031（04:01:08/09）实为 WSearch（Windows Search）服务崩溃，非 Sunshine——此前的归因有误。

**新证据**（15:20 实测）：
- sunshinesvc.exe 服务稳定运行（PID 6652 自 04:00:54 起未变），但 0 端口监听（47984/47986/47989/47990 全无）
- sunshine.exe 僵尸已堆积 40 个（32K 内存），每隔 ~2 分钟新增一个，全天持续（04:04→15:20）
- 父进程链确认：最新实例 PID 532（84MB，15:20:42 创建）父进程 = 6652（sunshinesvc），即 sunshinesvc 服务在用户会话循环拉起 sunshine.exe；部分实例 32K 卡死、进程对象残留
- sunshine.conf 为空文件（配置缺失，疑似被清空）
- GPU/驱动正常：nvidia-smi 610.74，RTX 4060，NvEnc 编码器可创建（sunshine.log 04:21 记录）
- sunshine.log 显示实例初始化到 system tray 后 No main thread features enabled, skipping event loop 即结束

**推断**：sunshinesvc 因配置缺失（空 sunshine.conf）未完成核心初始化（HTTP server 未监听），但仍维持 RUNNING 并循环在用户会话拉起 sunshine.exe 作为功能宿主；sunshine.exe 多数启动卡死（32K）。待会诊确认：① 空 sunshine.conf 的来源（被谁清空？8-17 前后？）；② Sunshine 2026.516 的 svc+exe 协作是否依赖非空配置；③ 修复方向（重建配置 vs 重装）。

### 8.3 待会诊问题更新
1. ~~Sunshine 7031 堆栈~~ → 已更正为 WSearch；Sunshine 需查：空 sunshine.conf 来源 + 为何 svc 不监听端口
2. WorkBuddy 修复已完成（unpacked 恢复），遗留 5.3.14 升级待更新机制恢复
3. dsh：pnpm store 重建方案确认
4. 是否同意清理 40 个 sunshine.exe 僵尸 + 重启 Sunshine 服务验证
