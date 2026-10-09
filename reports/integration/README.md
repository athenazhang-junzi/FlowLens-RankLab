# FlowLens RankLab｜Gate B 适配器验证摘要

> 本页保留 Gate B 的历史运行证据。Gate C 已于 2026-10-09 完成统一离线评估，结论为 `ITERATE_AND_RETEST`；完整结果见 [`GateC-统一离线评估.md`](./GateC-%E7%BB%9F%E4%B8%80%E7%A6%BB%E7%BA%BF%E8%AF%84%E4%BC%B0.md)。

## 结论

Gate B 的 **事件导出、Metarank 导入／训练／服务和排序请求链路已验证**。50 个验证集请求全部成功，253 个候选全部返回。这是技术运行时验收，不是模型效果结论；模型效果结论以后续 Gate C 统一离线评估为准。

## 已实际运行

| 检查 | 结果 | 证据 |
|---|---:|---|
| Python 单元测试 | 6/6 通过 | `tests/test_metarank_integration.py` |
| 合成契约样例 | 13 条事件，10 项合同检查通过 | 临时测试产物，不作为业务结果 |
| 真实公开数据事件导出 | 200 个回放组，2,077 条事件 | 本地 `runs/integration/gateb-contract/export_manifest.json` |
| 内容／排序／交互事件 | 936／200／941 | `gateb_event_validation.json` |
| 排序请求 dry-run | 50 个请求、253 个候选 | `gateb_rank_dry_run.json` |
| Metarank 导入 | 2,077 条事件，生成 2,799 个状态更新 | `gateb_runtime_validation.json` |
| Metarank 训练 | 92 个 clickthrough，74／18 时间切分，模型上传成功 | `gateb_runtime_validation.json` |
| 排序 API | 50 个请求、253 个结果，候选守恒通过 | `gateb_rank_runtime.json` |

真实数据导出沿用 Gate 3 训练窗 `20220409–20220417`，上游运行是 `gate3-3b42b7057a17`。候选组按用户、日期和 tab 派生，因此属于 E3 logged-exposure replay，不代表原平台真实请求。

## 已阻断的风险

- 全局事件 ID 重复；
- item／user／session 命名空间错误；
- 排序候选不足或重复；
- 候选缺少内容元数据事件；
- 结果标签泄漏进排序字段；
- interaction 缺少父 ranking 或不属于父候选；
- interaction 早于父 ranking；
- 自行发送 Metarank 保留的 `impression`；
- JSONL 事件流时间倒序；
- 排序 API 返回候选缺失、增项或重复。

## 运行时边界

- 固定镜像为 `metarank/metarank:0.8.0@sha256:495f...74e63`，平台为 `linux/arm64`。
- Metarank 内部 18 个测试会话上 source 与 reranked 的 NDCG@5 均为 1.0，这不是相对 FlowLens 基线的提升证据。
- 200 组冒烟训练事件未覆盖所有验证候选：`item_duration` 覆盖 117/253，`tag_diversity` 覆盖 133/253。
- API 有效证明版本兼容、请求成功与候选守恒，不证明排序效果提升。

## Gate C 衔接结果

Gate C 已完成以下三项衔接：

1. 为 7,583 个唯一验证候选补齐内容元数据；239 个源数据缺失时长的内容使用 `duration_ms=0` 与 `duration_missing=1` 显式表示缺失，而非虚构时长；
2. 在同一验证候选、标签、时间切分和指标口径下，对 FlowLens 冻结基线与 Metarank 进行配对比较；
3. 将可追溯摘要静态导入 LiveLab，并明确标记为 E3 离线回放结果。
