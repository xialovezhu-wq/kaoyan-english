# English LLM Wiki Index

本页是英语知识层入口。`wiki/` 保存 LLM 维护后的主题页、表达页、视频语料页和规则化索引；旧目录继续兼容，不迁移、不改名。

## 层级映射

| 层级 | 路径 | 角色 | 维护边界 |
|---|---|---|---|
| raw sources | `raw/` | 原始资料层 | 只读登记，不精翻、不改写、不直接入长期库 |
| reference sources | `raw/reference_sources/`; `raw/articles/exam-reading-corpus/`; `raw/protected/exam-reading-analysis/` | PDF 参考、结构化语料与受保护答案解析层 | 保留 manifest、OCR、题号块和审核状态；practice-safe 页面不嵌入答案，不自动进入正式库 |
| derived relations | `raw/reference_relations/writing-vocabulary-foundation/` | 用户错词、作文句型 / 词组、大纲 occurrence 与 SP 的只读派生关系图 | `unreviewed` 只入图；`lexical_candidate` 不等于语义 / 搭配；不回写正式库 |
| intake pipeline | `intake/` | 逐句不可变事件、快速视图、Luna 候选和夜间 receipts | Markdown 为投影；白天与 Luna 不写正式库 |
| wiki | `articles/` | 文章精读 wiki | 保存文章、题目、用户作答、错因、精翻记录和候选内容；legacy / 已完成复盘页可保留解析，practice-safe 页只保留受保护引用 |
| wiki | `wiki/video/` | 视频语库 wiki | 保存字幕精读、主题表达、时间戳段落、候选入库项 |
| wiki | `bank/sentence_patterns.md` | 句式结构 wiki | 可复用句式卡片库，按 SP 规则归并 |
| structured bank | `bank/master_bank.csv` | 长期结构化知识库 | 13 列固定，只收少而精的长期复习项 |
| review state | `review/` | 复习状态层 | `tomorrow_review.md` 临时，`daily_review_log.md` / `weekly_review.md` 为日志 |
| schema | `schema/` 与 `prompts/codex_prompt.md` | 规则层 | `prompts/codex_prompt.md` 最高优先，schema 做三层操作索引 |

## 文章精读入口

| 页面 | 类型 | 状态 | 备注 |
|---|---|---|---|
| [2026-04-24-article.md](../articles/2026-04-24-article.md) | article wiki | legacy | 早期文章卡 |
| [2026-05-27-2010-english-i-text-4.md](../articles/2026-05-27-2010-english-i-text-4.md) | article wiki | active | 含题目、解析、错因和精读记录 |
| [2026-06-21-alan-gilbert-philharmonic.md](../articles/2026-06-21-alan-gilbert-philharmonic.md) | article wiki | active | 2011 English I Text 1 |
| [2026-06-22-2011-english-i-text-2.md](../articles/2026-06-22-2011-english-i-text-2.md) | article wiki | active | 2011 English I Text 2 |
| [2026-07-03-2011-english-i-text-3.md](../articles/2026-07-03-2011-english-i-text-3.md) | article wiki | active | 2011 English I Text 3；答案与解析 hidden_until_review |
| [2026-07-10-2011-english-i-text-4.md](../articles/2026-07-10-2011-english-i-text-4.md) | article wiki | active | 2011 English I Text 4；practice_safe；受保护源页不嵌入 active article |

## 批量学习资料入口

- [英语 PDF 学习资料总索引](reference/英语PDF学习资料总索引.md)：39 份用户资料的统一入口，汇总真题 / 解析、大纲词汇和作文资料三条学习线。
- [2010–2024 历年阅读总索引](reading/历年真题阅读总索引.md)：60 篇原文、题目与 A–D 选项；2012 年及以后标记待学习，practice-safe 页面不含答案。
- [2010–2024 受保护答案解析索引](../raw/protected/exam-reading-analysis/index.md)：按 60 篇 / 300 题组织的标准答案与出版方解析本地题号块；用户只陈述自己的选项时不解锁，只在明确要求核对答案、讲题或进入复盘后读取本地最小题号块，OCR 有歧义时才回外部 PDF。字段与门禁见 [历年阅读答案解析受保护预处理规则](../schema/protected_exam_analysis.md)。
- [历年阅读答案解析预处理验收](validation/2026-07-11-历年阅读答案解析预处理验收.md)：60 / 60 篇、300 / 300 题、来源哈希、视觉抽检与答案隔离的专项验收记录。
- [大纲词汇参考库](vocabulary/大纲词汇参考库.md)：大纲词汇 PDF 的可追溯 OCR / 词头参考层，用于以后造句选词，不等于长期生词库；当前数量以 manifest 和 selector 的实时校验为准。
- [作文资料总索引](writing/作文资料总索引.md)：大作文、小作文、主题词与历年题面候选入口。
- [作文造句可用白名单](writing/作文造句可用白名单.md)：未来生成例句只从本层的 approved / corrected 作文句型和词组中选材。
- [作文—大纲词—错词关系图谱](relationships/作文-大纲词-错词关系图谱.md)：四层地基派生图说明；词元重叠只作 `lexical_candidate`。
- [生词例句四层地基规则](../schema/reference_grounded_examples.md)：把旧“双源 / 三重命中”升级为用户措辞 / 错词证据 + 作文句型 + 作文词组 + 大纲词，`SP-*` 可选。

## 结构化库入口

