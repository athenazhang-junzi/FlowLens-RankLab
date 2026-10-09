# FlowLens RankLab｜集成文档

本目录说明 FlowLens、Metarank 与 LiveLab 如何组成一条可复现的离线策略验证链。公开仓库只保留理解接口、核验结果和复现集成层所需的文档。

## 当前状态

| Gate | 目标 | 状态 | 交付物 |
|---|---|---|---|
| A | 定义产品、架构、事件契约与证据边界 | 已完成 | 本目录 4 份基线文档与机器可读事件契约 |
| B | 跑通最小事件导出、Metarank 训练与重排 | 已完成：运行时与候选守恒通过 | 配置、适配器、运行报告与校验记录 |
| C | 把重排结果送回 FlowLens 评估，并让 LiveLab 读取真实离线产物 | 已完成：验证 pilot 决策为 ITERATE_AND_RETEST | 统一指标、配对区间、离线摘要与界面卡片 |
| D | 发布与复现 | 本地复现、精简仓库与 CI 检查通过 | 一键命令、版本锁、CI、Apache-2.0 与复现清单 |

## 文档入口

1. [系统架构](./01-system-architecture.md)：三个组件的职责和数据流。
2. [事件契约](./02-event-contract.md)：FlowLens 与 Metarank 之间的字段、ID、时间和校验规则。
3. [证据与声明边界](./03-evidence-boundary.md)：区分真实离线结果、本地模拟和未来能力。
4. [复现与发布说明](./04-reproduction-and-release.md)：一键入口、运行锁和产物说明。
5. [`metarank_event_contract.json`](../../config/integration/metarank_event_contract.json)：适配器读取的机器可读契约。

## 已冻结的关键决策

- 主仓库继续使用 `FlowLens`，对外产品名暂定为 **FlowLens RankLab**。
- Metarank 以固定版本的外部运行时接入，不复制其 Scala 源码。
- `metarank-zh` 保持独立，作为非官方中文参考资料，不作为 FlowLens 自有代码。
- LiveLab 已纳入 `apps/livelab/`，保留固定种子模拟队列，同时以独立 E3 卡片读取 Gate C 真实离线运行摘要。
- 第一条集成链只处理离线 logged-exposure reranking，不宣称全量召回或线上 A/B。

## 集成与发布检查

- [x] FlowLens 项目代码采用 Apache License 2.0。
- [x] 事件契约中的阻断规则转为可执行校验。
- [x] Metarank 镜像固定为 `metarank/metarank:0.8.0@sha256:495f8f72cef67bbbccd1bc29b9f3d1ddfa322eb2f79eb151a48d9a6b4ed74e63`。
- [x] 使用小型、可公开、无敏感信息的契约样例先完成冒烟测试。
- [x] `smoke` 与完整 `gatec` 一键复现均实际通过。
- [x] LiveLab、运行时锁和静态 CI 检查纳入主仓库。

## Gate B 当前验证结果

- 6 个适配器单元测试通过；
- 真实公开数据导出 200 个回放组、2,077 条事件，10 项合同检查全部通过；
- 真实验证集生成 50 个排序请求、253 个候选，dry-run 通过；
- Metarank 真实导入 2,077 条事件，完成 74／18 会话时间切分与 LambdaMART 训练；
- 排序 API 实际运行 50 个验证请求，253 个候选全部返回；
- 运行时链路通过不代表效果提升；验证候选元数据补齐与统一评估已在 Gate C 独立完成并记录。

具体运行方法见 [Metarank 运行说明](../../services/metarank/README.md)。Gate B 的过程型 JSON 已从公开仓库移除，关键规模和边界保留在本文与运行说明中。

## Gate C 当前验证结果

- 10,000 个训练回放组生成 70,358 条事件，Metarank 导入与训练成功；
- 7,583 个评估内容元数据全覆盖，239 个缺失时长采用哨兵值 + 缺失标记；
- 验证集稳定抽样 2,000 个请求、10,889 个候选，1,455 个用户进入统一评估；
- Metarank 相对冻结基线的 NDCG@5 差异为 -0.049803，95% CI [-0.060228, -0.037868]；
- Top-5 ECR 差异为 -1.5258pp，95% CI [-2.0213pp, -1.0512pp]；
- 验证未过门，决策为 `ITERATE_AND_RETEST`，未查看冻结测试集；
- LiveLab 已显示该 E3 离线摘要，同时保留原有 E4 模拟实验队列。

详见 [Gate C 统一离线评估](../../reports/integration/GateC-统一离线评估.md)。
