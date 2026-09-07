# 英语资料 Ingest 工作流

## Goal

把文章、网页、字幕、音频、视频笔记和 NotebookLM 输出保存为可追溯的 raw 与 wiki 资产，并只在用户明确授权时进入正式学习数据。

## Success criteria

- 原始内容、来源字段和 source_id 可追溯。
- 当前目标的 raw、索引和 wiki 或 practice-safe 文章页完整。
- 文章与句子具有可供快速捕获复用的稳定身份和来源哈希。
- 题目与选项一起保存。
- 答案与解析按受保护规则保存，不泄漏到自主练习页。
- 候选与正式 bank 分开。
- 缺失信息明确标记，不编造。
- 最终回执说明修改、验证、未写正式数据和待补充项。

## Inputs

按当前材料只读取必要入口：

- prompts/codex_prompt.md
- schema/schema.md
- raw/index.md
- 目标类型模板
- 可能重复的来源或文章页
- 涉及历年答案时读取 schema/protected_exam_analysis.md
- 只有正式入库任务才读取对应 bank、mastered items 和写入模板

不把所有索引、日志和模板作为固定前置。

## Authorization

Ingest 默认允许：

- 保存当前目标的 raw 原件或清洗结果。
- 登记 raw/index.md。
- 新增或更新当前目标的 wiki、practice-safe article 和候选区。
- 运行结构、来源和泄漏检查。

Ingest 默认不允许：

- 写 bank/master_bank.csv、bank/mastered_items.csv 或 bank/sentence_patterns.md。
- 写任何 review 文件。
- 批量覆盖既有正式文章学习记录。
- 因普通词或候选有价值而自动正式入库。

只有用户明确要求精选正式入库或当前任务就是正式入库时，才转对应流程。

## Mode selection

| 模式 | 结果 |
|---|---|
| raw only | 只保存原始来源并登记索引，不创建 article |
| articles context | 创建或更新 practice-safe 文章语境 |
| raw + articles | 同时保存可追溯 raw 与文章语境 |
| protected analysis | 按受保护契约保存答案和解析，不嵌入 practice-safe 页 |
| media intake | 保存字幕、音频、视频或 NotebookLM raw，并创建对应 wiki 候选页 |

## Workflow

1. 识别材料类型、用户要求的模式和允许写入的路径。
2. 从用户材料提取来源年份、试卷、Text、标题、平台、日期、source type、答案或解析可用性和用户标注。
3. 搜索标题、年份与 Text、首句、来源或已有 source_id，避免重复创建。
4. 缺失字段写待确认、待补充、未标明或未记录；不补造。
5. 保存 raw 原件或清洗结果，并在 raw/index.md 登记稳定 source_id。
6. 创建或更新目标 wiki 或 article：
   - 原文完整；
   - 题目和所有选项完整；
   - 逐句精读、题目逻辑和候选入口存在；
   - practice-safe 页面不含答案或解析正文。
   - 能稳定生成或复用 `source_id`、`sentence_id` 与 `source_hash`，并把后续快速捕获交给 `wiki/workflows/english-async-intake.md`。
7. 用户提供答案或解析时：
   - 历年真题转 schema/protected_exam_analysis.md；
   - 普通材料保留可追溯的受保护 raw 引用；
   - 聊天回执不复述答案。
8. 普通词、词组和结构只进入候选区。
9. 运行当前材料的结构、来源、答案泄漏和索引检查。
10. 回答完成状态和缺口后停止。

## Web sources

网页先用 defuddle 提取干净 Markdown，再进入 raw/web 或 raw/articles。页面抓取失败时尝试一个有意义的官方或原始链接后备；仍失败就报告来源缺口，不生成正文。

## Batch exam PDFs

- manifest 记录来源 PDF、页数、SHA-256 和角色。
- 真题视觉页是原文、题目和选项的权威。
- practice-safe 语料和文章页不含答案。
- 答案与出版方解析进入 raw/protected/exam-reading-analysis/。
- 构建后分别验证 60 篇结构、每篇 5 题与 A 至 D 选项、页脚噪声、答案泄漏，以及受保护层的 300 题答案、解析和来源页。
- 既有学习页只建立链接或做被授权的目标更新，不批量覆盖。

## Media and NotebookLM

- 原始字幕、视频笔记和音频转写放入 raw/video 或 raw/audio。
- NotebookLM 导出放入 raw/notebooklm，并视为 raw，不把其总结当原始事实。
- 缺时间戳写 VISUAL_PENDING。
- 候选表达、句型和写作素材先留在 wiki。
- 需要正式 CSV 时转明确的正式入库任务。

## Output

回执只包含：

- 本次识别和模式
- 已保存或更新的路径
- source_id 或待确认
- 原文、题目、选项、受保护答案和解析的保存状态
- 已建立的精读或候选入口
- 正式数据是否保持未修改
- 已运行验证
- 待补充信息
- 下一步技能或流程

逐句学习开始后，完整学习事实进入现行 `intake/packages/` 并保持原始消息和附件；`intake/events/` 只保留历史兼容证据，不接收新学习。文章页不充当后台队列。

## Stop rules

- 缺失字段不影响安全保存时标记后继续。
- 缺失字段会造成错误归档、覆盖或答案串篇时，只询问最小缺失信息。
- 发现重复目标时更新或链接现有资产，不另建重复页。
- 正式写入未授权时停在候选区。
- 答案存储位置不明确时不写 article，转受保护契约。
- 验证失败时报告失败项，不宣称 ingest 完成。
