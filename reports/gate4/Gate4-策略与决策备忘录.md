# FlowLens Gate 4｜策略与决策备忘录

## 决策结论

本次运行 `gate4-c2f35eb1de6d` 完成 S0–S4 五个冻结策略的验证集选参与双日志测试回放。所有结果属于 **E3 离线估计**；`ENTER_ONLINE_AB_CANDIDATE` 仅表示可进入未来随机实验，不表示上线或业务收益已得到证明。

**本轮没有策略通过 A/B 准入门槛。** `S2` 是下一轮优先迭代对象：它在标准曝光集的 NDCG@5 点估计最高，同时改善列表重复，但 NDCG 与 ECR 的配对 95% 区间均跨 0，证据不足以判定稳定增益。

## 标准曝光测试结果（相对 S0）

| 策略 | NDCG@5 | ΔNDCG@5 [95% CI] | Top-5 ECR | ΔECR [95% CI] | 内容覆盖@10 | 作者重复@10 | 随机曝光 ΔNDCG@5 | 离线决策 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| S0 | 0.6236 | +0.0000 [+0.0000, +0.0000] | 45.93% | +0.00% [+0.00%, +0.00%] | 88.49% | 0.36% | +0.0000 | BASELINE |
| S1 | 0.6240 | +0.0004 [-0.0003, +0.0011] | 45.94% | +0.01% [-0.05%, +0.07%] | 87.77% | 0.36% | +0.0184 | ITERATE_AND_RETEST |
| S2 | 0.6241 | +0.0005 [-0.0003, +0.0012] | 45.99% | +0.06% [-0.02%, +0.14%] | 87.54% | 0.31% | +0.0221 | ITERATE_AND_RETEST |
| S3 | 0.6240 | +0.0004 [-0.0003, +0.0011] | 45.98% | +0.06% [-0.02%, +0.14%] | 88.06% | 0.31% | +0.0164 | ITERATE_AND_RETEST |
| S4 | 0.6240 | +0.0004 [-0.0003, +0.0011] | 45.99% | +0.06% [-0.02%, +0.14%] | 88.06% | 0.31% | +0.0164 | ITERATE_AND_RETEST |

## 冻结策略快照

- **S0 · MultiTask baseline**：Frozen Gate 3 learning-model baseline；参数 `{}`。
- **S1 · Collaborative blend**：Blend learned utility with ItemCF affinity；参数 `{"itemcf_weight": 0.15}`。
- **S2 · Diversity rerank**：Reduce repeated authors and primary tags in Top 10；参数 `{"author_repeat_penalty": 0.06, "itemcf_weight": 0.15, "tag_repeat_penalty": 0.04}`。
- **S3 · Long-tail exploration**：Reserve ranking headroom for historically less-exposed items；参数 `{"author_repeat_penalty": 0.06, "itemcf_weight": 0.15, "long_tail_boost": 0.06, "tag_repeat_penalty": 0.04}`。
- **S4 · Negative-feedback and fatigue control**：Penalize historical hate risk and recent author fatigue；参数 `{"author_repeat_penalty": 0.06, "fatigue_penalty": 0.02, "itemcf_weight": 0.15, "long_tail_boost": 0.06, "negative_risk_penalty": 0.1, "tag_repeat_penalty": 0.04}`。

## 决策解释

- **S1 → ITERATE_AND_RETEST**：NDCG@5 增量区间未完全高于 0；Top-5 ECR 增量区间未完全高于 0。
- **S2 → ITERATE_AND_RETEST**：NDCG@5 增量区间未完全高于 0；Top-5 ECR 增量区间未完全高于 0。
- **S3 → ITERATE_AND_RETEST**：NDCG@5 增量区间未完全高于 0；Top-5 ECR 增量区间未完全高于 0。
- **S4 → ITERATE_AND_RETEST**：NDCG@5 增量区间未完全高于 0；Top-5 ECR 增量区间未完全高于 0。

## 下一步线上实验设计

- 随机化单元：用户；同一用户固定分组，避免跨组污染。
- 触发：用户进入目标 Feed 且至少生成 2 个 eligible 候选；分组不等于实际曝光，必须单独记录 `assigned` 与 `exposed`。
- 主指标：用户级有效消费率；互证指标为播放时长，当前公开数据不足以设置真实线上 MDE。
- 护栏：负反馈、同作者／同内容重复、作者与标签覆盖、曝光集中度；收入保持 N/A。
- 健康检查：SRM、触发率、跨组污染、重复事件、版本一致性、迟到事件和 A/A。任一阻断项失败，不生成上线结论。

## 实现与限制

- 运行追踪后端：`local_json_adapter`。MLflow／Evidently 因当前环境无法从 PyPI 安装，使用字段兼容的本地 JSON 适配层；不能写成已集成原生服务。
- S3 使用历史长尾度而非新内容年龄：数据上传日期过于集中，无法可靠验证持续冷启动。
- 标准曝光与随机曝光来自不同采集策略，跨日志差异只做稳健性诊断。
- 本次是 retrospective replay；正式线上实验必须重新预注册参数、MDE、样本量与停止规则。
