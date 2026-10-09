#!/usr/bin/env python3
"""Independently validate FlowLens Gate 3 output consistency and claim boundaries."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports" / "gate3"
MODELS = {"Popularity", "ItemCF", "MultiTaskHashSGD"}
SPLITS = {"validation", "standard_test", "random_sensitivity"}
USER_METRICS = [
    "ndcg_at_5",
    "recall_at_5",
    "ecr_at_5",
    "ctr_at_5",
    "ndcg_at_10",
    "recall_at_10",
    "ecr_at_10",
    "ctr_at_10",
    "mrr_at_10",
    "all_candidate_ecr",
]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def main() -> None:
    required = [
        "baseline_metrics.csv",
        "user_ranking_metrics.csv",
        "tag_supply_demand.csv",
        "daily_standard_test.csv",
        "split_manifest.json",
        "guardrails.json",
        "leakage_report.json",
        "run_manifest.json",
        "Gate3-诊断与基线报告.md",
    ]
    checks: list[dict[str, object]] = []
    missing = [name for name in required if not (REPORT_DIR / name).exists()]
    checks.append(check("required_artifacts_exist", not missing, f"missing={missing}"))
    if missing:
        raise SystemExit(f"Missing required artifacts: {missing}")

    metrics = pd.read_csv(REPORT_DIR / "baseline_metrics.csv")
    user_metrics = pd.read_csv(REPORT_DIR / "user_ranking_metrics.csv")
    tags = pd.read_csv(REPORT_DIR / "tag_supply_demand.csv")
    daily = pd.read_csv(REPORT_DIR / "daily_standard_test.csv")
    split_manifest = json.loads((REPORT_DIR / "split_manifest.json").read_text(encoding="utf-8"))
    leakage = json.loads((REPORT_DIR / "leakage_report.json").read_text(encoding="utf-8"))
    run = json.loads((REPORT_DIR / "run_manifest.json").read_text(encoding="utf-8"))

    observed_pairs = set(map(tuple, metrics[["split", "model"]].itertuples(index=False, name=None)))
    expected_pairs = {(split, model) for split in SPLITS for model in MODELS}
    checks.append(check(
        "model_split_matrix_complete",
        observed_pairs == expected_pairs and len(metrics) == 9,
        f"rows={len(metrics)}, pairs={len(observed_pairs)}",
    ))

    recomputed = user_metrics.groupby(["split", "model"], as_index=False)[USER_METRICS].mean()
    comparison = metrics.merge(recomputed, on=["split", "model"], suffixes=("_reported", "_recomputed"))
    max_abs_diff = 0.0
    for metric in USER_METRICS:
        diff = np.abs(comparison[f"{metric}_reported"] - comparison[f"{metric}_recomputed"])
        max_abs_diff = max(max_abs_diff, float(diff.max()))
    checks.append(check(
        "user_level_metrics_recompute",
        max_abs_diff < 1e-12,
        f"maximum_absolute_difference={max_abs_diff:.3e}",
    ))

    bounded_columns = [
        column for column in metrics.columns
        if column.startswith(("ndcg_", "recall_", "ecr_", "ctr_"))
        or column in {
            "auc_long_view", "mrr_at_10", "all_candidate_ecr",
            "content_coverage_at_10", "author_coverage_at_10",
            "eligible_user_rate", "cold_user_pair_rate", "cold_item_pair_rate",
        }
    ]
    in_range = metrics[bounded_columns].ge(0).all().all() and metrics[bounded_columns].le(1).all().all()
    checks.append(check("metrics_within_unit_interval", bool(in_range), f"columns={len(bounded_columns)}"))

    ci_valid = (
        (metrics["ndcg_at_5_ci_low"] <= metrics["ndcg_at_5"])
        & (metrics["ndcg_at_5"] <= metrics["ndcg_at_5_ci_high"])
    ).all()
    checks.append(check("bootstrap_ci_contains_estimate", bool(ci_valid), "all 9 rows checked"))

    dates_ordered = (
        split_manifest["train"]["date_max"] < split_manifest["validation"]["date_min"]
        and split_manifest["validation"]["date_max"] < split_manifest["standard_test"]["date_min"]
    )
    checks.append(check("strict_time_order", dates_ordered, "train < validation < standard_test"))

    leakage_checks_pass = leakage["status"] == "PASS" and all(leakage["checks"].values())
    expected_rejections = {"forbidden_source", "invalid_availability", "outcome_leakage"}
    observed_rejections = set(leakage["injected_feature_failures"])
    checks.append(check(
        "leakage_suite_and_negative_control",
        leakage_checks_pass and expected_rejections <= observed_rejections,
        f"status={leakage['status']}, injected_rejections={sorted(observed_rejections)}",
    ))

    share_columns = ["supply_share", "demand_share", "exposure_share", "consumption_share"]
    share_errors = {column: abs(float(tags[column].sum()) - 1.0) for column in share_columns}
    checks.append(check(
        "tag_shares_reconcile",
        max(share_errors.values()) < 1e-9,
        ", ".join(f"{key}_error={value:.2e}" for key, value in share_errors.items()),
    ))

    test_dates_complete = set(daily["date"].astype(int)) == set(range(20220422, 20220431)) | set(range(20220501, 20220509))
    checks.append(check(
        "daily_test_window_complete",
        test_dates_complete and int(daily["rows"].sum()) == split_manifest["standard_test"]["rows"],
        f"days={len(daily)}, rows={int(daily['rows'].sum())}",
    ))

    standard_order = metrics.loc[metrics["split"] == "standard_test"].sort_values("ndcg_at_5", ascending=False)["model"].tolist()
    random_order = metrics.loc[metrics["split"] == "random_sensitivity"].sort_values("ndcg_at_5", ascending=False)["model"].tolist()
    checks.append(check(
        "sampling_sensitivity_detected",
        standard_order != random_order,
        f"standard={standard_order}; random={random_order}",
    ))

    checks.append(check(
        "run_manifest_valid_e3",
        run["status"] == "VALID" and run["evidence_level"] == "E3",
        f"run_id={run['run_id']}, status={run['status']}, evidence={run['evidence_level']}",
    ))

    current_script_hash = sha256_file(PROJECT_ROOT / "scripts" / "run_gate3.py")
    current_config_hash = sha256_file(PROJECT_ROOT / "config" / "gate3_baseline.json")
    checks.append(check(
        "code_and_config_hashes_match",
        run["script_sha256"] == current_script_hash and run["config_sha256"] == current_config_hash,
        f"script_match={run['script_sha256'] == current_script_hash}, config_match={run['config_sha256'] == current_config_hash}",
    ))

    missing_manifest_artifacts = [name for name in run["artifacts"] if not (REPORT_DIR / name).exists()]
    checks.append(check(
        "manifest_artifacts_exist",
        not missing_manifest_artifacts,
        f"listed={len(run['artifacts'])}, missing={missing_manifest_artifacts}",
    ))

    overall = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    payload = {
        "status": overall,
        "review_scope": "Gate 3 compact outputs and user-level metric recomputation",
        "checks": checks,
        "claim_boundary": run["claim_boundary"],
    }
    (REPORT_DIR / "validation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# FlowLens Gate 3｜独立校验摘要",
        "",
        f"结论：**{overall}**。本校验从逐用户排名明细独立复算聚合指标，并检查时间边界、区间、标签份额、泄漏负控与运行状态。",
        "",
        "| 检查 | 状态 | 证据 |",
        "|---|---|---|",
    ]
    for item in checks:
        lines.append(f"| `{item['check']}` | {item['status']} | {item['detail']} |")
    lines.extend([
        "",
        "> 边界：该校验确认产物内部一致与泄漏防线有效，不把 logged-exposure 离线指标解释为线上因果提升。",
    ])
    (REPORT_DIR / "validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Gate 3 validation: {overall} ({len(checks)} checks)")
    if overall != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
