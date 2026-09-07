# Raw Sources Index

本目录是英语系统的原始资料层。这里保存原文、字幕、音频转写、网页清洗结果、NotebookLM 导出和用户原始摘录，只做登记和追溯，不做精翻、改写、总结或长期词条判断。

## 使用规则

- `raw/` 下文件默认只读；需要修正原始材料时，保留旧文件并新增更正版本，不覆盖历史来源。
- 每个 raw 来源必须有 `source_id`，后续 wiki 页、CSV 词条和复习记录都应能追溯到该 ID 或明确来源句。
- 原始材料缺时间戳、标题、平台或来源时，使用 `待补充`、`待确认`、`VISUAL_PENDING`，不要编造。
- NotebookLM、网页清洗、字幕提取结果仍算 raw；LLM 提炼后的内容必须写入 `wiki/`，不能直接覆盖 raw。

## Source ID 约定

- 文章：`RAW-ARTICLE-YYYYMMDD-NNN`
- 视频 / 字幕：`RAW-VIDEO-YYYYMMDD-NNN`
- 音频 / 播客：`RAW-AUDIO-YYYYMMDD-NNN`
- 网页：`RAW-WEB-YYYYMMDD-NNN`
- NotebookLM 导出：`RAW-NBLM-YYYYMMDD-NNN`
- 真题 / 解析 PDF 清单：`SRC-EXAM-NNN`
- 大纲词汇参考：`SRC-SYLLABUS-VOCABULARY-BOOKLET-*`、`SYL-VOCAB-*`
- 作文资料参考：`WRITING-SRC-*`、`WRITING-APPROVED-PATTERN-*`、`WRITING-APPROVED-VOCAB-*`

## 批量参考资料登记

| 参考层 | 范围 | 机器清单 / Raw 子索引 | Wiki 入口 | 边界 |
|---|---|---|---|---|
| 历年英语一阅读 | 2010–2024，15 年 × 4 篇、共 60 篇 / 300 题 | `raw/reference_sources/exam_pdf_manifest.json`; `raw/articles/exam-reading-corpus/index.md`; [受保护答案解析索引](protected/exam-reading-analysis/index.md) | `wiki/reading/历年真题阅读总索引.md` | practice-safe 层只含原文、题目、选项；答案与出版方解析按题号预处理到 `raw/protected/exam-reading-analysis/`。解锁后先读本地题号块，OCR 有歧义才回外部 PDF；规则见 [受保护预处理规则](../schema/protected_exam_analysis.md) |
| 大纲词汇 | 《大纲词汇背诵宝典 英语一》 | `raw/reference_sources/syllabus_vocabulary/` | `wiki/vocabulary/大纲词汇参考库.md` | OCR 参考层；不代表用户生词，不自动写 CSV |
| 作文资料 | 大 / 小作文模板、主题词、历年题面、答题卡共 6 份 PDF | `raw/writing_reference/manifest.json`; `raw/writing_reference/README.md` | `wiki/writing/作文资料总索引.md` | 自动抽取默认 unreviewed；只允许 approved / corrected 进入造句 |

## 登记表

| source_id | 类型 | 标题 | 日期 | raw_path | 来源说明 | wiki_status | wiki_path | 备注 |
|---|---|---|---|---|---|---|---|---|
| RAW-ARTICLE-20260703-001 | article | 2011 考研英语一 Text 3｜新媒介给营销传播带来的机遇和风险 | 2026-07-03 | `raw/articles/2026-07-03-2011-english-i-text-3/2011_text3_codex_ingest_pack/` | 用户提供 `2011_text3_codex_ingest_pack.zip`；包含 PDF 页截图、用户文章/题目截图、Markdown/JSON/JSONL 入库资料；原始 PDF 路径：`/Users/xiazhibin/Desktop/2011年考研英语一真题解析.pdf` | created | `articles/2026-07-03-2011-english-i-text-3.md` | 答案与解析保存为 hidden_until_review；不在初次练习阶段展示 |
| RAW-ARTICLE-20260710-001 | article | 2011 考研英语一 Text 4｜自主练习安全语境 | 2026-07-10 | `raw/articles/2026-07-10-2011-english-i-text-4/2011_text4_codex_ingest_pack/` | 用户提供整册 PDF、原文截图与第 36–40 题截图；练习安全转写仅含原文、题目和选项；PDF 第 34–43 页另存为受保护原始证据 | created | `articles/2026-07-10-2011-english-i-text-4.md` | practice_safe；受保护页不参加默认检索 |

2010–2024 年新增批量文章的 60 条逐篇登记统一维护在 `raw/articles/exam-reading-corpus/index.md`，避免在本总表复制 60 行并产生双重状态源。
