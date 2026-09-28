# Claude Code 接入

状态：unverified。若当前执行环境能输出文件，按统一 CandidateEvent 结构导出至本机桥接目录；由 `worklog import` 校验并落盘。只能引用用户授权的当前项目及会话。无文件能力时，提供标准 JSON 文本供人工导入。不得假定它能访问 Codex 或 ChatGPT 的私有历史。

