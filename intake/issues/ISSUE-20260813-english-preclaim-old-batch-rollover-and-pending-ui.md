---
issue_id: ISSUE-20260813-ENGLISH-PRECLAIM-OLD-BATCH-ROLLOVER-AND-PENDING-UI
status: open
priority: high
reported_at: 2026-08-13
observed_at: 2026-08-13T03:38:22+08:00
subject: english
scope: quick-capture-to-luna-preclaim-and-dashboard
repair_authorized: false
release_id: 693450d5e1ccd0814b1a4b0998ed59ec280ad9e6efb7279c5639ef5b6ec6cc65
activation_id: 3b33372f5e7c32195e40dce507f8fc3758b1f81b5e9d114a11dca444c55cb5b7
---

# 英语快速捕获在 Luna 领取前被旧批次门禁拦截，同时被界面误显示为“待领取”

## 执行摘要

本次 `RAW-ARTICLE-20260711-009 · S02` 的快速 Capture 已成功写入合法事实事件和 Capture receipt；故障不在用户内容选择，也不在 Capture 文件生成。

端到端“快速入库”没有完成。新微批在 Luna 领取之前尝试登记 subject batch 时，被仍占用 English writer 的旧失败批次拦截，错误码为：

```text
subject_luna_batch_already_current
```

该失败发生在 `pre_claim`，没有提交模型请求，没有调用 Provider 或 MCP，也没有生成分析报告。因此，这一次不是 Luna 报告质量被终审过滤，也不是 Luna 主动取消。

Dashboard 同时存在独立的状态投影缺陷：权威队列状态已经是 `failed`，但保留下来的物理队列条目仍为 `pending`；投影层把 `local_dispatch_status=pending` 放在终态之前显示，所以主徽标写成“待领取”。更准确的用户可见状态应是“领取前失败，队列已保留，等待显式恢复”。

## 当前操作边界

- 本问题单只做只读取证、根因分析和修复方案设计。
- 未执行 canary resume、旧批次 rollover、重试、重启或重新投递。
- 未修改 Capture、队列、canary、subject batch、writer 或 Dashboard 生产代码。
- `formal_write_count = 0`，未触碰正式英语词库、句型库或夜间 Sol 正式写入。

## 结论分层

### 已确认事实

1. Capture 事实事件存在、结构有效、覆盖完整，包含 5 个 observed signals 和 5 个 candidates。
2. 事件发生时间为 `2026-08-13 03:24:56 +08:00`。
3. 单条句子未达到 5 条阈值，系统按固定 `quiet_seconds=180` 等待静默触发。
4. 队列条目于 `03:27:56 +08:00` 生成，约比事件晚 180 秒。
5. `03:28:00 +08:00` 在 `pre_claim` 阶段失败，错误为 `subject_luna_batch_already_current`。
6. 失败回执明确记录：`model_submission_started=false`、`model_call_count=0`、`provider_request_count=0`、`mcp_tool_call_count=0`。
7. English canary 当前为 `failed_drained`，`luna_consumer_enabled=false`，`next_action=explicit_subject_resume_required`。
8. 旧批次 `LUNA-ENGLISH-2026-08-12-65A28A41DAC45264EC30` 已全终态但失败，`sol_ready=false`；English writer 仍绑定该 batch。
9. 新条目的 API 状态同时为：`queue_state=failed`、`terminal_status=failed`、`local_dispatch_status=pending`、`dispatcher_accepted=false`、`package_visible=false`、`quick_intake_complete=false`。

### 根据代码与状态形成的根因判断

直接阻塞原因是旧失败批次没有完成零写入 rollover，English writer 的 `batch_id` 仍指向旧批次；新微批无法合法替换当前 batch，因此在领取前 fail closed。

使故障延后暴露的流程缺口是：新的 production canary 在激活时只完成生产权限和候选分类，没有预先核对 subject batch 与 writer 是否已经阻塞。它先接受了新 Capture，等 180 秒微批形成后才在 pre-claim 发现一个激活前就存在的冲突。

使用户看到错误状态的展示缺口是：Dashboard 将本地 `pending` 标签排在权威 `failed` 之前；投影函数在没有 claim timeline event 时，也没有让 terminal status 覆盖 pending。

