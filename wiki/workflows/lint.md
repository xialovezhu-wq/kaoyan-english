# 英语系统 Lint 工作流

## Goal

只读检查英语系统的结构、来源、索引、答案隔离、正式数据边界和派生层状态。Lint 发现问题并给出证据，但默认不修复、合并、删除或写正式数据。

## Success criteria

- 检查对象和范围明确。
- 使用可重复的命令或方法。
- 发现项附路径、字段或证据。
- 候选、确认缺陷和未检查项分开。
- 答案泄漏、正式数据误写和来源伪造作为硬失败。
- 报告明确列出未执行的修复。
- Lint 本身不改变被检查的正式来源。

## Authorization

Lint 默认只读：

- bank/master_bank.csv
- bank/mastered_items.csv
- bank/sentence_patterns.md
- articles/
- review/
- raw 原件与受保护层
- 派生关系图和索引

可以写新的 lint 或 validation 报告，但只有用户明确要求修复时才进入修复任务。即使用户要求修复，也要按目标文件的正式授权和验证规则处理。

## Check routes

### CSV

检查：

- master_bank 每行 13 列。
- type 和 writing_value 属于受控枚举。
- CSV 引号、逗号和换行转义。
- item 去重和疑似重复。
- source_article、source_sentence、appear_count、last_seen 的明显异常。
- 已掌握 item 是否被重新放回活跃池。
- 普通低价值词是否批量长期化。

只报告候选重复，不自动合并。

### Raw and wiki

检查：

- raw source 是否登记。
- wiki 或 article 是否可追溯到 raw 或明确来源。
- practice-safe article 是否保留题目与所有选项。
- 候选区是否明确后续状态。
- 既有正式 article 是否被批量覆盖。
- video 是否有 source_id、raw_path、时间戳或 VISUAL_PENDING。

raw 原件不自动改写。

### Protected exam analysis

按 schema/protected_exam_analysis.md 检查：

- 60 篇与 300 题覆盖。
- 每题答案、非空解析、题号块和来源页。
- practice-safe 层无答案泄漏。
- 解锁提示只允许最小题号读取。
- PDF manifest 与 SHA-256。
- OCR 歧义和 Text 边界。

hidden_until_review 不是内容完成证明。

### Reference and generated examples

按 schema/reference_grounded_examples.md 检查：

- mastered 排除先于候选。
- selector 使用派生图且保持只读。
- 图谱 manifest 输入哈希未过期。
- 作文句型和词组为 approved 或 corrected。
- 大纲 occurrence 为 verified 状态。
- unreviewed、pending、rejected 只用于定位。
- lexical_candidate 没有被提升为语义、搭配或自然度证明。
- 缺 source_sentence 时返回 needs_context。
- 最多两个地基包后失败关闭。
- 正式 bank、句式卡和 review 前后哈希不变。

### Review

检查：

- tomorrow_review 是否有过期块。
- review 项是否混入已掌握排除池。
- 临时复习项是否有来源和复习提醒。
- daily 与 weekly review 是否只在对应任务中更新。
- 查询、ingest、selector 或 lint 是否误写 review。

### Tutor and cross-system

检查：

- Tutor 输入来自精选 article、wiki 或句式候选。
- 普通词没有未经筛选批量进入。
- 训练结果只同步摘要，不反写英语正式数据。
- Dashboard 和第二大脑任务没有越权改变英语源数据。

## Method

优先使用已有 verify-only 或审计脚本。没有脚本时采用最小可重复检查，并记录：

- 命令或工具
- 输入范围
- 输出摘要
- 失败证据
- 未覆盖范围

检查相互独立时可以并行；存在依赖时先验证上游来源，再检查下游派生结果。

## Output

Lint 报告包含：

- 检查对象
- 检查方法
- 通过项
- 确认缺陷
- 候选或需人工确认项
- 未执行的修复
- 正式数据是否保持不变
- 下一项最小修复建议

不要把旧快照数字写成当前事实。需要当前数量时从本次命令输出引用。

## Stop rules

- 达到用户指定范围后停止，不顺带扩大到全库。
- 发现硬失败时继续完成同一范围内的安全检查，然后报告；不自动修复。
- 证据不足时标为待确认，不把可疑项报成确定缺陷。
- 修复需要新的写入授权时停止并请求方向。
- 无法运行验证时说明原因和下一项最可靠检查。
