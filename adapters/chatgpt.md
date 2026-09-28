# ChatGPT 接入

状态：合成桥接格式已验证；真实 ChatGPT 导出结构与账号能力仍为 unverified。仅对当前会话或用户明确授权的可访问内容提取事实。`tests/fixtures/synthetic-chatgpt-bridge.json` 是人工构造的明确工作声明，`scripts/convert_chatgpt_bridge.py` 将其变成标准候选事件。该桥接格式不是 ChatGPT 官方导出格式；拿到真实脱敏导出后须按实际结构适配，不得从任意对话自动推断已完成工作。

若当前环境不能直接写本地文件，输出符合 `schemas/event.schema.json` 的候选 JSON，由本机导入器执行 `worklog import`。导出中不放完整对话、令牌或未经授权的链接。每条源事件的 `idempotency_key` 要稳定，后续重试保持不变。无法证明全天采集范围结束时，不提交 `close-day` 声明。
