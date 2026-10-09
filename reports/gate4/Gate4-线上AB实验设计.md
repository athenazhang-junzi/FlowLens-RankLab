# FlowLens Gate 4｜线上 A/B 实验设计

## 1. 当前准入状态

- 对应离线运行：`gate4-c2f35eb1de6d`。
- 当前可进入线上实验的策略：**无；需先完成离线迭代与重测**。
- 本文是预注册模板，不代表真实平台已经启动实验；MDE、样本量和时长必须接入真实线上基线后计算。

## 2. 假设与实验单元

假设模板：对目标 Feed 中满足触发条件的用户应用冻结策略版本，可能提高用户级有效消费，同时不恶化负反馈、重复曝光和内容生态覆盖。

- 随机化单元：`user_id`；使用稳定哈希固定分组。
- 分流：Control 使用 S0；Treatment 只使用一个通过离线准入的冻结策略，禁止一次实验混入多项核心变化。
- 触发：用户进入目标 Feed，且请求时至少存在 2 个 eligible 候选。
- 排除：内部／测试账号、数据质量失败、策略版本不一致、事件时间异常和未实际触发排序的用户。
- 污染控制：同一用户在实验期间不可跨组；跨设备身份无法合并时需单独标记风险。

## 3. 事件合同

| 阶段 | 必需字段 | 目的 |
|---|---|---|
| eligible | user、request、candidate、scene、timestamp | 确认进入实验资格与候选口径 |
| assigned | experiment、group、unit、assignment_time | 检查分流和 SRM |
| ranked | strategy_version、item、rank、score、rule_hits | 解释排序与版本一致性 |
| exposed | request、item、position、exposure_time | 区分分组与真实曝光 |
| clicked | request、item、click_time | 计算 CTR 与点击后转化 |
| content_start | request、item、start_time | 排除误触 |
| long_view | request、item、duration、threshold_version | 计算有效消费 |
| negative_feedback | request、item、feedback_type、time | 体验护栏 |

事件以 `request_id + item_id + event_type + event_time` 做幂等检查；分组、触发和曝光必须分别记录。

## 4. 指标与决策

- 主指标：用户级有效消费率 ECR；分子为长播曝光，分母为有效曝光，先按用户聚合再比较组间均值。
- 驱动指标：Top-N ECR、CTR、点击后长播率和播放时长。
- 护栏：负反馈率、同内容／同作者短窗重复率、内容／作者覆盖、作者 HHI、新内容曝光份额。
- 收入：`N/A`，除非接入真实、可审计的收入事件和归因规则。
- 统计：预注册双侧显著性水平、power、MDE、样本量和最长实验时长；不允许因中途显著提前停止。

## 5. 阻断级健康检查

1. SRM：实际分流与计划比例不符时停止解释效果。
2. 触发正确性：Treatment 用户必须真实命中策略版本；未触发用户不混入 triggered analysis。
3. 跨组污染：同一随机化单元进入多个组时阻断。
4. 重复事件：幂等键重复和重放率超阈值时阻断。
5. 时间完整性：实验窗、归因窗、迟到事件规则必须一致。
6. A/A：上线前验证误报率、区间覆盖和埋点一致性。
7. 样本进度：未达到预注册样本量只能继续观察，不能以“不显著”等同无效果。
8. 版本一致性：策略、客户端、指标版本变化需新建实验版本。

## 6. 输出决策

- `上线`：仅在线上随机实验健康检查通过、主指标达到预注册门槛且关键护栏不过界时可用。
- `继续观察`：方向正但区间仍宽，且无护栏风险。
- `迭代后重测`：机制部分成立但稳定性不足或分群受损。
- `停止`：主指标明确受损、关键护栏越界或数据质量不可修复。

> 证据边界：Gate 4 is a retrospective offline strategy replay. ENTER_ONLINE_AB_CANDIDATE means eligible for a future randomized experiment, not approved for launch and not proven business lift.
