# FlowLens RankLab｜Metarank 运行说明

本目录固定 FlowLens RankLab 的 Metarank 运行时基线。Gate B 已完成最小运行时验收；Gate C 已完成统一验证集比较；Gate D 已用固定镜像再次完成完整一键复现。当前效果决策为 `ITERATE_AND_RETEST`。

## 文件

- `config.yml`：Metarank 0.8.0 的 LambdaMART 初始配置。
- `compose.yml`：使用固定 tag、digest 与平台，读取本地训练事件的运行入口。
- `THIRD_PARTY.md`：版本、许可证和验证边界。

## 1. 导出真实训练事件

在 FlowLens 仓库根目录执行：

```bash
.venv/bin/python scripts/export_metarank_events.py --max-groups 200
.venv/bin/python scripts/validate_metarank_events.py \
  --events runs/integration/gateb-contract/events.jsonl
```

`--max-groups 0` 表示导出训练窗内全部合格回放组。建议先使用 200 组完成冒烟验证，再扩大数据量。

## 2. 启动 Metarank

前提：Docker Engine／Docker Desktop 可用。

```bash
docker compose -f services/metarank/compose.yml up
```

该命令使用 `metarank/metarank:0.8.0` 执行 standalone 导入、训练和 API 服务。首次成功运行时必须额外记录镜像 digest 和完整日志；不能只凭容器启动就标记 Gate B 完成。

如需使用 Gate C 训练事件，可通过环境变量替换默认输入：

```bash
METARANK_EVENTS_FILE=../../runs/integration/gatec-runtime/events.jsonl \
  docker compose -f services/metarank/compose.yml up -d --force-recreate
```

## 3. 生成验证集排序请求

不调用服务的 dry-run：

```bash
.venv/bin/python scripts/call_metarank_rank.py \
  --candidates reports/gate3/validation_candidate_scores.csv \
  --split validation \
  --timestamp-ms 1650207850712 \
  --max-requests 50 \
  --dry-run
```

Metarank 服务训练完成后，移除 `--dry-run`：

```bash
.venv/bin/python scripts/call_metarank_rank.py \
  --candidates reports/gate3/validation_candidate_scores.csv \
  --split validation \
  --timestamp-ms 1650207850712 \
  --max-requests 50
```

适配器会阻断候选缺失、增项或重复。实际响应只有通过候选守恒后才能进入 Gate C 评估。

## 4. Gate D 一键复现

在仓库根目录执行：

```bash
make ranklab-smoke
make ranklab-gatec
```

默认运行结束后停止容器；调试时可使用 `--keep-service`。完整参数、产物和发布边界见 [`docs/integration/04-reproduction-and-release.md`](../../docs/integration/04-reproduction-and-release.md)。

## 5. 已验证的运行基线

- 镜像：`metarank/metarank:0.8.0`，`linux/arm64`；
- 导入：2,077 条事件，2,799 个状态更新；
- 训练：92 个 clickthrough，74／18 时间切分，模型上传成功；
- API：50 个请求返回 253 行，候选守恒通过；
- 对应过程型 JSON 已从精简后的公开仓库移除；上面的规模摘要用于说明已验证范围，不代表效果提升。

完整 Gate D 复现再次得到 2,000 个验证请求、10,889 个候选和 `ITERATE_AND_RETEST` 决策；这不是效果提升证据。

## 6. 当前边界

- 回放组是按 `user_id + date + tab` 构造的 E3 派生训练组，不是真实线上 request/slate。
- `click: 3` 和 `long_view: 7` 是与 30%／70% 目标等比例的整数标签基线，不是调优结果。
- `negative_feedback` 会进入事件流，并在 Metarank 中显式映射为整数标签 `0`，不作为正向训练奖励；真正的负反馈护栏仍由 FlowLens 统一评估。
- KuaiRand 内容表中缺失的 `video_duration` 使用 `duration_ms=0` 哨兵值，并同时写入 `duration_missing=1`；不删除这些候选，也不把哨兵值解释为真实时长。
- Metarank 得分只用于同一次请求内排序，不解释为点击率或长播概率。
