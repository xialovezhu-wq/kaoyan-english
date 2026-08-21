# 英语系统数据与流程契约

## Goal

把原始证据、可学习页面、正式学习数据和操作规则分层保存，使每个结果可追溯、可验证，并避免查询或整理任务越权写入正式库。

## Success criteria

- 每项资料有明确层级和来源。
- 候选状态不会被误当成正式事实或已掌握状态。
- practice-safe 页面与受保护答案层保持隔离。
- 正式 bank、句式卡和 review 写入都能追溯到用户授权。
- 派生图、索引和缓存可以重建，且不会反向污染正式来源。
- 当前任务完成后运行对应验证并在证据不足时停止。

## Rule ownership

- prompts/codex_prompt.md 负责跨任务角色、协作方式、权限、路由、聊天输出和停止规则。
- 本文件负责层级、路径和稳定数据边界。
- schema/protected_exam_analysis.md 负责答案存储、读取和解锁。
- schema/reference_grounded_examples.md 负责系统生成例句的四层地基。
- wiki/workflows/ingest.md、query.md、lint.md 分别负责具体操作。
- 专项文件在自己的领域内拥有细节；冲突时对答案披露、来源和正式写入采用更保守的规则。

历史 handoff、validation、raw 包内旧提示和统计快照只作证据，不覆盖现行契约。

## Layer ownership

| 层级 | 路径 | 负责内容 | 边界 |
|---|---|---|---|
| raw sources | raw/ | 原文、字幕、网页清洗、NotebookLM 导出、用户原始摘录 | 保留原貌；不精翻、不替代正式判断 |
| protected evidence | raw/protected/ | 答案、出版方解析、逐页 OCR 和题号索引 | 不进入 practice-safe 页；按解锁条件最小读取 |
| reference and derived | raw/reference_sources/；raw/reference_relations/；raw/articles/exam-reading-corpus/ | PDF manifest、OCR、真题结构化语料、派生关系图 | 候选与词元重叠不等于审核结论 |
| wiki and articles | articles/；wiki/ | practice-safe 文章、精读记录、候选、主题和操作记录 | 候选不等于正式 bank；既有页面不批量覆盖 |
| intake events and projections | intake/events/；intake/views/；intake/candidates/；intake/nightly/；intake/receipts/ | 不可变逐句事实、快速文档、Luna 候选、冻结批次、恢复事务与 receipts | Markdown 是投影；白天和 Luna 的 formal_write_count 固定为 0 |
| formal study data | bank/；review/ | 长期库、掌握排除池、句式卡和复习状态 | 只在对应正式任务中写入 |
| schema | schema/；prompts/；wiki/workflows/ | 权限、路由、字段和验证规则 | 不存学习结论，不复制多份细节真源 |

## Stable paths

- articles/：文章学习页；自主练习页保持 practice-safe。
- bank/master_bank.csv：13 列长期结构化库。
- bank/mastered_items.csv：有主动正确使用证据的排除池。
- bank/sentence_patterns.md：SP 句式卡正式库。
- review/tomorrow_review.md：临时复习清单。
- review/daily_review_log.md：每日复盘日志。
- review/weekly_review.md：只在周复盘任务中更新。
- raw/protected/exam-reading-analysis/：历年阅读答案与解析受保护层。
- raw/reference_relations/writing-vocabulary-foundation/：可重建四层地基关系图。
- intake/events/YYYY-MM-DD/：逐句快速捕获事实真源；事件不可覆盖。
- intake/views/YYYY-MM-DD/：按事件重建的快速入库 Markdown。
- intake/candidates/YYYY-MM-DD/：Luna 结构化候选与截图式 Markdown。
- intake/nightly/YYYY-MM-DD/：批次 manifest、Sol actions、提交日志与可恢复事务。
- intake/receipts/capture/YYYY-MM-DD/：快速捕获与文章完成 receipt。
- intake/receipts/nightly/YYYY-MM-DD/：夜间 dry-run 与正式写入 receipt。
- intake/receipts/recovery/YYYY-MM-DD/：中断事务恢复 receipt。

