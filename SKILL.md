---
name: agent-worklog-skill
description: 将当前可访问的 Agent 工作记录为可追溯事件，并从私有 Git 数据仓生成日、周、月、季、年本地报告。仅在用户要求记录工作或生成工作报告时使用。
---

# Agent Worklog

仅记录当前有权访问且实际完成的工作。不要猜测其他平台的历史，也不要把讨论、计划或模型推断写成已完成。收集候选事实时保留稳定的 `idempotency_key`，每次重试复用；未知工时设为 `unknown` 和 `null`。详细字段见 [协议](references/protocol.md)。

先在本地把候选 JSON 交给 `worklog import`；它会脱敏、校验并返回落盘收据。只有收到 `persisted: true` 才能告诉用户已记录。同步状态为 `pending` 时明确说明尚未推送。各平台接入边界见 [Adapter 契约](adapters/README.md)。

报告由配置的单一 Aggregator 生成。`worklog aggregate daily`、`worklog weekly`、`worklog monthly`、`worklog quarterly` 和 `worklog yearly` 读取已落盘事实，不调用模型计算数值。缺失上报、修订冲突或未知时长须如实展示。静态页面只供本地阅读；公开发布和远端同步分别需要明确配置与权限。
