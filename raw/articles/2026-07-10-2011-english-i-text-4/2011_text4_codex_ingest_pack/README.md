# 2011 考研英语一 Text 4｜Codex 入库包

source_id: RAW-ARTICLE-20260710-001
created_at: 2026-07-10
scope: 仅 2011 年考研英语一 Reading Comprehension Part A Text 4

## 文件结构

- dataset/text4_practice_safe.md：练习安全 Markdown，只含原文、题目和选项。
- dataset/text4_practice_safe.json：练习安全结构化主文件，不含作答判定、定位结论或试题讲解。
- dataset/text4_practice_safe.jsonl：按段落、题目和门禁切片的练习安全数据。
- practice_source/：用户提供的原文截图与题目截图，可在自主练习阶段使用。
- protected_source_pages/：PDF 第 34–43 页的受保护原始证据，仅在用户明确要求核对、讲解或复盘时按需读取。
- prompts/codex_preprocessing_instructions.md：后续会话读取门禁。
- manifest.json：来源、范围、校验值和文件角色。
- checksums.sha256：包内文件完整性校验。

## 安全原则

自主练习、逐词翻译、句子结构、段落理解、题干翻译和选项含义讨论，只读取 practice_safe 文章页、dataset/ 和 practice_source/。protected_source_pages/ 不参加默认检索，也不嵌入 active article。

本包没有生成含作答判定的 Markdown、JSON 或 JSONL 转写。出版方材料以页图形式完整保留；需要时按题号和页码最小读取。

