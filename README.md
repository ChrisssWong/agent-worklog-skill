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

周报和月报都从日报统计，避免跨月重复计算。报告保留来源；不知道的时长记为 unknown，不把聊天跨度当作工作时间。

**当前状态：** 已有本地 CLI、报告生成、看板和 ChatGPT 格式转换脚本；真实 Codex/ChatGPT 会话接入及连续七天试运行仍待验证，不代表已能自动读取所有聊天记录。

## 本地准备

需要 Python 3.12+ 和 Git，建议两个项目放在同一父目录。以下命令在本项目根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/worklog --help
```

数据仓库的 `policy/worklog.yaml` 决定时区、Agent 名册和报告时间。CLI 目前通过 `--data` 指定数据目录；`worklog.local.example.yaml` 是配置参考，不会代替这个参数。

下面的 `/path/to/...` 都要替换成你的实际路径。

## Codex 怎么接入

最简单的方式是让 Codex 读取本项目的 `SKILL.md` 和 `adapters/codex.md`，并告诉它数据仓库位置。可以直接复制这段话：

> 请读取 `/path/to/agent-worklog-skill/SKILL.md` 和 Codex Adapter。将当前任务中实际做过的工作整理为候选 JSON，agent_id 使用 codex，数据目录为 `/path/to/agent-worklog-data`。使用本项目 CLI 导入，复用稳定的幂等键，返回落盘收据。不确定的时长填 unknown，不读取其他会话，不自动推送。

如果希望 Codex 自动发现这个 Skill，可将本项目链接到个人技能目录（仅首次执行，目标已存在时先检查）：

```sh
mkdir -p ~/.agents/skills
ln -s /path/to/agent-worklog-skill ~/.agents/skills/agent-worklog-skill
```

之后可显式提及 `$agent-worklog-skill`。这是技能加载方式；实际文件访问仍受当前环境权限限制。参见 [OpenAI 官方技能说明](https://learn.chatgpt.com/docs/build-skills)。

接入成功的标志是导入结果包含 `persisted: true`，而不只是 Codex 回复“已经记录”。

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

> 请按我提供的桥接 JSON 样例整理当前会话中的实际工作，保留字段结构，将 synthetic 改为 false。只记录有依据的事实，不附完整聊天或秘密。不知道的时长使用 duration_type=unknown、duration_seconds=null；没有整个任务已完成的证据时 task_state=null。同一条记录重试时保留 conversation_id 和 source_item_id。只输出 JSON。

一份桥接文件对应一条工作事件。样例中的日期、项目和 ID 都要换成实际值；会话 ID 可用自定且稳定的本地标识。**这是本项目的桥接格式，不是 ChatGPT 官方聊天导出格式**，不能直接把账号导出的整个历史文件交给转换脚本。文件保存前先去除敏感信息。

## 每天怎么用

先导入各 Agent 的候选 JSON；当天声明范围内的工作都已上报后，再关闭该 Agent 的当日记录：

```sh
.venv/bin/worklog --data /path/to/agent-worklog-data close-day --agent codex --date 2026-09-28 --scope current-task
```

`current-task` 只表示当前任务，不能当作整个账号的全天覆盖。ChatGPT 也只能在确认其声明范围已上报时使用 `--agent chatgpt` 关闭。

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
