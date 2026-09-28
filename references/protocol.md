# V1 协议

权威输入是 `raw/` 的不可变修订、`coverage/` 的声明、`policy/` 与 `overrides/` 的规则。`reports/`、`metrics/`、`site/` 和 `manifests/` 都是可重建派生结果。HTML 只位于 `site/`。

事件身份用 UUID `entry_id`；修订用 UUID `revision_id`；重试用稳定 `idempotency_key`；持续任务用 `task_id`；主题用 `topic_id`。缺失任务身份不能从相似标题推断。ID 字符仅允许小写字母、数字与短横线，Agent 与项目 ID 使用同样规则。别名只能通过版本化 policy 或 override 声明。一级分类取 `implementation`、`design`、`review`、`research`、`operations`、`learning`、`other`。

所有时间戳带偏移，统计日按配置的 IANA 时区。周期为左闭右开。`activity_window` 只是可观察窗口；`duration_type=unknown` 时秒数必须为 null。exact 有计时证据；estimated 有估算依据。无可靠跨日分段时，时长整体归 `work_date`；事件数始终只归 `work_date`。多技术标签时长允许重叠，不作总和为 100% 的占比。

修订图每个节点只引用同一事件的父修订。唯一叶节点为有效头；多个叶节点冲突，须显式 resolve；retract 叶不参与统计。相同来源命名空间和幂等键的等价载荷只算一个事件。`status=completed` 是完成事件，只有 `task_state_event` 可以声明任务完成。

Agent Daily 从当日有效 raw 生成，Global Daily 合并各 Agent Daily；Weekly 与 Monthly 都读取对应 Global Daily；Quarterly 读取三个月报，Yearly 读取四个季报。集合按身份并集，时间桶按唯一 bucket ID 去重，不能把下层 distinct 指标相加。跨月周仅提供相关叙述参考，不进入月报数值输入。所有结论必须保留来源 ID。

23:00 初版是 provisional；次日 00:15 后可 closed，但仅当所需 Agent 的有效声明齐备、无冲突、依赖齐备时才 complete。`no_activity` 与未上报分开。迟到事件使旧声明摘要失效。Git `.lock` 不作分布式锁；V1 只支持单一聚合通道。

错误码：0 成功；2 输入或 Schema；3 隐私或路径；4 不完整但有报告；5 同步待重试；6 冲突；7 聚合入口忙；8 内部错误。`--dry-run` 不写文件、不调用模型、不推送。输出诊断不得包含候选中的秘密。

