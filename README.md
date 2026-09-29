# agent-worklog-skill

把不同 AI Agent 的工作记录整理成统一日志，再生成日报、周报和本地看板。

可以把两个项目理解为：**本项目是“记账工具”，`agent-worklog-data` 是“工作账本”**。工具保存规则和程序，账本保存你的真实工作记录。

## 它怎样工作

```text
Codex / ChatGPT 等整理本次工作
        ↓
生成 JSON → 脱敏、校验、去重 → 写入数据仓库
        ↓
一个指定的聚合执行者生成各 Agent 日报和综合日报
        ↓
周报、月报 → 季报 → 年报 → 本地 HTML 看板
```

周报和月报都从日报统计，避免跨月重复计算。报告保留来源；没有可靠依据的工时留空，不把聊天跨度当作工作时间。

**当前状态：** 已有本地 CLI、报告生成、看板和 ChatGPT 格式转换脚本；真实 Codex/ChatGPT 会话接入仍待验证，不代表已能自动读取所有聊天记录。已移除本机 `launchd` 调度入口及其运行日志、七天试运行审计脚本。

## 从工作记录到 `index.html`：流程与运行入口

**Codex 的输入是一项工作一份 CandidateEvent JSON，不是一篇已经排版的 Markdown 日报。** 多项工作分别导入，再由程序按日期聚合。字段以 [事件 Schema](schemas/event.schema.json) 和 [协议](references/protocol.md) 为准；主要包括 `entry_id`、`revision_id`、稳定的 `idempotency_key`、`agent_id`、`work_date`、`recorded_at`、`source_refs`、`project_id`、`category`、`title`、`summary`、`actions`、`status`、`outputs` 和 `time`。没有可靠工时依据时，`duration_type`、`duration_seconds` 与 `evidence_ref` 均填 `null`；不要从聊天跨度推算。Codex 应先核对当前可访问的实际工作与产物，再生成完整 JSON。

下面的命令都在 `agent-worklog-skill` 根目录运行，`--data` 指向独立的数据仓；`<候选文件.json>` 是 Codex 保存的完整事件 JSON 路径。

| 步骤 | 运行命令或入口 | 作用与主要结果 |
|---|---|---|
| 1. 导入每项工作 | `.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data import <候选文件.json>` | 校验、脱敏、检查幂等键；成功时返回 `persisted: true`，写入 `raw/YYYY/MM/DD/<agent_id>/<entry_id>/<revision_id>.json`。一份候选文件对应一条事件。 |
| 2. 核对原始数据 | `.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data validate all` | 检查数据和修订冲突；继续聚合前确认 `valid: true` 且 `conflicts` 为空。 |
| 3. 声明上报范围（有条件） | `.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data close-day --agent codex --date 2026-09-28 --scope current-task` | 仅在确认该日期、该范围的工作都已导入后，向 `coverage/` 写入声明。`current-task` 只覆盖当前任务，不能使全天日报变为完整；只有确认全天均已上报，才使用 `--scope full-day`。 |
| 4. 生成到期报告和首页 | `.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data run-due --as-of <实际当前带时区时间>` | 根据 `policy/worklog.yaml` 的时间表，从 `raw/` 和 `coverage/` 聚合报告，生成 `reports/`、`manifests/` 和 `site/`，并发布 `site/current/index.html`。例如 9 月 28 日的文字日报位于 `reports/2026/daily/09/28/summary.md`。 |
| 5. 查看完整性 | `.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data status --date 2026-09-28` | 查看当天是否缺少上报声明或其他依赖；生成了首页不等于日报已经完整。 |
| 6. 同步远端（可选） | `.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data sync` | 检查允许提交的文件，提交并尝试推送 Git 远端；只有 `sync: "pushed"` 才代表远端同步成功。 |

`run-due` 只处理按配置**已经到期**的日期：当前配置在 23:00 生成当日初版，次日 00:15 后补跑日终版。需要提前手动查看某日结果时，可依次运行 `aggregate daily <日期> --as-of <实际当前带时区时间>` 和 `dashboard --as-of <同一时间>`；后者发布 `site/current/index.html`。文字日报和看板首页分别由已导入的事件生成，首页不是把 `summary.md` 直接转成 HTML。时间参数应使用真实当前时间。补录或修订后，重新确认覆盖范围并重跑报告；不要直接编辑生成的 HTML。

读者看到的 Markdown 和 HTML 只展示工作内容及通俗状态，不展示工时、事件 ID、修订 ID 或上报 Agent 清单。内部 `raw/`、报告 JSON 和 manifest 仍保留身份、来源、时长及完整性数据，用于纠错、去重和审计。进行中的日报显示“当日记录仍在更新”；日终缺有效全天声明时显示“记录尚未确认完整”。

上述命令统一由 `src/worklog/cli.py` 接收，通常通过 `.venv/bin/worklog` 或 `PYTHONPATH=src .venv/bin/python -m worklog` 运行。内部文件及独立脚本的分工如下：