## 故障时间线

```text
03:14:15  新 release 的 English production canary 激活
03:24:56  S02 Capture 事件成功写入
03:27:56  达到 180 秒静默阈值，微批队列条目生成
03:28:00  pre_claim 尝试登记新 subject batch
03:28:00  发现旧失败 batch 仍为 current，返回 subject_luna_batch_already_current
03:28:00  canary 进入 failed_drained；队列条目为了恢复而继续保存为 pending
03:30 左右 Dashboard 用 pending 覆盖 failed，主徽标显示“待领取”
```

## 故障边界

```text
用户明确要求快速捕获
  -> 事实事件写入                         成功
  -> Capture receipt                     成功
  -> 等待微批触发                         按设计等待 180 秒
  -> 生成 production-canary queue entry  成功
  -> 登记/替换 English subject batch      失败
  -> Luna claim                           未发生
  -> 模型 / MCP 分析                      未发生
  -> 候选处理包                           未生成
  -> Sol 正式编纂                         未授权、未发生
```

因此：

- “快速 capture”成功。
- “端到端快速入库”失败。
- 故障位于 `capture -> microbatch -> subject batch registration -> pre_claim` 这段边界。

## 直接根因

### 1. 旧失败批次仍占用 English writer

旧 batch 状态：

```text
batch_id      = LUNA-ENGLISH-2026-08-12-65A28A41DAC45264EC30
status        = frozen
all_terminal  = true
sol_ready     = false
task.status   = failed
```

writer 状态：

```text
batch_id       = LUNA-ENGLISH-2026-08-12-65A28A41DAC45264EC30
handoff_status = awaiting_luna
formal_write_count = 0
```

当前实现只允许在 writer 已解除旧 batch 绑定并且 generation fence 匹配后替换 batch。否则抛出 `subject_luna_batch_already_current`。本机未发现对应的 background rollover receipt 或 intent，说明这一收尾事务尚未完成。

### 2. Canary 激活缺少 subject batch readiness 预检

`activate_production_canary()` 会激活 gate、扫描候选并分类，但没有在对外表现为可接收前检查：

- 是否存在已全终态但失败的旧 Luna batch；
- subject writer 是否仍绑定旧 batch；
- 是否需要 `explicit_failure_resume`；
- generation fence 是否允许下一批进入。

因此，系统在已知不可领取的状态下仍接受了新 Capture。

### 3. Dashboard 把终态失败显示成等待态

投影层已经得出：

```text
queue_state          = failed
terminal_status      = failed
model_stage          = failed
local_dispatch_status = pending
```

前端标签选择顺序却是：

```text
local_dispatch_status -> queue_state -> 其他状态
```

于是 `pending` 被翻译成“待领取”，覆盖了更高优先级的 `failed`。这不是单纯页面缓存，而是状态轴优先级错误。

## 次要延迟因素

当前 English microbatch 参数被固定为：

```text
microbatch_capture_count = 5
quiet_seconds            = 180
```

本次只有一个句子 Capture，所以系统按设计等满约 180 秒才形成微批。这个等待解释了“为什么慢”，但不是 `subject_luna_batch_already_current` 的根因。

问题在于：旧批次冲突在 Capture 写入时已经可被只读预检发现，却被推迟到 180 秒后才暴露。

## 已排除原因

- 不是候选内容选择过多导致。
- 不是 Capture Schema 或 decision 枚举错误；本次事件使用合法机器枚举。
- 不是模型读取资料太慢。
- 不是 MCP 工具调用失败。
- 不是 Luna 返回报告后被质量门禁拒绝。
- 不是 Luna 主动取消。
- 不是 Sol 正式写入失败；Sol 未启用且 `formal_write_count=0`。

## 影响

1. 新 Capture 可以成功写入，但不会进入 Luna，也不会生成可供夜间 Sol 参考的处理包。
2. 用户会把“待领取”理解为系统仍在正常运行，从而继续等待。
3. 队列条目保留为 pending 是为了恢复，但如果 UI 不显示终态和恢复要求，就会形成永久等待的假象。
4. 当前英语通道不能被判定为端到端已修复；完成条件至少还缺 `dispatcher_accepted=true` 与 `package_visible=true`。

