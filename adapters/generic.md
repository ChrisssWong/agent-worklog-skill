# Generic 文件桥接

输入是 UTF-8 JSON 文件，结构与 `schemas/event.schema.json` 一致。执行 `worklog --data <数据仓路径> import <候选文件>`；返回 `persisted: true` 才算本地记录成功。文件导入只负责当前候选，不证明源平台其他工作均已采集。使用 `close-day` 前须确认对应 `coverage_scope` 的采集确已结束。