| 文件 | 作用 | 是否需要单独运行 |
|---|---|---|
| `src/worklog/core.py` | 校验事件、脱敏、去重、写入 `raw/`，以及写入 `coverage/`。 | 不需要，由 CLI 调用。 |
| `src/worklog/orchestrate.py` | 判断哪些报告到期、串行聚合并调用看板发布。 | 不需要，由 `run-due` 调用。 |
| `src/worklog/reports.py` | 从有效事件生成日报及周期报告的 JSON、Markdown 和报告页。 | 不需要，由聚合命令调用。 |
| `src/worklog/dashboard.py`、`src/worklog/publish.py` | 生成 `site/index.html` 等看板页，并把完整站点快照发布为 `site/current/index.html`。 | 不需要，由 `run-due` 或 `dashboard` 调用。 |
| `src/worklog/git_sync.py` | 限定可提交路径，执行数据仓的 Git 提交和推送。 | 不需要，由 `sync` 调用。 |
| `scripts/convert_chatgpt_bridge.py` | 将约定格式的 ChatGPT 桥接 JSON 转为 CandidateEvent JSON；转换后仍须执行 `worklog import`。 | 仅导入 ChatGPT 桥接记录时运行。 |

## 本地准备

需要 Python 3.12+ 和 Git，建议两个项目放在同一父目录。以下命令在本项目根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/worklog --help
```

数据仓库的 `policy/worklog.yaml` 决定时区、Agent 名册和报告时间。CLI 目前通过 `--data` 指定数据目录；`worklog.local.example.yaml` 是配置参考，不会代替这个参数。

## 切换 HTML 页面风格

首页、成长记录、项目/技术/Agent 等维度页，以及日、周、月、季、年报告页共用一项站点配置。在数据仓库的 `policy/worklog.yaml` 中设置：

```yaml
site:
  style: ledger
```

`ledger` 是默认的 **B · 纸本台账**：暖纸色、细分隔线和适合长文阅读的排版。改为 `blue` 可切换到 **C · 轻蓝工作台**：冷白底、浅蓝灰区块和更偏工具界面的排版。仅支持这两个值；旧配置未写 `site` 时也按 `ledger` 生成。风格由生成时的配置决定，页面内没有切换控件。

改完配置后，使用真实当前时间重新生成页面。例如先重建已有日报，再生成看板和最新站点快照：

```sh
.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data aggregate daily 2026-09-28 --as-of <实际当前带时区时间>
.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data aggregate daily 2026-09-29 --as-of <实际当前带时区时间>
.venv/bin/worklog --data /Users/wk/Documents/AI/agent-worklog-data dashboard --as-of <同一时间>
```

请把示例日期替换为需要更新的报告日期；正常到期的报告也会在后续 `run-due` 中按新风格生成。外观设置不改变原始记录、统计事实或 Markdown 内容。生成的 HTML 将样式内嵌，可离线打开；这里不会自动执行 Git 同步或推送。
若日报仍标记为 `incomplete`，`aggregate daily` 会返回状态码 4，但仍会写出该日报页面；请以命令输出中的完整性状态为准。

下面的 `/path/to/...` 都要替换成你的实际路径。

## Codex 怎么接入

### 1. 在 Codex 中启用 Skill

首次使用时，将本仓库作为个人 Skill 链接到 Codex 的技能目录（目标已存在时先检查，不要覆盖）：

```sh
mkdir -p ~/.agents/skills
ln -s /Users/wk/Documents/AI/agent-worklog-skill ~/.agents/skills/agent-worklog-skill
```

之后在 Codex 对话中输入 `$agent-worklog-skill` 即可显式调用。Codex 支持从个人 `.agents/skills` 目录发现符号链接的 Skill；若未出现，重启 Codex。参见 [官方 Skills 说明](https://learn.chatgpt.com/docs/build-skills)。本仓库的 CLI 仍需按上文“本地准备”安装，且 Codex 需要能读工具仓、写数据仓。

### 2. 生成当前工作的日报

在**刚完成工作的 Codex 对话**中发送：

```text
使用 $agent-worklog-skill，把本次对话中实际完成的工作记录到
/Users/wk/Documents/AI/agent-worklog-data，agent_id=codex。
每项工作生成一条符合事件 Schema 的 JSON，并逐条执行 worklog import；
没有可靠工时依据时将时间字段留空为 null，重试复用幂等键。
确认每条返回 persisted=true。
然后用实际当前带时区时间执行 aggregate daily <今日日期>，
再执行 dashboard，生成今天的日报和 site/current/index.html，
返回日报路径及完整性状态。本次不执行 full-day 声明，也不 Git push。
```

白天生成的日报可能显示“当日记录仍在更新”；它只覆盖已经导入的工作。其他对话中的工作须在各自会话记录，不能由当前对话猜测。

### 3. 让 Codex 每晚推送今日工作日报

先确保数据仓的 `origin/main` 是预期的**私有远端**、Git 认证可用，并处理数据仓中与工作日志无关的未提交变更。随后在 Codex 对话中发送下面的创建请求；它会创建或更新**独立的本地定时任务**，阅读这段文字本身不会创建任务：

```text
请创建或更新一个名为“每日工作日报推送”的 Codex 定时任务：
每天 Asia/Shanghai 23:05 运行，项目为
/Users/wk/Documents/AI/agent-worklog-skill，执行环境选本地 Local。
如已有同用途任务，请更新而不要重复创建。任务每次使用以下提示词：

