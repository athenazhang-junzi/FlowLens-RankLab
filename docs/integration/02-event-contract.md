# FlowLens ↔ Metarank 事件契约 v0.1

## 1. 适用范围

契约 ID：`flowlens_metarank_event_contract_v0.1`

本契约服务于两个明确区分的模式：

| 模式 | 证据等级 | 用途 |
|---|---|---|
| `logged_exposure_replay` | E3 | 用公开历史日志构造训练组、验证和测试重排 |
| `future_online_contract` | E0 | 描述未来真实系统应发送的请求与反馈；当前没有实现或数据 |

本文的 JSON 示例只说明结构，不是已经运行的结果。

## 2. 关键语义约束

1. `ranking` 表示一次用于训练或推理的显式候选列表。
2. KuaiRand-Pure 缺少可验证的完整原始 request/slate ID，因此回放模式下的 `ranking` 是派生训练组，不能称为真实线上曝光列表。
3. Metarank 的 `impression` 是保留交互类型，FlowLens 不发送 `type=impression`。
4. 负反馈先作为事件留痕和 FlowLens 护栏，不在 v0.1 中进入模型训练权重。
5. 排序 API 只允许重排输入候选；输入和输出的内容集合必须完全一致。

## 3. ID 规范

所有业务 ID 在进入 Metarank 前加命名空间，避免不同数据源碰撞：

| 对象 | 格式 | 示例 |
|---|---|---|
| user | `krp:user:<user_id>` | `krp:user:42` |
| item | `krp:video:<video_id>` | `krp:video:1396` |
| session | `krp:<mode>:<user_id>:<date>:<tab>` | `krp:replay:42:20220410:1` |
| ranking | `flr:rank:<contract>:<split>:<stable_hash>` | `flr:rank:v0.1:train:7e91ab20` |
| interaction | `flr:int:<type>:<stable_hash>` | `flr:int:long_view:2fe891ad` |
| item event | `flr:item:<video_id>:<metadata_version>` | `flr:item:1396:v1` |

`stable_hash` 必须来自规范化源键，不使用 Python 进程级随机哈希。Gate B 应固定为 SHA-256 前 16 位，并在 manifest 中记录输入字段。

## 4. 时间规则

- 统一使用 UTC epoch milliseconds 传给 Metarank；源 `date` 仍保留在字段中，不静默改写。
- 回放训练组按 `user_id + date + tab` 构造，组内候选按源 `time_ms` 排序。
- `ranking.timestamp` 取该组最早源事件之前 1ms；每个交互保留其真实源 `time_ms`。
- 若最早时间不可用、无法解析或导致父排序晚于交互，整组阻断，不用文件行号制造时间。
- 评估 `/rank` 请求使用切分配置中冻结的评估时点，并在请求字段中写明 `evaluation_as_of`；不得读取该时点后的特征。
- 同一源 `date` 与 `time_ms` 推导日期不一致时，遵循现有 FlowLens 策略：分区使用源 `date`，组内顺序使用 `time_ms`，并记录不一致标记。

## 5. FlowLens 到 Metarank 映射

### 5.1 内容元数据 `item`

| FlowLens 字段 | Metarank 位置 | 规则 |
|---|---|---|
| `video_id` | `item` | 加 `krp:video:` 前缀 |
| `author_id` | `fields.author_id` | 字符串；缺失则内容不进入作者级特征 |
| `tag` | `fields.tags` | 规范化为字符串数组；未知值显式写 `UNKNOWN_TAG` |
| `upload_dt` | `fields.upload_date` | 只在源字段可验证时提供 |
| `video_duration` | `fields.duration_ms` | 只使用请求时可得的基础元数据；源值缺失时省略，不以中位数静默填充 |
| 元数据版本 | `fields.metadata_version` | 适配器配置版本 |

禁止把 `video_features_statistic_pure.csv` 的全月聚合字段写入训练或评估事件。

示例：

```json
{
  "event": "item",
  "id": "flr:item:1396:v1",
  "timestamp": 1640995200000,
  "item": "krp:video:1396",
  "fields": [
    {"name": "author_id", "value": "1174959"},
    {"name": "tags", "value": ["9"]},
    {"name": "metadata_version", "value": "v1"}
  ]
}
```

### 5.2 排序事件 `ranking`

| FlowLens 来源 | Metarank 位置 | 规则 |
|---|---|---|
| 派生 request ID | `id` | 后续交互通过 `ranking` 引用同一 ID |
| `user_id` | `user` | 加命名空间 |
| 用户／日期／tab | `session` | 稳定且可复算 |
| `tab` | `fields.scene_tab` | 字符串，不编造业务名称 |
| 数据切分 | `fields.dataset_split` | `train`／`validation`／`standard_test`／`random_sensitivity` |
| 来源模式 | `fields.source_mode` | 固定为 `logged_exposure_replay` |
| FlowLens 运行 | `fields.upstream_run_id` | 例如 Gate 3 run ID |
| 策略版本 | `fields.strategy_version` | 基线或策略快照 ID |
| `video_id` | `items[].id` | 加命名空间 |
| 上游基础分 | `items[].fields.relevancy` | 首版使用冻结的 `multitask_score`；字段名和来源同时记录 |
| 其他基线分 | `items[].fields.*` | 可保留 `itemcf_score`、`popularity_score`，是否入模由配置决定 |