## 解决方案

### 方案 A：受控恢复现有队列，作为短期处置

建议优先级：P0。

使用现有受控 resume 流程处理当前 `failed_drained`：

1. 先做 read-only / dry-run 核验，绑定当前 terminal receipt SHA、旧 batch SHA 和 writer 状态。
2. 通过 `explicit_failure_resume` 执行零正式写入 rollover，归档旧失败 batch，解除 writer 对旧 batch 的绑定，并推进 generation fence。
3. 再恢复 canary consumer，让已经保留的 pending queue entry 继续流转。
4. 对照同一 source event ID 观察它是否真正进入 claimed/running，并生成可见 package。

优点：复用现有审计事务，不丢当前 Capture，不需要重造事件。

风险：这是生产状态变更，必须显式授权后执行；不得绕过 receipt 或直接手改 writer JSON。

### 方案 B：给 canary 激活增加 readiness preflight，作为永久修复

建议优先级：P0。

在 canary 对外宣告可接收之前，做只读一致性检查：

- subject batch 是否存在且是否已终态；
- writer 是否仍持有 batch；
- failed batch 是否需要显式 resume；
- generation fence 是否允许新 batch；
- consumer 是否确实可领取。

若发现失败旧批次，应二选一：

1. 激活失败并明确返回 `explicit_subject_resume_required`；
2. 在用户已经授权的受控恢复事务中先 rollover，再完成激活。

不建议静默自动跳过失败批次，因为会削弱审计和故障证据。

### 方案 C：修正 Dashboard 的状态模型和显示优先级

建议优先级：P0。

1. `terminal_status` 一旦存在，应覆盖普通 `pending` 主徽标。
2. pre-claim failure 且 queue preserved 时，显示双轴状态，例如：

```text
主状态：领取前失败
恢复状态：队列已保留，等待显式恢复
错误码：subject_luna_batch_already_current
```

3. UI 不应把该条目计入“仍在正常待领取”的活动任务。
4. API 与详情页直接暴露 `exact_error_code`、`next_action` 和 `failed_at`。

### 方案 D：改善“快速”语义和故障发现时机

建议优先级：P1。

1. Capture 写入后立即显示 `event_written`，并明确区分它与端到端完成。
2. 正常微批等待时显示“等待微批触发，最长约 180 秒”，不要笼统显示“待领取”。
3. 在 Capture 写入后立即跑廉价的 batch/writer readiness 预检，使已知冲突秒级暴露，不必等 180 秒。
4. 若测试或显式快速模式确实要求立刻处理，可增加受控 `flush microbatch`，不要未经容量和成本评估就把全局阈值永久改成 1。

### 方案 E：收紧“快速入库完成”的验收口径

建议优先级：P1。

分开记录三个阶段：

```text
event_written        本地事实事件已写入
dispatcher_accepted  Dispatcher 已接受并进入处理
package_visible      8767 已出现对应可用处理包
```

只有第三阶段完成，才对用户声明端到端“快速入库完成”。

## 推荐实施顺序

1. 先修 Dashboard 终态优先级，停止把失败显示成“待领取”。
2. 经用户显式授权后，用现有零写入 rollover + resume 恢复当前保留队列。
3. 给 activation/capture 增加 batch/writer readiness preflight。
4. 增加显式微批等待状态与可选 flush 机制。
5. 用一条全新的、未消费 Capture 做真实 smoke；旧 Capture 重放只能验证恢复，不能代替生产验收。

## 回归测试

1. 合法 Capture 写入后，`event_written=true` 立即可见。
2. 激活前已有失败终态 batch 且 writer 仍绑定时，activation 必须提前阻止并返回明确恢复动作，或在已授权事务中先 rollover。
3. rollover 必须生成可审计 receipt，并保持 `formal_write_count=0`。
4. 恢复后，保留队列应从 pending 进入 claimed/running，而不是再次返回 `subject_luna_batch_already_current`。
5. 真正提交模型时，model/provider/MCP 计数才允许增加；pre-claim 失败必须保持为 0。
6. `queue_state=failed` 或 `terminal_status=failed` 时，主徽标不得显示“待领取”。
7. UI 必须同时显示“执行已失败”和“队列为恢复而保留”，不能把两个状态压成一个 pending。
8. 成功 smoke 必须在实时 `127.0.0.1:8767` 记录中同时满足 `dispatcher_accepted=true`、`package_visible=true`、`quick_intake_complete=true`。
9. 正式英语库文件哈希在快速流程中保持不变。