使用 $agent-worklog-skill。工具目录为
/Users/wk/Documents/AI/agent-worklog-skill，数据仓为
/Users/wk/Documents/AI/agent-worklog-data。
读取实际当前北京时间，仅汇总数据仓已经导入的今日记录；
不扫描其他对话，不虚构工作，不自动执行 close-day。
在工具目录运行 PYTHONPATH=src .venv/bin/python -m worklog，
每条命令均带 --data /Users/wk/Documents/AI/agent-worklog-data：
先执行 validate all，确认 valid=true 且 conflicts 为空；
再执行 run-due --as-of <实际当前带时区时间>，
并执行 status --date <今日日期> 检查日报状态。
检查数据仓分支、私有 origin/main 和 Git 改动；先运行 --dry-run sync。
只有拟提交路径都属于工作日志流程时，才运行 sync --remote origin --branch main。
允许推送明确标注为 incomplete 的初版；只有 sync=pushed 才报告推送成功。
最终用中文返回今日已记录工作、日报完整性、Git 同步状态和
site/current/index.html 路径。
```

23:05 生成的是当日初版，定时任务不会自动读遍白天所有 Codex 会话。涉及本机文件的定时任务需要电脑开机、应用运行且文件可访问；参见 [官方定时任务说明](https://learn.chatgpt.com/docs/automations)。排障与恢复见 [运行手册](docs/operations.md)。

## ChatGPT 怎么接入

先使用**结构化导出 → 本地导入**的方式，无需假设 ChatGPT 能访问你的电脑或 Git。

1. 将 [桥接样例](tests/fixtures/synthetic-chatgpt-bridge.json) 的内容提供给 ChatGPT。
2. 让它按相同结构整理当前会话中的实际工作，保存为 `chatgpt-work.json`。
3. 在本机转换并导入：

```sh
.venv/bin/python scripts/convert_chatgpt_bridge.py /path/to/chatgpt-work.json /path/to/candidate.json
.venv/bin/worklog --data /path/to/agent-worklog-data import /path/to/candidate.json
```

给 ChatGPT 的提示词：

> 请按我提供的桥接 JSON 样例整理当前会话中的实际工作，将 synthetic 改为 false。只记录有依据的事实，不附完整聊天或秘密。没有可靠工时依据时，省略 duration_type、duration_seconds、duration_basis；没有整个任务已完成的证据时 task_state=null。同一条记录重试时保留 conversation_id 和 source_item_id。只输出 JSON。

一份桥接文件对应一条工作事件。样例中的日期、项目和 ID 都要换成实际值；会话 ID 可用自定且稳定的本地标识。**这是本项目的桥接格式，不是 ChatGPT 官方聊天导出格式**，不能直接把账号导出的整个历史文件交给转换脚本。文件保存前先去除敏感信息。

## 每天怎么用

先导入各 Agent 的候选 JSON；当天声明范围内的工作都已上报后，再关闭该 Agent 的当日记录：

```sh
.venv/bin/worklog --data /path/to/agent-worklog-data close-day --agent codex --date 2026-09-28 --scope current-task
```

`current-task` 只表示当前任务，不能当作全天覆盖，也不会满足日报的全天完整性要求。只有核实全天范围已上报，才使用 `--scope full-day`。ChatGPT 也只能在确认其声明范围已上报时使用 `--agent chatgpt` 关闭。

随后由单一聚合执行者生成到期报告和看板：

```sh
.venv/bin/worklog --data /path/to/agent-worklog-data run-due --as-of 2026-09-29T00:15:00+08:00
```

日期和 `--as-of` 请换成实际日期及当前带时区时间，不要为提前生成完整报告而填写未来时间。打开数据仓库的 `site/current/index.html` 阅读最新发布结果。

需要同步到已配置的私有远端时，单独执行 `sync`；它会提交允许范围内的变更并尝试推送。没有远端时返回 pending，不代表已备份到云端。

## 常用入口

| 想做什么 | 入口 |
|---|---|
| 了解日志字段 | [协议](references/protocol.md)、[事件 Schema](schemas/event.schema.json) |
| 检查数据 | `.venv/bin/worklog --data /path/to/agent-worklog-data validate all` |
| 查看某天状态 | `.venv/bin/worklog --data /path/to/agent-worklog-data status --date 2026-09-28` |
| 预览补跑、不写入 | `.venv/bin/worklog --data /path/to/agent-worklog-data --dry-run run-due --as-of 2026-09-29T00:15:00+08:00` |
| 同步 Git | `.venv/bin/worklog --data /path/to/agent-worklog-data sync` |
| 修订、调度和恢复 | [运行手册](docs/operations.md) |
| 查看接入限制 | [Adapter 说明](adapters/README.md) |

补录或修订后，重新提交受影响日期的关闭声明，再运行 `run-due`。不要直接改生成的报告或 HTML。定时唤醒由外部调度器负责，安装 Skill 本身不会自动开启定时任务。