- [master_bank.csv](../bank/master_bank.csv)：长期总库，字段固定为 `id,date,type,item,source_article,source_sentence,meaning,usage,writing_value,tags,review_note,appear_count,last_seen`。
- [mastered_items.csv](../bank/mastered_items.csv)：已掌握排除池，优先级高于旧词联想、明日复习和再次入库。
- [sentence_patterns.md](../bank/sentence_patterns.md)：句式结构卡片库，句式归并优先于新建。

## 旧词记忆曲线索引

- [old_words/memory_curve_summary.md](old_words/memory_curve_summary.md)：旧词联动造句的派生摘要，记录 D1/D3/D7/D15/D30/D60/D90+ 分布。
- [old_words/memory_curve_active_items.csv](old_words/memory_curve_active_items.csv)：去重后的活跃旧词索引，供不背单词导出优先查询。
- [old_words/memory_curve_rows.csv](old_words/memory_curve_rows.csv)：`master_bank.csv` 逐行预处理索引，供审计使用。

以上记忆曲线文件是派生缓存；若不是按当天正式库生成、或源文件状态已变化，必须从 `bank/master_bank.csv` 实时重算，并继续先排除 `mastered_items.csv`。

## 复习状态入口

- [tomorrow_review.md](../review/tomorrow_review.md)：临时复习清单，看完可清空，不作为长期 master source。
- [daily_review_log.md](../review/daily_review_log.md)：每日复盘记录。
- [weekly_review.md](../review/weekly_review.md)：周复盘记录，仅明确要求周复盘时维护。

## 视频语库入口

- [video/README.md](video/README.md)：视频语库维护规则。
- [video/_template.md](video/_template.md)：视频 wiki 页模板。

视频原始字幕、NotebookLM 导出和用户视频笔记先进入 `raw/video/` 或 `raw/notebooklm/`；生成后的语料页放在 `wiki/video/`。

## 操作中心

- [operation_center/英语智能体操作中心.md](operation_center/英语智能体操作中心.md)：英语系统内部操作中心。
- [operation_center/规则清单.md](operation_center/规则清单.md)：本系统规则来源和优先级。
- [operation_center/不可写正式数据清单.md](operation_center/不可写正式数据清单.md)：本目标期间不可写正式数据边界。
- [operation_center/长期表达库入口.md](operation_center/长期表达库入口.md)：`master_bank.csv` 的只读入口说明。
- [operation_center/英语学习看板.base](operation_center/英语学习看板.base)：Obsidian Bases 看板。

## LLM Wiki 工作流

- [workflows/ingest.md](workflows/ingest.md)：文章、网页、视频、NotebookLM 导入流程。
- [workflows/english-async-intake.md](workflows/english-async-intake.md)：逐句快速捕获、Luna 后台预处理与手动 Sol 夜间正式编纂。
- [workflows/query.md](workflows/query.md)：表达、句型、旧词联动、写作素材查询流程。
- [workflows/lint.md](workflows/lint.md)：CSV、raw/wiki、review、Tutor 体检流程。

## Tutor 与同步

- [tutor/长难句限定条件与转折逻辑接入方案.md](tutor/长难句限定条件与转折逻辑接入方案.md)：首批 Tutor 专题设计。
- [study_vaults/long-sentence-conditions-turns/input_candidates.md](study_vaults/long-sentence-conditions-turns/input_candidates.md)：StudyVault 输入候选。
- [sync/2026-06-28-英语LAMBIC同步包.md](sync/2026-06-28-英语LAMBIC同步包.md)：第二大脑高层同步包。

## 验收记录

- [validation/2026-07-11-英语PDF学习资料验收.md](validation/2026-07-11-英语PDF学习资料验收.md)：39 份 PDF、阅读 / 词汇 / 作文参考层与造句规则的最终验收。
- [validation/2026-07-11-不背单词四层地基验收.md](validation/2026-07-11-不背单词四层地基验收.md)：关系图、59 条作文地基视觉 overlay、只读 selector、四场景冒烟与 formal 零写入验收。
- [validation/2026-07-11-双源造句冒烟测试.md](validation/2026-07-11-双源造句冒烟测试.md)：旧“双源 / 三重命中”的历史基线测试；现行运行规则以四层地基、关系图和 selector 门禁为准。
- [validation/大纲词汇参考库验证报告.md](validation/大纲词汇参考库验证报告.md)：5746 条词汇候选、分区、人工复核与按需视觉核验门禁。
- [validation/三层架构验收记录.md](validation/三层架构验收记录.md)：raw/articles/wiki/schema/bank/review 边界验收。
- [validation/Obsidian_CLI验收记录.md](validation/Obsidian_CLI验收记录.md)：Obsidian CLI 和 Bases 查询验收。
- [lint_report.md](lint_report.md)：CSV lint 报告。

## Query 路由

- 查表达：先查本索引和未来 `wiki/expressions/`，再查 `bank/master_bank.csv`，再回到相关文章或视频页。
- 查句型：先查 `bank/sentence_patterns.md`，再查文章 / 视频页中的句型候选，最后查 CSV 遗留 `type=句型`。
- 查主题写作素材：先查未来 `wiki/topics/`，再聚合文章、视频、写作表达和 CSV 主题标签。
- 为生词造句：先排除 `mastered_items.csv`，优先保留用户当前措辞 / 明确错词证据，必须运行只读 `python3 scripts/select_bbdc_foundation.py ...` 读取四层地基关系图；地基包需含 approved/corrected 作文句型、approved/corrected 作文词组和 verified_* 大纲 occurrence，`SP-*` 可选。selector 不生成最终例句、不判断自然度、不回写 formal；最终造句另过 12–28 词及自然度 / 约束门禁。
- Query 默认只读。只有用户明确要求将当前答案沉淀到指定 wiki 页或正式库时，才路由到对应写入流程并验证。
