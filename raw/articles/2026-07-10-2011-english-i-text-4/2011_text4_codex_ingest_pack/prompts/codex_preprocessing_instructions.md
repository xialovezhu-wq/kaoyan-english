# Codex 预处理指令｜2011 英语一 Text 4

## 任务范围

只处理 2011 年考研英语一 Reading Comprehension Part A Text 4，不得混入 Text 3 或 Part B。

## 默认读取范围

自主练习与后续逐句学习默认只读取：

1. articles/2026-07-10-2011-english-i-text-4.md
2. dataset/text4_practice_safe.md
3. dataset/text4_practice_safe.json
4. dataset/text4_practice_safe.jsonl
5. practice_source/ 中的两张用户截图

## 禁止默认读取

protected_source_pages/ 仅作为受保护原始证据。下列请求不构成解锁：

- 单词或词组是什么意思
- 某句如何翻译或拆结构
- 某段在说什么
- 题干或某个选项如何翻译
- 某个代词指什么
- 用户陈述自己的选择但没有要求核对

只有用户明确要求核对某题、判断某个选择、讲解某题或进入整篇复盘，才按题号读取最小必要源页。

## 输出约束

- 不主动给出选项正误、作答结论或可反推结论的提示。
- 不在 active article 中嵌入受保护页、出版方翻译或试题讲解。
- 不以折叠块、注释、frontmatter 或隐藏字段软隐藏受限内容。
- 每次局部问答只处理用户当前指定的句子、词或选项。

