# Adapter 合同

ChatGPT、Codex、Claude Code、DeepSeek 与 generic 都只产生同一份 CandidateEvent JSON。Adapter 必须声明 `agent_id`、`producer_instance_id`、`source_namespace`、`coverage_scope` 与 `capabilities`，且只能读取当前获授权的上下文。无法写文件或 Git 时，输出候选 JSON 供本地 `worklog import` 导入。候选重试复用同一 `idempotency_key`。

当前能力状态均为 `unverified`。本地 generic 文件导入已实现；其他平台尚无真实账号或会话路径验证，不能标为 native-verified 或 bridge-verified。