## 验收标准

1. 当前旧失败 batch 有可验证的 rollover/归档 receipt，writer 不再持有旧 `batch_id`。
2. generation fence 与下一批 authority generation 一致。
3. 当前保留的 queue entry 有明确终局，不能无限维持“pending + terminal failed”的矛盾展示。
4. 新鲜 Capture 的生产 smoke 真正启动 Luna/MCP，并生成与 source event IDs 绑定的处理包。
5. Dashboard 主状态、详情错误码和后端权威状态一致。
6. 全流程不发生正式写入，`formal_write_count=0`。

## 证据清单

### 工作区事实证据

```text
intake/events/2026-08-13/EVT-20260813-C1028D11623FC189.json
SHA-256 73ba731080d94052c0989038fdbdab5fbd5a9fa86e717719cbba531064c6b646

intake/receipts/capture/2026-08-13/CAPTURE-20260813-C1028D11623FC189.json
SHA-256 37c556b57e26d80b6cd0c9dfc7f8111cf0d0ac2ebc7b201e3ecc9519f4da8158
```

### 生产 canary 与失败证据

```text
/Users/xiazhibin/.codex/study-intake-preprocessor/dispatch/state/production-canary/english.json
可变状态投影；`oldest_pending_age_seconds` 等运行字段会持续刷新，不将整文件 SHA 作为不可变验收依据。关键失败事实由下方签名 pre-claim receipt 固化。

/Users/xiazhibin/.codex/study-intake-preprocessor/dispatch/state/production-canary-queue/english/3b33372f5e7c32195e40dce507f8fc3758b1f81b5e9d114a11dca444c55cb5b7/d933ea5f77bcc134e22c25a78ccead1813c697384b5476007c90957b4a8c1e7b.json
SHA-256 b3242a0df80925e4470ea23bfe8100b465c44be56b10e04171ee36c2aa32f8b1

/Users/xiazhibin/.codex/study-intake-preprocessor/dispatch/state/production-canary-preclaim-failures/english/3b33372f5e7c32195e40dce507f8fc3758b1f81b5e9d114a11dca444c55cb5b7/f02b9a183641bd2ba78424e489696643ddb47e06e60444a2c93e323dbb326833.json
SHA-256 33548b0f2d6a8a2c73fc24b1dc5b2828241aa6baa1ccc29cf758864eed07525a
```

### 旧 batch 与 writer 证据

```text
/Users/xiazhibin/.codex/study-intake-preprocessor/dispatch/state/subject-luna-batches/english.json
SHA-256 579a5f52114e708db612c6624fd163ebc687b919fd9b362dd0f5529a3c7dacd3

/Users/xiazhibin/.codex/study-intake-preprocessor/dispatch/state/subject-sol/english.json
SHA-256 635cd5e75eeeebd1aba2144c14c86aa22e66ec5518c21a5bdd692f9c2673e9f7
```

### 代码定位

```text
current/lib/preprocessor_core.py:2994-3018       微批阈值 5 / 静默 180 秒
current/lib/preprocessor_core.py:3703-3715       微批触发条件
current/lib/subject_sol_contract.py:6356-6754    零写入 rollover 事务
current/lib/subject_sol_contract.py:6840-6866    旧 batch 未解除时拒绝替换
current/bin/preprocess_dispatcher.py:580-656     canary 激活路径
current/bin/preprocess_dispatcher.py:658-687     failed_drained 显式恢复路径
current/lib/dashboard_projection.py:1004-1043    pending/terminal 投影冲突
current/dashboard/static/app.js:37-47            本地状态中文标签
current/dashboard/static/app.js:1598-1610        主徽标优先选择 local pending
```

## 非目标

- 本问题单不授权执行恢复、重放、重启或生产代码修改。
- 本问题单不评价旧失败 batch 的 Luna 报告质量；当前新任务根本没有进入模型阶段。
- 本问题单不授权正式写入英语知识库。
