# FlowLens RankLab｜Gate D 复现与发布说明

## 1. 当前结论

Gate D 的代码与本地复现链路已经建立：主仓库包含 LiveLab、固定运行时、静态发布检查、CI 检查和一键复现入口。2026-10-09 已使用同一个入口实际完成 `smoke` 与完整 `gatec` 两档运行；完整档复现出 Gate C 相同的 10,000 个训练组、2,000 个验证请求、10,889 个候选和 `ITERATE_AND_RETEST` 决策。

正式公开发布仍有一个收口条件：

1. 当前修改提交后，在真正的干净 clone 中再次执行依赖安装与静态检查，并按需完成数据准备后的完整复现。

FlowLens 与仓库内 LiveLab 代码已选择 Apache License 2.0。该许可证不覆盖未随仓库分发的 KuaiRand-Pure 数据，也不改变外部 Metarank 项目的归属。

当前本地复现来自未提交工作树，清单中的 `git.dirty=true` 是事实记录，不能表述为“已由公开 commit 完整复现”。去除 `.git`、`.venv`、本地数据和 `runs/` 的临时源码副本已通过 `make ranklab-check`；由于 PyPI TLS 握手失败，该次隔离检查使用新建的 `--system-site-packages` 虚拟环境，没有冒充为一次独立联网安装。

## 2. 固定运行时

- Python：3.12；
- NumPy：2.3.5；
- pandas：2.2.3；
- Metarank：`0.8.0`；
- 镜像：固定 tag、digest 与 `linux/arm64` 平台；
- 抽样：稳定哈希，seed `20261009`；
- 完整锁文件：[`runtime_lock.json`](../../config/integration/runtime_lock.json)。

`linux/arm64` 是当前已实测平台。其他架构不能仅凭 tag 推定结果一致，需要单独生成并验证对应 digest。

## 3. 新环境准备

先按 [`data/README.md`](../../data/README.md) 下载 KuaiRand-Pure，再完成 Gate 2 和 Gate 3，生成清洗事件与候选文件。原始数据、处理中间表和逐候选大文件不会进入 Git。

安装 RankLab 运行依赖：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-integration.txt
```

Docker Desktop／Docker Engine 必须已启动。LiveLab 静态检查还需要 Node.js；页面运行本身不需要 npm 安装。

## 4. 一键入口

仅检查可公开的代码、文档、血缘和前端：

```bash
make ranklab-check
```

快速端到端复现：

```bash
make ranklab-smoke
```

完整 Gate C 规模复现：

```bash
make ranklab-gatec
```

两档入口都会依次执行：训练事件导出 → 事件合同校验 → Compose 配置校验 → Metarank 导入／训练／服务 → 候选元数据补齐 → 排序请求 → 统一 cohort 评估 → LiveLab 摘要生成。

默认运行结束后停止容器，且不覆盖仓库中的正式 LiveLab 摘要。调试时可直接运行：

```bash
.venv/bin/python scripts/run_ranklab_reproduction.py \
  --profile gatec \
  --keep-service
```

只有核对新结果并明确要更新展示时，才使用 `--publish-livelab`；该参数只允许用于 `gatec` 档。

## 5. 产物与审计

- 每次运行写入独立的 `runs/integration/gated-<profile>-<UTC>/`，该目录不进入 Git；
- 最新复现摘要写入 `reports/integration/gated_reproduction_latest.json`；
- 清单记录输入哈希、锁文件哈希、Git commit／dirty 状态、逐步骤退出码、容器 ID、请求数、候选数和最终决策；
- `scripts/verify_ranklab_release.py` 检查镜像锁、第三方声明、Gate C 状态、LiveLab JSON/JS 一致性和公开血缘；
- `.github/workflows/ranklab-check.yml` 只执行不依赖未提交数据的静态发布检查，不伪装成完整模型复现。

## 6. 已执行记录

完整 Gate D 本地运行：`gated-gatec-20261009T060623Z`。

- 训练：10,000 个回放组，70,358 条事件；
- 元数据：7,583 个候选内容写入；
- 排序：2,000 个请求、10,889 个候选，候选守恒通过；
- 评估：1,455 个用户；
- NDCG@5 差异：-0.049803，95% CI [-0.060228, -0.037868]；
- Top-5 ECR 差异：-1.5258pp，95% CI [-2.0213pp, -1.0512pp]；
- 决策：`ITERATE_AND_RETEST`；冻结测试集仍未运行。

这是一条 E3 logged-exposure 离线复现链，不是线上 A/B 或业务收益证明。

## 7. 正式发布清单

- [x] LiveLab 纳入主仓库；
- [x] Python 包版本锁定；
- [x] Metarank tag、digest 与平台锁定；
- [x] 第三方来源和许可证说明；
- [x] 一键 smoke／gatec 入口；
- [x] 静态 CI 检查；
- [x] 本地完整复现通过；
- [x] 无本地数据、无原工作区虚拟环境的临时源码副本通过静态检查；
- [x] FlowLens 代码采用 Apache License 2.0；
- [ ] 提交当前修改；
- [ ] 在干净 clone 中完成独立依赖安装并复跑 `make ranklab-check`；
- [ ] 如需声称完整可复现，在完成公开数据准备后复跑 `make ranklab-gatec`。
