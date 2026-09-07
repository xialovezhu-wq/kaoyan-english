# 旧词记忆曲线预处理索引

generated_date: 2026-07-27
source: `bank/master_bank.csv`; `bank/mastered_items.csv`
status: derived-index; rebuildable; not formal bank data

## 规则

- 先排除 `bank/mastered_items.csv` 已掌握项。
- 使用 `last_seen` 计算距离今天的天数；缺失时回退 `date`。
- 命中窗口：D1, D3, D7, D15, D30, D60, D90+。
- 最近今天/昨天刚见过的词不优先用于旧词联动。
- 无自然命中时，使用 `oldest-fallback`：选择最久未复现且能自然造句的活跃旧词。
- 本索引不更新 `appear_count`、`last_seen`、`master_bank.csv` 或复习文件。

## 输出文件

- `wiki/old_words/memory_curve_active_items.csv`：去重后的活跃旧词索引，供造句优先使用。
- `wiki/old_words/memory_curve_rows.csv`：master_bank 逐行预处理索引，供审计使用。

## 总览

- master_bank 数据行：732
- mastered_items 数据行：0
- 活跃逐行记录：732
- 去重后活跃 item：729
- 今天命中记忆曲线窗口的活跃 item：255
- CSV 字段错位行：0
- mastered_items 字段错位行：0

## 类型分布

| type | count |
|---|---:|
| 写作表达 | 1 |
| 动词 | 1 |
| 单词 | 284 |
| 句型 | 47 |
| 熟词僻义 | 34 |
| 词组 | 365 |

## 活跃 item 记忆曲线分布

| bucket | count |
|---|---:|
| D1 | 25 |
| between-D15-D30 | 149 |
| between-D30-D60 | 325 |
| D90+ | 230 |

## 当前命中窗口样例

| item | bucket | days | type | meaning |
|---|---|---:|---|---|
| a crisis of confidence | D90+ | 94 | 词组 | 信心危机 |
| a cursory search for causes | D90+ | 94 | 词组 | 对原因的粗略查找；粗略寻找原因 |
| a function of | D90+ | 94 | 词组 | 是……的结果；取决于……；是……的函数 |
| a given | D90+ | 94 | 词组 | 理所当然的事；不言自明的条件 |
| a policy on sth | D90+ | 94 | 词组 | 关于……的政策 |
| a tiny minority of | D90+ | 94 | 词组 | 极少数的…… |
| account for sth | D90+ | 94 | 词组 | 占据比例；解释原因 |
| acknowledge | D90+ | 94 | 单词 | 承认；认可某事实存在 |
| acquaintances | D90+ | 94 | 单词 | 熟人；认识的人 |
| administer tests | D90+ | 94 | 词组 | 组织考试；实施考试 |
| admissions test | D90+ | 94 | 词组 | 入学考试 |
| advocacy | D90+ | 94 | 单词 | 倡导；主张 |
| allow for | D90+ | 94 | 词组 | 使成为可能；容许 |
| an approach to sth | D90+ | 94 | 词组 | 做某事的方法；处理路径 |
| anecdotal | D90+ | 94 | 单词 | 传闻的；轶事性的；基于个别事例的 |
| anecdotal evidence | D90+ | 94 | 词组 | 传闻证据；个案证据；轶事性证据 |
| argument | D90+ | 94 | 单词 | 论点；观点；主张 |
| arise | D90+ | 94 | 单词 | 产生；出现；源于 |
| arm sb with sth | D90+ | 94 | 词组 | 用……武装自己；配备 |
| as | D90+ | 94 | 单词 | 随着；当……的时候 |
| as recently as | D90+ | 94 | 词组 | 直到最近；就在……时 |
| at a loss | D90+ | 94 | 词组 | 不知所措；困惑 |
| at the heart of | D90+ | 94 | 词组 | 处于核心 |
| attribute | D90+ | 94 | 单词 | 特质；属性 |
| attribute A to B | D90+ | 94 | 词组 | 把 A 归因于 B |
| back | D90+ | 94 | 单词 | 支持；证实 |
| be aware of | D90+ | 94 | 词组 | 意识到；认识到 |
| be crucial to sth | D90+ | 94 | 词组 | 对……关键 |
| be desperate for sth | D90+ | 94 | 词组 | 迫切需要；极度渴望 |
| be driven in large part by | D90+ | 94 | 词组 | 很大程度上由……推动；主要受……驱动 |

## oldest-fallback 样例

| rank | item | days | type | meaning |
|---:|---|---:|---|---|
| 231 | in public | 50 | 词组 | 在公开场合 |
| 232 | behind the scenes | 50 | 词组 | 幕后；私下里 |
| 233 | take aim at | 50 | 词组 | 把矛头对准；针对；批评 |
| 234 | accounting | 50 | 单词 | 会计的；会计 |
| 235 | standard-setters | 50 | 词组 | 标准制定者 |
| 236 | their rules | 50 | 词组 | 他们的规则；此处指会计准则制定者的规则 |
| 237 | moan | 50 | 单词 | 抱怨 |
| 238 | force sb to do sth | 50 | 词组 | 迫使某人做某事 |
| 239 | report losses | 50 | 词组 | 报告亏损；确认损失 |
| 240 | enormous | 50 | 单词 | 巨大的；庞大的 |
| 241 | not fair | 50 | 词组 | 不公平 |
| 242 | assets | 50 | 单词 | 资产；财产 |
| 243 | value some assets | 50 | 词组 | 评估一些资产；给一些资产估值 |
| 244 | third party | 50 | 词组 | 第三方 |
| 245 | the price a third party would pay | 50 | 句型 | 第三方愿意支付的价格 |
| 246 | fetch | 50 | 单词 | 售得；卖得某价 |
| 247 | at the price A would pay not the price B would like | 50 | 句型 | 按照 A 愿付价格，而不是按照 B 希望卖出的价格 |
| 248 | lobbying | 50 | 单词 | 游说；游说活动 |
| 249 | unknowable | 50 | 单词 | 难以获知的；不可知的 |
| 250 | independence | 50 | 单词 | 独立性; 自主性 |

## lint 提示

| flag | count |
|---|---:|
| invalid_type | 1 |
