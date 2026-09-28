# 本地运行与恢复

## 安装

本机 Python 3.12。两个本地 Git 仓库分别是同级 `agent-worklog-skill` 与 `agent-worklog-data`。在 Skill 仓建立虚拟环境并安装 `pyproject.toml` 所列依赖；CLI 可用 `PYTHONPATH=src .venv/bin/python -m worklog` 运行。数据仓 `policy/worklog.yaml` 是共享统计政策；本机目录和凭据放在忽略的运行配置中。远端未配置时，`sync` 只作本地提交并返回 pending。

## 常用命令

下例均在 Skill 仓执行；`--data` 使用数据仓绝对路径。候选文件必须先脱敏并通过 Schema；CLI 仍会执行二次脱敏和校验。

```sh
PYTHONPATH=src .venv/bin/python -m worklog --data /Users/wk/Documents/AI/agent-worklog-data import /path/to/candidate.json
PYTHONPATH=src .venv/bin/python -m worklog --data /Users/wk/Documents/AI/agent-worklog-data close-day --agent codex --date 2026-09-28 --scope current-task
PYTHONPATH=src .venv/bin/python -m worklog --data /Users/wk/Documents/AI/agent-worklog-data aggregate daily 2026-09-28 --as-of 2026-09-29T00:15:00+08:00
PYTHONPATH=src .venv/bin/python -m worklog --data /Users/wk/Documents/AI/agent-worklog-data run-due --as-of 2026-09-29T00:15:00+08:00
PYTHONPATH=src .venv/bin/python -m worklog --data /Users/wk/Documents/AI/agent-worklog-data sync
```

`run-due` 从 policy 中最早启用日检查到显式时钟，按日报、周、月、季、年顺序补跑并发布 `site/current/index.html`。同一主机使用进程锁；外部调度器只需周期唤醒。缺声明时生成 incomplete 报告，修订或补录后重跑即可。`--dry-run` 仅列出拟写路径或到期节点，不写文件、不提交、不推送。

本机已安装 `launchd/com.chris.agent-worklog.plist` 到 `~/Library/LaunchAgents/`，每 900 秒唤醒一次。可用 `launchctl print gui/501/com.chris.agent-worklog` 查看上次退出码；日志位于数据仓忽略的 `.worklog-runtime/`。停止时用 `launchctl bootout gui/501/com.chris.agent-worklog`，再移除安装的 plist；仓库数据不受影响。

合成 ChatGPT 桥接样例见 `tests/fixtures/synthetic-chatgpt-bridge.json`，转换命令：

```sh
.venv/bin/python scripts/convert_chatgpt_bridge.py tests/fixtures/synthetic-chatgpt-bridge.json /private/tmp/chatgpt-candidate.json
```

该转换只认本项目的明确工作声明格式。真实 ChatGPT 导出需获得授权样例后重新适配，不能把合成测试当作平台兼容证明。

## 修订与恢复

修订候选保留原 `entry_id`、`partition_date`、`agent_id`，赋予新 `revision_id`，填写 `parent_revision_ids`、`revision_kind` 与 `revision_reason`，再使用同一导入命令。冲突分支需 resolve 引用全部叶节点。旧关闭声明在输入摘要变化后自动失效，须重新 close-day。

备份须同时保留远端仓库和未推送的本地提交；只保存远端可能丢离线事件。恢复时先核对 raw 文件摘要，执行 `validate all`，再 `run-due` 重建报告与站点。秘密若已进入 Git 历史，应先撤销凭据、隔离输出，再单独处理历史清理；本工具不自动改写历史。

## 当前限制

真实平台接入和七天试运行尚未执行。当前运行只支持一个本机聚合执行通道；Git 目录归属只由 CLI 检查，不是服务端权限隔离。模型分析默认关闭。站点仅供本地阅读，未配置远端与公开托管。
