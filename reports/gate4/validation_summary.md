# FlowLens Gate 4｜独立校验摘要

结论：**PASS**。校验覆盖逐用户指标复算、配对差值、验证集选参、策略快照、决策边界与运行血缘。

| 检查 | 状态 | 证据 |
|---|---|---|
| `required_artifacts_exist` | PASS | missing=[] |
| `manifest_hashes_match_current_code` | PASS | script_match=True, config_match=True |
| `upstream_gate3_lineage_matches` | PASS | gate3_run_id=gate3-3b42b7057a17 |
| `strategy_split_matrix_complete` | PASS | rows=15, pairs=15 |
| `identical_candidates_within_split` | PASS | candidate counts are identical across S0-S4 |
| `user_metrics_recompute` | PASS | maximum_absolute_difference=1.110e-16 |
| `paired_deltas_recompute` | PASS | maximum_absolute_difference=9.845e-17 |
| `validation_selection_is_argmax` | PASS | one validation argmax selected per strategy |
| `strategy_snapshots_are_immutable` | PASS | snapshots=5 |
| `forbidden_outcomes_not_scoring_features` | PASS | overlap=[] |
| `evaluation_adapter_tests_pass` | PASS | tests=8, drift=WARN |
| `decision_vocabulary_and_boundary` | PASS | decisions=['BASELINE', 'ITERATE_AND_RETEST'] |
| `claim_boundary_visible` | PASS | offline, experiment, and revenue boundaries are explicit |
| `manifest_artifacts_exist` | PASS | listed=11, missing=[] |
| `explanation_samples_present` | PASS | rows=100 |

> 本校验确认离线产物内部一致；不把 retrospective replay 转换为线上因果或商业收益证明。
