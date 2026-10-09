window.rankLabOfflineRun = {
  "schema_version": "flowlens_livelab_offline_run_v1",
  "id": "gatec-eval-c85d58741bd0473a",
  "name": "Metarank × MultiTask 统一离线复盘",
  "source_type": "offline_replay",
  "evidence_level": "E3",
  "status": "completed",
  "decision": "ITERATE_AND_RETEST",
  "split": "validation",
  "sampling": {
    "method": "hash",
    "seed": 20261009,
    "request_count": 2000,
    "candidate_count": 10889
  },
  "eligible_users": 1455,
  "training": {
    "groups": 10000,
    "events": 70358,
    "interactions": 54482,
    "sampling": "hash",
    "seed": 20261009
  },
  "metadata": {
    "candidate_items": 7583,
    "covered_items": 7583,
    "missing_duration_items": 239,
    "missing_policy": "duration_ms=0 sentinel plus duration_missing=1"
  },
  "models": {
    "baseline": "MultiTaskHashSGD",
    "candidate": "Metarank 0.8.0 LambdaMART"
  },
  "metrics": [
    {
      "key": "ndcg_at_5",
      "name": "NDCG@5",
      "baseline": 0.7543059601302992,
      "metarank": 0.7045027993062145,
      "delta": -0.04980316082408465,
      "ci_low": -0.06022794638893022,
      "ci_high": -0.03786806858431799,
      "better": "higher",
      "guardrail": false
    },
    {
      "key": "ecr_at_5",
      "name": "Top-5 ECR",
      "baseline": 0.4928293241695304,
      "metarank": 0.47757159221076745,
      "delta": -0.015257731958762955,
      "ci_low": -0.020213058419243986,
      "ci_high": -0.010512027491408938,
      "better": "higher",
      "guardrail": false
    },
    {
      "key": "hate_rate_at_5",
      "name": "Top-5 负反馈率",
      "baseline": 0.0006185567010309278,
      "metarank": 0.0007560137457044674,
      "delta": 0.00013745704467353962,
      "ci_low": 0.0,
      "ci_high": 0.00041237113402061863,
      "better": "lower",
      "guardrail": true
    },
    {
      "key": "content_coverage_at_10",
      "name": "内容覆盖@10",
      "baseline": 0.9254843517138599,
      "metarank": 0.9314456035767511,
      "delta": 0.005961251862891204,
      "ci_low": null,
      "ci_high": null,
      "better": "higher",
      "guardrail": true
    },
    {
      "key": "author_repeat_rate_at_10",
      "name": "作者重复@10",
      "baseline": 0.002559046528118693,
      "metarank": 0.0026965035727922327,
      "delta": 0.00013745704467353972,
      "ci_low": 0.0,
      "ci_high": 0.0003436426116838488,
      "better": "lower",
      "guardrail": true
    },
    {
      "key": "primary_tag_repeat_rate_at_10",
      "name": "标签重复@10",
      "baseline": 0.21833878797796322,
      "metarank": 0.21620820378552336,
      "delta": -0.0021305841924398605,
      "ci_low": -0.003917525773195876,
      "ci_high": -0.0005824742268041251,
      "better": "lower",
      "guardrail": true
    }
  ],
  "health_checks": [
    {
      "name": "候选守恒",
      "status": "PASS",
      "detail": "API 输入输出候选集合一致"
    },
    {
      "name": "元数据覆盖",
      "status": "PASS",
      "detail": "7,583 个评估内容均已写入元数据"
    },
    {
      "name": "时间切分",
      "status": "PASS",
      "detail": "只使用训练窗事件训练，验证集仅用于本轮判断"
    },
    {
      "name": "冻结测试集",
      "status": "NOT_RUN",
      "detail": "验证集未过门，因此未查看标准测试与随机敏感性结果"
    }
  ],
  "summary": "Metarank 在本轮验证 cohort 上的 NDCG@5 与 ECR@5 均低于冻结基线，因此决策为 ITERATE_AND_RETEST，不进入冻结测试集。",
  "claim_boundary": "This is a paired E3 offline replay on a deterministic logged-exposure cohort. It is not a randomized online experiment and does not establish causal or business lift.",
  "lineage": {
    "evaluation_manifest_sha256": "e416d1d14b121afe2c8e655c86e362191b655d8b91bcdee7bcd18d8a26a3a599",
    "metrics_sha256": "6ac8b734328455313880d9ad8cc9486e6f0ac6767cd0f6e1d17bac29d6d5b841",
    "paired_deltas_sha256": "665b83e9dcfaa27bda7eaf191668393b6d6fc4ed1e769833aab1b676fd51d845",
    "training_manifest_sha256": "c95d1dea2947c03ab6f6852ea525543e9a80ba513a68f4032aaa0047f360efb8",
    "hydration_manifest_sha256": "1a23aca8026c1d5cf42cd6201078ffd21c7d77774f4cada20fe9930ba9c5515c"
  }
};
