# FlowLens Gate 3｜独立校验摘要

结论：**PASS**。本校验从逐用户排名明细独立复算聚合指标，并检查时间边界、区间、标签份额、泄漏负控与运行状态。

| 检查 | 状态 | 证据 |
|---|---|---|
| `required_artifacts_exist` | PASS | missing=[] |
| `model_split_matrix_complete` | PASS | rows=9, pairs=9 |
| `user_level_metrics_recompute` | PASS | maximum_absolute_difference=3.331e-16 |
| `metrics_within_unit_interval` | PASS | columns=18 |
| `bootstrap_ci_contains_estimate` | PASS | all 9 rows checked |
| `strict_time_order` | PASS | train < validation < standard_test |
| `leakage_suite_and_negative_control` | PASS | status=PASS, injected_rejections=['forbidden_source', 'invalid_availability', 'outcome_leakage'] |
| `tag_shares_reconcile` | PASS | supply_share_error=4.00e-15, demand_share_error=2.89e-15, exposure_share_error=3.22e-15, consumption_share_error=3.22e-15 |
| `daily_test_window_complete` | PASS | days=17, rows=289119 |
| `sampling_sensitivity_detected` | PASS | standard=['MultiTaskHashSGD', 'ItemCF', 'Popularity']; random=['ItemCF', 'Popularity', 'MultiTaskHashSGD'] |
| `run_manifest_valid_e3` | PASS | run_id=gate3-3b42b7057a17, status=VALID, evidence=E3 |
| `code_and_config_hashes_match` | PASS | script_match=True, config_match=True |
| `manifest_artifacts_exist` | PASS | listed=11, missing=[] |

> 边界：该校验确认产物内部一致与泄漏防线有效，不把 logged-exposure 离线指标解释为线上因果提升。
