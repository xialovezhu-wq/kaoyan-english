# 2011 考研英语一 Text 3｜Codex 入库包

本包仅包含 2011 年考研英语一第三篇阅读 Text 3 的材料：文章原文、题目、解析、概念表、Codex 预处理指令和源页视觉资料。

## 文件结构

- `dataset/text3_ingest.json`：结构化入库主文件，含文章、题目、解析和隐藏答案字段。
- `dataset/text3_ingest.jsonl`：逐段/逐题/逐概念切片格式，便于向量化或检索预处理。
- `dataset/text3_full_ingest.md`：Markdown 版完整资料，答案与解析放在折叠块内，供复盘阶段调用。
- `prompts/codex_preprocessing_instructions.md`：给 Codex 的处理规则，强调复盘前不泄露答案和解析。
- `source_images/`：用户上传的原始文章与题目截图。
- `source_pages/`：从 PDF 渲染/裁剪的 Text 3 相关源页，仅供 Codex 校验，不用于直接展示。

## 重要规则

本包包含答案与详细解析。导入 Codex 后，请把答案、解析、错项分析标记为 `hidden_until_review`。学习者未明确要求复盘前，不应展示这些内容。

创建时间：2026-07-02T08:22:14.942551+00:00