示例：

```json
{
  "event": "ranking",
  "id": "flr:rank:v0.1:validation:7e91ab20",
  "timestamp": 1650153599999,
  "user": "krp:user:42",
  "session": "krp:replay:42:20220417:1",
  "fields": [
    {"name": "scene_tab", "value": "1"},
    {"name": "dataset_split", "value": "validation"},
    {"name": "source_mode", "value": "logged_exposure_replay"},
    {"name": "upstream_run_id", "value": "gate3-3b42b7057a17"},
    {"name": "strategy_version", "value": "multitask_gate3_v1"}
  ],
  "items": [
    {
      "id": "krp:video:1396",
      "fields": [
        {"name": "relevancy", "value": 0.7674105},
        {"name": "itemcf_score", "value": 1.6223123}
      ]
    }
  ]
}
```

示例中的数值来自现有候选文件，只用于说明字段位置；它不表示 Metarank 已经运行或产生了改进。

### 5.3 交互事件 `interaction`

| FlowLens 条件 | Metarank `type` | v0.1 用途 |
|---|---|---|
| `is_click == 1` | `click` | 可作为训练反馈，权重由冻结配置记录 |
| `long_view == 1` | `long_view` | 可作为训练反馈，权重由冻结配置记录 |
| `is_hate == 1` | `negative_feedback` | 仅留痕和 FlowLens 护栏；默认不进入训练权重 |
| `is_like == 1` 等 | 同名显式类型 | v0.1 不纳入模型，后续需单独决策 |

同一源记录可产生多个交互事件，但每个事件 ID 必须唯一，且都引用同一父 `ranking`。

```json
{
  "event": "interaction",
  "id": "flr:int:long_view:2fe891ad",
  "ranking": "flr:rank:v0.1:train:7e91ab20",
  "timestamp": 1649552400123,
  "user": "krp:user:42",
  "session": "krp:replay:42:20220410:1",
  "type": "long_view",
  "item": "krp:video:1396",
  "fields": [
    {"name": "evidence_level", "value": "E1"},
    {"name": "source_dataset", "value": "KuaiRand-Pure"}
  ]
}
```

## 6. 推理请求与响应合同

推理调用使用 `POST /rank/<model>?explain=true`。请求结构与 `ranking` 主体一致，但不带 `event` 字段；响应必须保存原始 JSON，不只保存最终名次。

适配器输出表至少包含：

| 字段 | 含义 |
|---|---|
| `integration_run_id` | 本次集成运行 |
| `request_id` | 排序请求 ID |
| `user_id` | FlowLens 匿名用户 ID |
| `video_id` | FlowLens 内容 ID |
| `input_rank` | 输入候选位置 |
| `upstream_score` | 上游冻结分数 |
| `metarank_rank` | Metarank 返回位置 |
| `metarank_score` | 同一次请求内的模型分数 |
| `explain_features_json` | `explain=true` 返回的特征快照 |
| `model_name` | Metarank 模型名 |
| `config_sha256` | 配置哈希 |
| `response_took_ms` | Metarank 报告的处理时间；不外推为生产 SLA |

Metarank 分数仅用于同一请求内排序，除非另有校准证据，不解释为点击或长播概率。

## 7. 与 LiveLab 的映射

LiveLab 的事件链 `eligible → assigned → exposed → clicked → content_start → long_view / negative_feedback` 不直接等同于 Metarank 的四类事件：

| LiveLab | 当前集成含义 |
|---|---|
| `eligible` | FlowLens 规则允许进入候选；不是 Metarank 事件 |
| `assigned` | 未来实验分组；Gate C 只读展示，不由 Metarank 产生 |
| `exposed` | 对应已经实际展示的排序结果；回放模式只有派生近似，必须标 E3 |
| `clicked` | 映射为 `interaction.type=click` |
| `content_start` | 可留在 FlowLens 实验合同，v0.1 不进入模型 |
| `long_view` | 映射为 `interaction.type=long_view` |
| `negative_feedback` | 映射为同名交互，但默认仅用于护栏 |

## 8. 阻断级校验

导出事件在进入 Metarank 前必须全部通过：

- 每个事件 `id` 非空且全局唯一；
- `item`、`user`、`session` 命名空间一致；
- 每个 interaction 引用已存在且更早的 ranking；
- interaction.item 存在于父 ranking.items；
- 不发送保留的 `impression` 类型；
- 同一 ranking 内 item 唯一，候选数至少为 2；
- 时间戳可解析，且不使用未来结果字段生成训练特征；
- 训练、验证、标准测试和随机敏感性切分不交叉；
- API 输入和输出的 item 集合、数量完全一致；
- 失败、跳过和缺失记录均有计数，不能静默丢弃。

## 9. 尚未冻结的模型选择

事件契约不预设训练权重。Gate B 配置必须显式记录：

- 模型类型与后端；
- `click`、`long_view` 的权重；
- 使用哪些内容、上下文、历史和上游分数特征；
- 训练／验证时间窗；
- 随机种子；
- 负反馈是否入模，以及对应版本证据。

这些选择只能在验证集上确定，测试集保持冻结。
