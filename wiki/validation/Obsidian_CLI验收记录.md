# Obsidian CLI 验收记录

验收日期：2026-06-28

## Vault 可见性

CLI 已识别以下 vault：

- `kaoyan-408`
- `kaoyan-english`
- `kaoyan-math`
- `睡眠状态记录`

当前活动 vault：

- 名称：`kaoyan-english`
- 路径：`/Users/xiazhibin/Documents/kaoyan-english`

## 文件计数样本

- `wiki/`：15 个文件
- `articles/`：4 个文件
- `bank/`：3 个文件

## 关键词搜索验收

| 关键词 | 结果 |
|---|---|
| `LAMBIC` | 命中 `wiki/operation_center/英语智能体操作中心.md`、规则清单、不可写清单 |
| `operation_center` | 命中本地操作中心文件 |
| `articles` | 命中 `schema/schema.md`、Tutor 输入候选、工作流文件 |
| `video` | 命中视频导入模板、schema、工作流和操作中心 |
| `bank` | 命中 schema、Tutor 输入候选、StudyVault 说明 |
| `review` | 命中 schema、Tutor 输入候选、lint 工作流 |
| `Tutor` | 命中 Tutor 方案、StudyVault 输入候选、lint/query 工作流 |

## 读取入口验收

已通过 Obsidian CLI 读取：

1. `wiki/index.md`
2. `schema/schema.md`
3. `wiki/operation_center/英语智能体操作中心.md`
4. `wiki/operation_center/英语学习看板.base`
5. `wiki/tutor/长难句限定条件与转折逻辑接入方案.md`

## Bases 看板验收

看板文件：`wiki/operation_center/英语学习看板.base`

YAML 校验：

- `ruby -e 'require "yaml"; YAML.load_file(...)'` 通过。

Obsidian CLI 验收：

- `obsidian bases` 可看到 `wiki/operation_center/英语学习看板.base`。
- `obsidian open path="wiki/operation_center/英语学习看板.base"` 可打开。
- `obsidian base:views` 可列出视图：
  - 精读文章
  - 视频语库
  - 长期库
  - 复习记录
  - Raw 来源
  - 操作中心
  - Tutor
  - 同步包
  - 验收与Lint
- `base:query` 已成功查询：
  - 精读文章
  - 视频语库
  - 长期库
  - 复习记录
  - 操作中心
  - Tutor

## 注意

`base:views` 需要先打开 base 文件作为当前 active base；直接带 path 调用时曾报 “Active file is not a base file”。这属于 CLI 使用方式限制，不是看板不可用。

