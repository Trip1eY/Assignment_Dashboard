# Y7000P 三应用启动故障二次会诊意见

> Review date: 2026-08-20 16:04 (GMT+8)  
> Reviewed source: `DIAG-20260820-Y7000P-Startup-Failures.md`  
> Agent-ID: `chatgpt@cloud#20260820-1604-y7000p-diag-review`  
> Task-ID: `Y7000P-STARTUP-DIAG-REVIEW-001`  
> Scope: **只做二次诊断与执行建议，不覆盖原始 WorkBuddy 诊断证据。**

---

## 0. 二次会诊结论

原报告后续更新已经纠正了最重要的一处误判：**Event 7031 是 WSearch，不是 SunshineService。**

当前结论：

| 应用 | 二次会诊结论 | 置信度 |
|---|---|---:|
| WorkBuddy | 根因已闭环，修复已实测通过。5.3.14 更新中断后，不只是 `qm/scripts`，而是 `resources/app.asar.unpacked` 大片缺失；全量恢复 unpacked 后恢复正常 | 极高 |
| DSH | `D:\.pnpm-store\v11` 内容丢失导致 pnpm symlink 悬空，`tsx` 不可加载，判断成立 | 很高 |
| DSH 自启动 | 与依赖损坏是两个独立问题：目前 Windows 中没有任何真实 DSH 自启动项 | 极高 |
| Sunshine | `sunshinesvc.exe` supervisor 在正常运行，但 child `Sunshine.exe` 周期性退出；真正退出原因尚未抓到 | 很高 |
| Sunshine 空 `sunshine.conf` | 目前只能算候选现象，**不能作为首要根因** | 高 |
| Sunshine NVENC/驱动 | 当前证据不足以支持直接重装 NVIDIA 驱动 | 高 |
| 三应用共同根因 | 暂无证据支持单一直接共同根因；最多存在 8-16~8-18 某次清理/安全软件/文件操作作为上游诱因的可能性 | 高 |

**建议撤回“统一 Windows 启动层故障”作为主假设。** 三个应用目前展示的是三条不同的直接故障链。

---

## 1. WorkBuddy：诊断已闭环，不建议继续扩大操作

原始诊断最初把缺失范围聚焦在 `resources\qm` 和 `resources\scripts`，但后续修复已经证明真正缺失范围更大：

- Y7000P 的 `resources\app.asar.unpacked` 此前只剩 `cli\`；
- 从 m10-home 恢复约 409 MB 的完整 `app.asar.unpacked` 后，native 模块与 `@tencent/qimei-node`、`better-sqlite3`、`koffi` 等恢复；
- 9 个 WorkBuddy 进程稳定运行 40 秒以上；
- 主进程约 433 MB；
- renderer 不再出现 `MODULE_NOT_FOUND`。

这已经形成完整因果闭环：

```text
5.3.14 更新开始
  -> 更新器清理旧 unpacked/qm 等组件
  -> app.quit 卡住并被强制退出
  -> NSIS 安装未完成
  -> 新 unpacked 未完整恢复
  -> app.asar require native/unpacked 依赖失败
  -> WorkBuddy 启动崩溃
  -> 全量恢复 unpacked
  -> 启动恢复
```

### 建议

1. 保留 `app.asar.unpacked.bak` 一段时间作为回滚证据。
2. **暂时不要为了“修得更干净”立即强制升级 5.3.14。** 当前 5.3.13 已恢复正常，先保持稳定。
3. 如果后续升级，再单独观察 WorkBuddy 更新器是否仍在 `QmProtector suspend` 阶段失败。
4. `crashpad_handler.exe` 缺失暂不作为当前启动故障处理，因为 m10-home 同样缺失但可正常运行。

WorkBuddy 本轮可视为 **Resolved / Soak**。

---

## 2. DSH：原诊断成立，但修复动作建议稍作调整

### 已确认的直接故障

```text
D:\.pnpm-store\v11 被清理/缺失
  -> node_modules 内 pnpm 链接仍在
  -> node_modules\tsx 变成悬空链接
  -> node --import tsx/esm 加载失败
  -> start-dsh.ps1 退出
  -> 3080 无监听
