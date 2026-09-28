# ChatGPT 接入

状态：unverified。仅对当前会话或用户明确授权的可访问内容提取事实。若当前环境不能直接写本地文件，输出符合 `schemas/event.schema.json` 的候选 JSON，由本机导入器执行 `worklog import`。导出中不放完整对话、令牌或未经授权的链接。每条源事件的 `idempotency_key` 要稳定，后续重试保持不变。无法证明全天采集范围结束时，不提交 `close-day` 声明。

