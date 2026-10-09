#!/usr/bin/env python3
"""Independently validate Gate 4 strategy, delta, decision, and lineage outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports" / "gate4"
STRATEGIES = ["S0", "S1", "S2", "S3", "S4"]
SPLITS = ["validation", "standard_test", "random_sensitivity"]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def main() -> None:
    required = [
        "strategy_metrics.csv", "strategy_deltas.csv", "offline_decisions.csv",
        "validation_selection.csv", "user_strategy_metrics.csv", "explanation_samples.csv",
        "strategy_snapshots.json", "evaluation_tests.json", "run_manifest.json",
        "mlflow_compatible_runs.json", "Gate4-策略与决策备忘录.md", "Gate4-线上AB实验设计.md",
    ]
    checks: list[dict[str, str]] = []
    missing = [name for name in required if not (REPORT_DIR / name).exists()]
    checks.append(result("required_artifacts_exist", not missing, f"missing={missing}"))
    if missing:
        raise SystemExit(f"Missing artifacts: {missing}")

    config_path = PROJECT_ROOT / "config" / "gate4_strategies.json"
    script_path = PROJECT_ROOT / "scripts" / "run_gate4.py"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = json.loads((REPORT_DIR / "run_manifest.json").read_text(encoding="utf-8"))
    gate3 = json.loads((PROJECT_ROOT / "reports" / "gate3" / "run_manifest.json").read_text(encoding="utf-8"))
    metrics = pd.read_csv(REPORT_DIR / "strategy_metrics.csv")
    deltas = pd.read_csv(REPORT_DIR / "strategy_deltas.csv")
    decisions = pd.read_csv(REPORT_DIR / "offline_decisions.csv")
    selection = pd.read_csv(REPORT_DIR / "validation_selection.csv")
    users = pd.read_csv(REPORT_DIR / "user_strategy_metrics.csv")
    snapshots = json.loads((REPORT_DIR / "strategy_snapshots.json").read_text(encoding="utf-8"))
    suite = json.loads((REPORT_DIR / "evaluation_tests.json").read_text(encoding="utf-8"))

    checks.append(result(
        "manifest_hashes_match_current_code",
        manifest["script_sha256"] == sha256_file(script_path) and manifest["config_sha256"] == sha256_file(config_path),
        f"script_match={manifest['script_sha256'] == sha256_file(script_path)}, config_match={manifest['config_sha256'] == sha256_file(config_path)}",
    ))
    checks.append(result(
        "upstream_gate3_lineage_matches",
        manifest["upstream_gate3_run_id"] == gate3["run_id"] == config["upstream_gate3_run_id"],
        f"gate3_run_id={gate3['run_id']}",
    ))

    expected = {(split, strategy) for split in SPLITS for strategy in STRATEGIES}
    observed = set(map(tuple, metrics[["split", "strategy"]].itertuples(index=False, name=None)))
    checks.append(result("strategy_split_matrix_complete", observed == expected and len(metrics) == 15, f"rows={len(metrics)}, pairs={len(observed)}"))

    candidate_consistency = metrics.groupby("split")[["candidate_pairs", "candidate_users", "eligible_users"]].nunique().eq(1).all().all()
    checks.append(result("identical_candidates_within_split", bool(candidate_consistency), "candidate counts are identical across S0-S4"))

    mean_map = {
        "ndcg_at_5": "ndcg_at_5",
        "ecr_at_5": "long_view_rate_at_5",
        "ctr_at_5": "is_click_rate_at_5",
        "hate_rate_at_5": "is_hate_rate_at_5",
        "author_repeat_rate_at_10": "author_repeat_rate_at_10",
        "primary_tag_repeat_rate_at_10": "primary_tag_repeat_rate_at_10",
        "negative_risk_at_5": "negative_risk_at_5",
        "long_tail_share_at_10": "long_tail_share_at_10",
    }
    recomputed = users.groupby(["split", "strategy"], as_index=False)[list(mean_map.values())].mean()
    recomputed = recomputed.rename(columns={source: f"{reported}_recomputed" for reported, source in mean_map.items()})
    merged = metrics.merge(recomputed, on=["split", "strategy"])
    max_diff = 0.0
    for reported, source in mean_map.items():
        max_diff = max(max_diff, float(np.abs(merged[reported] - merged[f"{reported}_recomputed"]).max()))
    checks.append(result("user_metrics_recompute", max_diff < 1e-12, f"maximum_absolute_difference={max_diff:.3e}"))

    delta_max_diff = 0.0
    for row in deltas.itertuples(index=False):
        base = users[(users["split"] == row.split) & (users["strategy"] == "S0")].set_index("user_id")
        current = users[(users["split"] == row.split) & (users["strategy"] == row.strategy)].set_index("user_id")
        common = base.index.intersection(current.index)
        for output, column in [("ndcg_at_5", "ndcg_at_5"), ("ecr_at_5", "long_view_rate_at_5"), ("hate_rate_at_5", "is_hate_rate_at_5")]:
            actual = float((current.loc[common, column] - base.loc[common, column]).mean())
            delta_max_diff = max(delta_max_diff, abs(actual - getattr(row, f"{output}_delta")))
    checks.append(result("paired_deltas_recompute", delta_max_diff < 1e-12, f"maximum_absolute_difference={delta_max_diff:.3e}"))

    selected_valid = True
    for strategy in STRATEGIES:
        group = selection[selection["strategy"] == strategy]
        selected_rows = group[group["selected"]]
        selected_valid &= len(selected_rows) == 1 and np.isclose(selected_rows.iloc[0]["objective"], group["objective"].max())
    checks.append(result("validation_selection_is_argmax", bool(selected_valid), "one validation argmax selected per strategy"))

    snapshot_valid = set(snapshots) == set(STRATEGIES)
    for strategy, snapshot in snapshots.items():
        expected_hash = hashlib.sha256(json.dumps(snapshot["parameters"], sort_keys=True).encode("utf-8")).hexdigest()
        snapshot_valid &= snapshot["snapshot_sha256"] == expected_hash and snapshot["selected_on"] == "validation"
    checks.append(result("strategy_snapshots_are_immutable", bool(snapshot_valid), f"snapshots={len(snapshots)}"))

    allowed = set(config["allowed_strategy_features"])
    forbidden = set(config["forbidden_strategy_features"])
    checks.append(result("forbidden_outcomes_not_scoring_features", not bool(allowed & forbidden), f"overlap={sorted(allowed & forbidden)}"))

    suite_valid = suite["status"] == "PASS_WITH_CONDITIONS" and all(item["status"] == "PASS" for item in suite["tests"])
    checks.append(result("evaluation_adapter_tests_pass", suite_valid, f"tests={len(suite['tests'])}, drift={suite['distribution_shift']['status']}"))

    decision_values = set(decisions["decision"])
    valid_decisions = decision_values <= {"BASELINE", "ENTER_ONLINE_AB_CANDIDATE", "ITERATE_AND_RETEST", "STOP"}
    checks.append(result("decision_vocabulary_and_boundary", valid_decisions and manifest["evidence_level"] == "E3", f"decisions={sorted(decision_values)}"))

    memo = (REPORT_DIR / "Gate4-策略与决策备忘录.md").read_text(encoding="utf-8")
    experiment = (REPORT_DIR / "Gate4-线上AB实验设计.md").read_text(encoding="utf-8")
    no_false_launch = "不表示上线" in memo and "不代表真实平台已经启动实验" in experiment and "收入保持 N/A" in memo
    checks.append(result("claim_boundary_visible", no_false_launch, "offline, experiment, and revenue boundaries are explicit"))

    artifact_missing = [name for name in manifest["artifacts"] if not (REPORT_DIR / name).exists()]
    checks.append(result("manifest_artifacts_exist", not artifact_missing, f"listed={len(manifest['artifacts'])}, missing={artifact_missing}"))

    explanation_rows = len(pd.read_csv(REPORT_DIR / "explanation_samples.csv"))
    checks.append(result("explanation_samples_present", explanation_rows == 100, f"rows={explanation_rows}"))

    overall = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    payload = {
        "status": overall,
        "review_scope": "Gate 4 strategy selection, metrics, deltas, decisions, evidence boundaries, and lineage",
        "checks": checks,
        "claim_boundary": config["claim_boundary"],
    }
    (REPORT_DIR / "validation_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# FlowLens Gate 4｜独立校验摘要", "",
        f"结论：**{overall}**。校验覆盖逐用户指标复算、配对差值、验证集选参、策略快照、决策边界与运行血缘。", "",
        "| 检查 | 状态 | 证据 |", "|---|---|---|",
    ]
    lines.extend(f"| `{item['check']}` | {item['status']} | {item['detail']} |" for item in checks)
    lines.extend(["", "> 本校验确认离线产物内部一致；不把 retrospective replay 转换为线上因果或商业收益证明。"])
    (REPORT_DIR / "validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Gate 4 validation: {overall} ({len(checks)} checks)")
    if overall != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
