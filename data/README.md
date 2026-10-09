# 数据准备

FlowLens RankLab 使用官方 KuaiRand-Pure 数据进行离线回放。

- 来源：https://zenodo.org/records/10439422
- 文件：`KuaiRand-Pure.tar.gz`
- 发布方提供的 MD5：`0820331067a3784d9691136f772b35a7`
- 数据许可：CC BY-SA 4.0

下载并校验：

```bash
curl -L --fail --retry 3 \
  -o data/raw/KuaiRand-Pure.tar.gz \
  https://zenodo.org/records/10439422/files/KuaiRand-Pure.tar.gz
md5 data/raw/KuaiRand-Pure.tar.gz
tar -xzf data/raw/KuaiRand-Pure.tar.gz -C data/extracted
```

完整 RankLab 复现还需要原 FlowLens 数据流水线生成以下本地输入：

- `data/processed/events/log_standard_4_08_to_4_21_pure_clean.csv`
- `reports/gate3/validation_candidate_scores.csv`
- `reports/gate3/standard_test_candidate_scores.csv`
- `reports/gate3/random_sensitivity_candidate_scores.csv`

这些大体积输入以及 `data/raw/`、`data/extracted/`、`data/processed/`、`runs/` 均被 Git 忽略。公开仓库不重新分发数据，也不把缺少本地数据时的静态检查表述为完整模型复现。
