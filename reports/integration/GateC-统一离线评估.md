# FlowLens RankLab｜Gate C 统一离线评估

## 结论

Gate C 已完成可复现的验证集 pilot，决策为 **ITERATE_AND_RETEST**。Metarank 在本轮统一 cohort 上的 NDCG@5 和 Top-5 ECR 都低于冻结的 MultiTaskHashSGD 基线，因此未查看标准测试集和随机曝光敏感性集。

这是 E3 logged-exposure 离线回放，不是线上 A/B 或因果收益。

## 统一口径

| 项目 | 口径 |
|---|---|
| 训练窗 | 2022-04-09 至 2022-04-17 |
| 训练样本 | 从 142,814 个合格回放组中按 seed `20261009` 稳定哈希抽取 10,000 组 |
| 训练事件 | 70,358 条，其中 54,482 条 interaction |
| 评估 cohort | 验证集按同一 seed 稳定哈希抽取 2,000 个请求 |
| 候选 | 10,889 个 user-video pair，Metarank 输入输出守恒 |
| 可评估用户 | 1,455，每人至少 2 个候选且至少 1 个长播正例 |
| 比较组 | 冻结 MultiTaskHashSGD vs. Metarank 0.8.0 LambdaMART |
| 不确定性 | 300 次用户级配对 Bootstrap |

## 结果

| 指标 | MultiTaskHashSGD | Metarank | Metarank - 基线 | 95% 配对区间 |
|---|---:|---:|---:|---:|
| NDCG@5 | 0.754306 | 0.704503 | -0.049803 | [-0.060228, -0.037868] |
| NDCG@10 | 0.793457 | 0.754881 | -0.038576 | [-0.047580, -0.029178] |
| Recall@5 | 0.882696 | 0.852617 | -0.030079 | [-0.039302, -0.020340] |
| Top-5 ECR | 49.2829% | 47.7572% | -1.5258pp | [-2.0213pp, -1.0512pp] |
| Top-5 CTR | 61.1775% | 59.8580% | -1.3196pp | [-1.8093pp, -0.8385pp] |
| Top-5 负反馈率 | 0.0619% | 0.0756% | +0.0137pp | [0.0000pp, 0.0412pp] |
| 内容覆盖@10 | 92.5484% | 93.1446% | +0.5961pp | 全局指标，未估区间 |
| 标签重复@10 | 21.8339% | 21.6208% | -0.2131pp | [-0.3918pp, -0.0582pp] |

Metarank 改善了内容覆盖和标签重复，但主效率指标明确下降，不满足进入冻结测试的门槛。

## 数据质量与决策

- 7,583 个评估内容的元数据均已写入 Metarank；
- 239 个内容在 KuaiRand 原始内容表中缺失时长，使用 `duration_ms=0` 哨兵值并同时设置 `duration_missing=1`；
- 候选守恒、时间切分、元数据覆盖和指标重算均通过；
- 因为验证集未过门，本轮没有查看冻结测试结果，避免为得到有利结论而污染测试集。

## 下一轮

1. 去掉与当前历史顺序强相关、但无法在 FlowLens 请求重建中一致解释的 position 依赖；
2. 将冻结 MultiTask 分数以明确的 relevancy 特征纳入 LambdaMART，而不是只作为请求字段但不参与模型；
3. 只在验证集上迭代并复现本轮配对评估；验证门槛通过后才解锁冻结测试集。

## 证据

- `gatec-validation/manifest.json`：运行、输入、输出与哈希；
- `gatec-validation/metrics.csv`：统一 cohort 聚合指标；
- `gatec-validation/paired_deltas.csv`：用户级配对差异与区间；
- `gatec_metadata_hydration.json`：元数据覆盖和缺失值政策；
- `gatec_livelab_payload.json`：LiveLab 导入的最小公开摘要。
