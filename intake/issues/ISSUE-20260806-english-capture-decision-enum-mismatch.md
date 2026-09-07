---
issue_id: ISSUE-20260806-ENGLISH-CAPTURE-DECISION-ENUM-MISMATCH
status: open
priority: high
reported_at: 2026-08-06
subject: english
scope: capture-to-dispatcher contract
repair_authorized: false
---

# 英语 Capture 候选枚举不一致，导致 8767 无处理记录

## 摘要

英语快速捕获可以生成事件文件和 Capture receipt，但事件中的 `candidate.decision` 使用了中文展示值“长期库候选”。统一 Schema 与实时 English Adapter 只接受机器枚举 `long_term_candidate`、`bbdc_candidate`、`article_only`、`not_recommended`，因此这些事件在进入 Dispatcher、Luna 和处理包生成之前被拒绝。

这不是 Luna Max 的推理质量或输出质量问题。首要故障位于 Luna 调用之前的 Capture 生产端、Schema 校验和 English Adapter 接收协议之间。

## 当前操作边界

- 本问题单仅做只读取证和记录。
- 未修改事件、Schema、生产脚本、Dispatcher 或 Luna 配置。
- 未停止、重启或干预任何后台进程。
- 当前三个原始事件保持原样，`formal_write_count = 0`。

## 用户可见现象

访问 `http://127.0.0.1:8767/` 时，看不到本次英语快速入库对应的处理记录或处理包。

2026-08-06 实时 API 结果：

```text
GET /api/v1/summary?date=2026-08-06&subject=english
counts.total = 0
pipeline.captured = 0
pipeline.luna_processed = 0
pipeline.package_ready = 0

GET /api/v1/items?date=2026-08-06&subject=english
items.length = 0
model_call_count = 0
formal_write_count = 0
```

## 受影响事件

```text
EVT-20260806-8F4D09BF50F3F1B3
EVT-20260806-507660196D4F941D
EVT-20260806-4DF6447806282008
```

三个事件均为 `sentence_captured`，每个候选的实际值均为：

```json
"decision": "长期库候选"
```

事件目录：

```text
intake/events/2026-08-06/
```

## 预期行为

1. Capture 生产端只应写入统一 Schema 允许的机器枚举。
2. 写入成功并生成 receipt 后，English Dispatcher 应能发现有效事件。
3. 达到批量或静默触发条件后，8767 应展示捕获记录及后续处理状态。
4. 快速捕获阶段必须继续保持 `formal_write_count = 0`。

## 实际行为

1. 生产端写入了 Schema 不允许的中文展示值。
2. Capture 文件和 receipt 的存在造成了“快速入库已完成”的错误成功信号。
3. English Adapter 在扫描时抛出 `english_capture_candidate_invalid`。
4. 事件未进入 Dispatcher，未调用 Luna，也未生成处理包；8767 显示为零记录。

## 已确认根因

工作区 Schema `schema/english_pipeline/capture-event-v1.schema.json` 规定：

```json
"decision": {
  "enum": [
    "long_term_candidate",
    "bbdc_candidate",
    "article_only",
    "not_recommended"
  ]
}
```

实时接收器 `/Users/xiazhibin/.codex/study-intake-preprocessor/current/lib/preprocessor_core.py` 使用相同机器枚举，并在不匹配时抛出：

```text
english_capture_candidate_invalid
```

因此，根因是 Capture 生产端写入值与统一 Schema、English Adapter 接收值不一致，同时写入前验收未阻止无效事件落盘。

## 关联设计缺陷

### 1. 成功判定不完整

当前流程可能仅依据事件文件或 Capture receipt 宣告成功，没有把以下结果纳入完成门禁：

- 事件通过统一 Schema 校验。
- English Adapter 成功接收。
- 8767 能看到对应记录。

### 2. 无效事件可能阻断整个事件扫描

English Adapter 的 `_load_events()` 会先逐个执行 `_validate_event()`，全部验证完成后才处理 `sentence_correction` 的 supersede 关系。因此，仅追加一个修正事件不能绕过已经落盘的无效原事件；旧事件仍会先触发验证失败。

### 3. 可观测性不足

8767 当前只显示英语总数为零，没有在列表中暴露被拒事件、失败代码及原始事件 ID。用户看到的效果与“完全没有捕获”相同，难以区分生产端未写入和接收端拒绝。

## 建议修复计划

### P0：统一协议并阻止再次产生无效事件

1. 在 Capture 生产端将展示值映射为机器枚举，例如“长期库候选”映射为 `long_term_candidate`。
2. 事件落盘前使用同一份 JSON Schema 做强制校验。
3. Schema 校验失败时禁止生成成功 receipt，并返回明确错误。
4. 增加覆盖四种 `decision` 枚举以及非法中文展示值的契约测试。

### P0：安全处理既有无效事件

1. 不直接静默改写不可变原始事件。
2. 设计显式、可审计的兼容或迁移机制，使三个既有事件不再阻断扫描。
3. 迁移结果应保留原事件哈希、修复映射、执行时间和修复 receipt。
4. 不能只追加普通 `sentence_correction`，因为当前加载顺序会先验证并拒绝原事件。

### P1：补齐接收与界面可观测性

1. English Adapter 对单个非法事件应提供隔离和明确失败记录，避免整个日期无声归零。
2. 8767 应显示 rejected/failed 数量、错误代码和事件 ID。
3. Capture 完成回执应区分 `event_written`、`dispatcher_accepted`、`package_visible`，不得统称“已入库”。

## 回归测试建议

1. 合法的 `long_term_candidate` 事件能被 English Adapter 接收。
2. 中文展示值不能未经映射直接落盘。
3. 单个非法事件不会让同日期的其他合法事件全部消失。
4. 历史无效事件可以通过审计式迁移恢复，且原始证据不被覆盖。
5. Dispatcher 未触发 Luna 前，界面能显示捕获或明确等待状态。
6. 全流程保持 `formal_write_count = 0`，直到用户明确启动正式编纂。

## 验收标准

修复完成后，至少同时满足：

1. 三个受影响事件均有可追溯的修复或迁移 receipt。
2. `GET /api/v1/summary?date=2026-08-06&subject=english` 不再返回 `pipeline.captured = 0`。
3. `GET /api/v1/items?date=2026-08-06&subject=english` 能看到与三个事件绑定的记录或明确的迁移后记录。
4. 达到触发条件后生成对应处理包，并能追溯到原始事件 ID。
5. 不出现重复候选、重复 Luna 调用或重复处理包。
6. `formal_write_count` 仍为 0，正式词库与句型库没有被本次修复改写。
7. 生产端、Schema、English Adapter 的契约测试全部通过。

## 非目标

- 本问题不评价 Luna Max 的分析质量。
- 本问题不授权正式写入英语词库或句型库。
- 本问题不授权在当前后台任务运行期间修改或重启相关进程。