```

`node.exe` 本身存在，所以**不需要复制或替换 Node**。

### 建议恢复顺序

不要先执行 `pnpm store prune`。当前 store 已经接近被清空，prune 的信息价值和修复价值都很低。

推荐：

```text
1. 保留 C:\Users\y\.dsh（sessions / profiles / settings / storages）
2. 记录当前 pnpm --version
3. 进入 DeepSeek-Harness 源码目录
4. 将现有 node_modules 改名备份，避免继续使用悬空链接
5. 执行 pnpm install --frozen-lockfile
6. 若 lockfile/缓存状态导致安装无法完整重建，再考虑 pnpm install --force
7. 验证 node_modules\tsx\package.json 可读
8. 直接运行启动命令
9. 验证 127.0.0.1:3080 LISTENING
10. 再通过 M10 的 dsh-start 路径验证一次远程启动
```

### DSH 还有第二个独立问题：没有自启动

原报告已经检查：

- Registry Run：无 DSH；
- Task Scheduler：无 DSH；
- Startup Folder：无 DSH。

所以：

```text
依赖损坏 = 手动也启动不了
没有自启动 = 即使修好依赖，重启后仍不会自动运行
```

这两个问题必须分开验收。

如果目标是“Y7000P 登录后 DSH 自动恢复”，建议最终建立正式任务：

```text
Task: Y7000P-DSH
Trigger: At logon (user y)
Delay: 20~30 seconds
Action: stable-path\start-dsh.ps1
Policy: if 3080 already listening -> exit 0
Restart on failure: bounded retries, not infinite
Logging: stdout/stderr to stable logs directory
```

### 长期结构问题

当前运行目录：

`C:\Users\y\Documents\Codex\2026-08-14\ban\outputs\DeepSeek-Harness`

这是一个历史 Agent 工作目录，不适合作为长期服务部署目录。

建议本次先恢复服务，不要同时大迁移；稳定后单独做部署规范化，例如：

`D:\Services\DeepSeek-Harness\`

并让 M10 Control Center 的 `_DSH_START_SSH` 只引用这个稳定路径。

---

## 3. Sunshine：当前最重要的是“抓 child 退出证据”，不是继续猜配置/显卡

### 3.1 `No main thread features enabled, skipping event loop` 是正常日志

这里需要纠正诊断方向。

Sunshine Windows 当前实现中，system tray 使用独立线程，因此主线程没有其它事件循环需求时，本来就会输出：

```text
No main thread features enabled, skipping event loop
```

随后主线程等待 shutdown event。

因此这句话**不是 Sunshine 自己决定退出，也不是崩溃点。**

正常启动链应该继续到 HTTP / config HTTP / RTSP 线程开始工作，并出现类似：

```text
Configuration UI available at [https://...:47990]
```

Y7000P 的异常可以更准确描述为：

```text
encoder/display 初始化已基本走完
  -> system tray 初始化
  -> 主线程进入正常等待状态
  -> 但 config HTTP / nvhttp / RTSP 未形成持续监听
  -> Sunshine.exe 很快退出
  -> sunshinesvc.exe 发现 child 结束
  -> supervisor 再次拉起 child
  -> 循环
```

### 3.2 40 个 `sunshine.exe` 与 Service supervisor 行为高度吻合

`sunshinesvc.exe` 的官方 Windows 实现本来就是：

```text
SunshineService (LocalSystem)
  -> 获取 active console session
  -> CreateProcessAsUserW 启动 Sunshine.exe
  -> 等待 child / stop / session change
  -> child 退出后再次循环拉起
```

所以“每隔一段时间新增 Sunshine.exe”本身不是根因，而是 **supervisor 对 child 异常退出的结果**。

### 3.3 最关键的新取证点：`C:\Windows\Temp\sunshine.log`

`sunshinesvc.exe` 源码明确：service 会打开系统 Temp 下的 `sunshine.log`，并把 child `Sunshine.exe` 的 stdout/stderr 继承到这个文件。

因为服务运行账户是 LocalSystem，优先检查：

```text
C:\Windows\Temp\sunshine.log
```

并检查可能的轮换/旧日志。

**这份日志目前比 `D:\Apps\Sunshine\config\sunshine.log` 更重要。** 后者是 Sunshine 自身应用日志；前者有机会包含 child 在应用日志关闭/flush 之后的 stderr、启动器错误或退出前最后输出。

### 3.4 下一轮只取证，暂时不要做这几件事

在获取下面证据前，不建议：

- 不要重建/覆盖 `sunshine.conf`；
- 不要重装 NVIDIA 驱动；
- 不要直接重装 Sunshine；
- 不要把 `NV_ENC_ERR_DEVICE_NOT_EXIST` 单独认定为根因。

原因：

1. `sunshine.conf` 为空目前只是异常候选，尚无证据证明空配置必然让 Sunshine 退出；
2. GPU 可被正常识别，encoder probe 能进行；
3. `NvEncUnregisterAsyncEvent() failed: NV_ENC_ERR_DEVICE_NOT_EXIST` 发生在 encoder probing/cleanup 场景时，不足以单独证明驱动损坏；
4. 现在直接重装会破坏最有价值的现场。

---

## 4. Sunshine 下一轮精确诊断清单

请在修改任何 Sunshine 配置前，执行一次只读取证。

### A. Service child stdout/stderr

读取：

```text
C:\Windows\Temp\sunshine.log
```

以及同目录可能的轮换文件。

保存最后一次 child 启动的完整尾部，而不是只截最后几行。

### B. Windows Application Error / WER

重点查同一时间窗：

- Event ID 1000 — Application Error
- Event ID 1001 — Windows Error Reporting

目标是拿到：

```text
Faulting application name
Faulting module name
Exception code
Fault offset
Process ID
Application path
Module path
Report ID
```

如果有 WER dump 路径，也记录路径，但不要为了会诊上传含敏感数据的大型 dump，先记录 metadata 即可。

### C. child exit code

建议在不改 Sunshine 本体的前提下，记录 `sunshinesvc` 拉起的最新 child：

```text
PID
Parent PID
Start time
Exit time
Exit code
Session ID
```

这能区分：

- 正常主动退出；
- Windows exception；
- service/job kill；
- 初始化返回非零。

### D. 端口启动边界

观察每个 child 生命周期内：

```text
47984
47986
47989
47990
```

是“从未监听”，还是“短暂监听后退出”。

这是非常关键的分界：

```text
从未监听 -> 更偏初始化 / bind / TLS / config-http 前故障
短暂监听 -> 更偏运行后 crash / session / tray / external termination
```

### E. 配置文件只校验，不修改

只检查：

- `sunshine_state.json` JSON 是否可解析；
- apps 配置 JSON 是否可解析；
- credentials/cert/key 文件是否存在且权限可读；
- `sunshine.conf` 大小、mtime、是否真的为 0 字节；
- 与最后一次正常工作的备份/历史版本是否存在。

暂时不要自动“生成一个默认 sunshine.conf”。

---

## 5. 推荐执行顺序

### Phase 1 — Sunshine 现场取证

优先完成 Sunshine 新日志 / WER / exit code 采集。

理由：当前 Sunshine 现场仍在持续复现，每一次 child 重启都能提供证据；先重装会丢失它。

### Phase 2 — DSH 修复

DSH 根因已经比较明确，可以直接修复：

```text
保留 ~/.dsh
-> 重建 pnpm 依赖
-> 验证 tsx
-> 验证 3080
-> 验证 M10 远程启动
```

### Phase 3 — Sunshine 定点修复

依据 Phase 1 证据再决定：

- TLS / cert / key；
- JSON/state/config；
- bind/port；
- runtime DLL；
- NVIDIA；
- Sunshine 安装文件。

**不要反过来先随机重装。**

### Phase 4 — DSH 自启动

服务恢复之后再创建正式自启动任务，避免“坏服务被自动无限拉起”。

### Phase 5 — 冷启动验收

完整重启 Y7000P，验收：

```text
WorkBuddy
  -> 用户会话中稳定运行
  -> 不再 MODULE_NOT_FOUND

DSH
  -> 自动/指定机制启动
  -> 3080 LISTENING
  -> Web 可访问

Sunshine
  -> SunshineService RUNNING
  -> 只有合理数量的 Sunshine child
  -> 47990 等端口持续监听
  -> Moonlight 可发现/连接
```

观察至少 2 个 Sunshine supervisor 重试周期以上，确认不是短暂假绿。

---

## 6. 对“共同根因”的最终判断

当前不建议说“完全没有任何共同因素”，也不建议说“三者就是一个故障”。

更准确的是：

### 直接根因层

```text
WorkBuddy -> 自身更新事务中断 / unpacked 未恢复
DSH       -> pnpm store 丢失 / symlink 悬空
Sunshine  -> child 周期性退出，退出原因尚待抓取
```

三者目前没有同一个已证实的直接根因。

### 上游诱因层

8-16~8-18 的时间集中度仍值得保留为调查线索：

- 是否执行过 D 盘清理；
- 火绒是否进行过扫描/清理/隔离；
- 是否移动过 pnpm store；
- 是否运行过磁盘优化/空间清理工具；
- WorkBuddy 更新失败是否与当时系统 I/O / 安全软件行为存在交互。

但在拿到火绒隔离历史、文件操作历史或其他证据之前，**不要把杀毒软件/清理动作写成已确认共同根因。**

---

## 7. 给执行 Agent 的下一步任务

```yaml
task_id: Y7000P-STARTUP-RECOVERY-NEXT
priority: P0

objectives:
  - preserve Sunshine failure evidence before mutation
  - restore DSH dependency graph and verify port 3080
  - identify Sunshine child exit reason from service stdout/stderr + WER + exit code

sunshine_read_only_first:
  - read C:\Windows\Temp\sunshine.log and rotated logs
  - collect Application Event 1000/1001 around latest child exits
  - record child PID/PPID/session/start/exit/exit_code
  - determine whether 47984/47986/47989/47990 ever briefly listen
  - validate JSON/config/cert/key presence without modifying them

sunshine_do_not_do_yet:
  - do not rebuild sunshine.conf
  - do not reinstall NVIDIA driver
  - do not reinstall Sunshine
  - do not delete evidence before collecting it

DSH:
  - preserve C:\Users\y\.dsh
  - record pnpm version
  - move broken node_modules aside
  - run pnpm install --frozen-lockfile
  - verify node_modules\tsx\package.json
  - run start-dsh.ps1
  - verify :3080 LISTENING
  - verify M10 dsh-start path

acceptance:
  - DSH survives a clean launch and 3080 remains listening
  - Sunshine failure is reduced from "unknown child exit" to a concrete failure class with evidence
  - no speculative driver/config rewrite is performed without evidence
  - all actions and evidence are appended back to the original DIAG or a follow-up report
```

---

## 8. Reviewer handoff

本 review 不要求执行 Agent照单全收。如果新证据与上述判断冲突，应优先服从**机器现场证据**。

尤其是 Sunshine：下一步目标不是“证明某个猜测正确”，而是获取 `Sunshine.exe` **真正退出前后的 stdout/stderr、WER 和 exit code**，然后再决定修复路线。

**Reviewer:** `chatgpt@cloud#20260820-1604-y7000p-diag-review`
