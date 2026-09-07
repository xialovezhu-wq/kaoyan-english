# 输入候选：长难句限定条件与转折逻辑

更新时间：2026-06-28

## 候选结构

| candidate_id | 来源 | 结构点 | 训练价值 | 状态 |
|---|---|---|---|---|
| ENG-TUTOR-001 | `bank/sentence_patterns.md` SP-002 | `not A but B` / `B, not A` | 训练对比否定和真正判断点 | ready |
| ENG-TUTOR-002 | `bank/sentence_patterns.md` SP-004 | `N + S + V` 省略引导词定从 | 训练限定对象识别 | ready |
| ENG-TUTOR-003 | `bank/sentence_patterns.md` SP-009 | 定从内部并列谓语 + `for fear of` + `yet` | 训练原因短语和转折谓语并存 | ready |
| ENG-TUTOR-004 | `articles/2026-05-27-2010-english-i-text-4.md` | `unless` 条件从句 | 训练必要条件和主句结果 | ready |
| ENG-TUTOR-005 | `articles/2026-06-22-2011-english-i-text-2.md` | `as` 原因 / 时间状语 | 训练一词多逻辑功能 | ready |
| ENG-TUTOR-006 | `articles/2026-06-22-2011-english-i-text-2.md` | `where` 抽象情境定从 | 训练非地点 where 的限定功能 | ready |
| ENG-TUTOR-007 | `articles/2026-06-21-alan-gilbert-philharmonic.md` | `not only ... but also ...` | 训练并列递进范围 | candidate |

## 可生成的概念笔记

1. 条件从句：`if / unless / as long as`
2. 转折连接：`but / yet / however`
3. 让步与反向预期：`although / though / even if`
4. 限定性定语从句：显性关系词与省略关系词
5. 抽象地点 where：`case / situation / point / search + where`
6. 对比否定：`not A but B`

## 题目设计样例

| 类型 | 问法 | 不展示的内容 |
|---|---|---|
| 主干识别 | 这句话先跳过哪个修饰成分才能抓住主干？ | 不直接给完整答案 |
| 逻辑判断 | `as` 在这里是时间、原因还是比较？ | 不提示选项特征 |
| 修饰对象 | 省略引导词的定从修饰哪个名词？ | 不提前标出关系词 |
| 错因回忆 | 这类句子下次第一步应该做什么？ | 不复述完整解析 |

## 同步边界

- 可同步：薄弱结构、重复误判、跨系统关系候选。
- 不同步：完整文章原文、标准选择题答案、普通生词批量清单。
- 不自动写：`bank/master_bank.csv`、`review/weekly_review.md`。