旧目录继续兼容。除非用户明确要求结构迁移，否则不重命名路径或字段。

## Authorization

默认只读正式学习数据的任务：

- 回答、解释、查询、诊断和计划。
- 普通 intake、候选筛选和词汇导出。
- selector、关系图构建或 verify-only。
- lint、Dashboard 汇总和第二大脑候选同步。

允许写入的任务：

- 当前 intake 可以写被点名的 raw、索引、practice-safe 文章页和候选区。
- 明确正式入库可以写被点名的 master_bank 条目。
- 明确句式入库可以写 sentence_patterns。
- 明确掌握维护且证据充分时可以写 mastered_items。
- 明确每日、明日或周复盘任务可以写对应 review 文件。
- “开始 YYYY-MM-DD 英语正式入库”允许确定性 writer 应用该日期冻结批次中已通过门禁的安全 action；歧义项保留 needs_user，不扩大到其他日期或历史操作。

写入正式数据前先验证来源、去重、字段和当前授权。普通生词、候选价值、系统生成例句或查询结果本身不提供写入授权。

## Reference sources

- 历年阅读 practice-safe 入口：wiki/reading/历年真题阅读总索引.md。
- 受保护答案入口：raw/protected/exam-reading-analysis/index.md。
- 大纲词汇入口：wiki/vocabulary/大纲词汇参考库.md。
- 作文审核白名单：wiki/writing/作文造句可用白名单.md。
- 四层地基关系图说明：wiki/relationships/作文-大纲词-错词关系图谱.md。

参考 ID 证明来源，不替代 master_bank ID 或 SP ID。未审核 OCR、pending、rejected 和 lexical_candidate 只用于定位。

## Task routes

- 新材料进入系统：wiki/workflows/ingest.md。
- 查询表达、句型、旧词或写作素材：wiki/workflows/query.md。
- 检查结构、来源和边界：wiki/workflows/lint.md。
- 系统生成例句：schema/reference_grounded_examples.md。
- 历年答案与解析：schema/protected_exam_analysis.md。
- 视频与 NotebookLM：schema/video_ingest_template.md。
- 快速捕获、Luna 与夜间正式编纂：wiki/workflows/english-async-intake.md。

只读取当前路线需要的文件，不把所有索引和模板作为每次任务的固定前置。

## Automation boundary

可以自动执行：

- raw 登记、网页清洗、字幕分段和索引链接。
- practice-safe 语料、OCR 参考层和派生关系图的可重建输出。
- 候选提取、只读 selector、lint 报告和验证。
- 不可变快速捕获、快速 Markdown 投影、文章结束 A/B/C 输出、Luna 候选与只读 Dashboard 投影。

需要明确任务授权：

- master_bank、mastered_items、sentence_patterns 和 review 写入。
- 既有正式文章学习记录的修改。
- 重复词合并、目录迁移、字段重命名或历史删除。

Luna 和 Sol 模型进程没有正式库写权限。Sol 只提交类型化 action，确定性 writer 在精确批次授权、写前哈希、文件锁、提交日志和写后验证全部成立时执行正式写入。

## Stop and validation

- 来源字段缺失且会改变结果时，标为待确认并停止该写入。
- practice-safe 与受保护答案边界不清时，不写文章页答案，转 schema/protected_exam_analysis.md。
- 关系图或缓存过期时，重建并 verify-only；验证失败就停止。
- 正式写入未授权时，在候选结果处停止。
- 同一幂等键对应不同 payload、来源哈希漂移或正式文件写前哈希漂移时失败关闭，不覆盖旧事实，也不做部分无回执写入。
- 修改后运行当前层的最小结构、来源、哈希或零写入检查；未通过时不得声称完成。
