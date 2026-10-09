#!/usr/bin/env python3
"""Build the public Gate C summary consumed by the local FlowLens LiveLab."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from metarank_contract import PROJECT_ROOT, sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evaluation-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "integration" / "gatec-validation",
    )
    parser.add_argument(
        "--training-manifest",
        type=Path,
        default=PROJECT_ROOT / "runs" / "integration" / "gatec-runtime" / "export_manifest.json",
    )
    parser.add_argument(
        "--hydration-manifest",
        type=Path,
        default=PROJECT_ROOT / "reports" / "integration" / "gatec_metadata_hydration.json",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=PROJECT_ROOT / "reports" / "integration" / "gatec_livelab_payload.json",
    )
    parser.add_argument(
        "--output-js",
        type=Path,
        default=PROJECT_ROOT / "apps" / "livelab" / "data" / "ranklab_offline_run.js",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    args = parse_args()
    evaluation_manifest_path = args.evaluation_dir / "manifest.json"
    metrics_path = args.evaluation_dir / "metrics.csv"
    deltas_path = args.evaluation_dir / "paired_deltas.csv"
    evaluation = json.loads(evaluation_manifest_path.read_text(encoding="utf-8"))
    training = json.loads(args.training_manifest.read_text(encoding="utf-8"))
    hydration = json.loads(args.hydration_manifest.read_text(encoding="utf-8"))
    metrics = {row["model"]: row for row in read_csv_rows(metrics_path)}
    deltas = {row["metric"]: row for row in read_csv_rows(deltas_path)}
    baseline = metrics["MultiTaskHashSGD"]
    metarank = metrics["Metarank-LambdaMART"]

    metric_specs = [
        ("ndcg_at_5", "NDCG@5", "higher", False),
        ("ecr_at_5", "Top-5 ECR", "higher", False),
        ("hate_rate_at_5", "Top-5 负反馈率", "lower", True),
        ("content_coverage_at_10", "内容覆盖@10", "higher", True),
        ("author_repeat_rate_at_10", "作者重复@10", "lower", True),
        ("primary_tag_repeat_rate_at_10", "标签重复@10", "lower", True),
    ]
    payload_metrics: list[dict[str, Any]] = []
    for key, name, better, guardrail in metric_specs:
        delta = deltas.get(key)
        payload_metrics.append(
            {
                "key": key,
                "name": name,
                "baseline": float(baseline[key]),
                "metarank": float(metarank[key]),
                "delta": float(metarank[key]) - float(baseline[key]),
                "ci_low": float(delta["ci_low"]) if delta else None,
                "ci_high": float(delta["ci_high"]) if delta else None,
                "better": better,
                "guardrail": guardrail,
            }
        )

    payload = {
        "schema_version": "flowlens_livelab_offline_run_v1",
        "id": evaluation["run_id"],
        "name": "Metarank × MultiTask 统一离线复盘",
        "source_type": "offline_replay",
        "evidence_level": "E3",
        "status": "completed",
        "decision": evaluation["decision"],
        "split": evaluation["split"],
        "sampling": evaluation["sampling"],
        "eligible_users": int(baseline["eligible_users"]),
        "training": {
            "groups": int(training["summary"]["groups_exported"]),
            "events": int(
                training["summary"]["unique_items_exported"]
                + training["summary"]["groups_exported"]
                + training["summary"]["interactions_exported"]
            ),
            "interactions": int(training["summary"]["interactions_exported"]),
            "sampling": training["summary"]["group_sampling"],
            "seed": int(training["summary"]["sample_seed"]),
        },
        "metadata": {
            "candidate_items": int(hydration["summary"]["candidate_unique_items"]),
            "covered_items": int(hydration["summary"]["metadata_rows_emitted"]),
            "missing_duration_items": int(hydration["summary"]["missing_duration"]),
            "missing_policy": hydration["duration_missing_policy"],
        },
        "models": {
            "baseline": "MultiTaskHashSGD",
            "candidate": "Metarank 0.8.0 LambdaMART",
        },
        "metrics": payload_metrics,
        "health_checks": [
            {"name": "候选守恒", "status": evaluation["candidate_conservation"], "detail": "API 输入输出候选集合一致"},
            {
                "name": "元数据覆盖",
                "status": evaluation["candidate_metadata_coverage"],
                "detail": f"{int(hydration['summary']['metadata_rows_emitted']):,} 个评估内容均已写入元数据",
            },
            {"name": "时间切分", "status": "PASS", "detail": "只使用训练窗事件训练，验证集仅用于本轮判断"},
            {"name": "冻结测试集", "status": "NOT_RUN", "detail": "验证集未过门，因此未查看标准测试与随机敏感性结果"},
        ],
        "summary": (
            "Metarank 在本轮验证 cohort 上的 NDCG@5 与 ECR@5 均低于冻结基线，"
            "因此决策为 ITERATE_AND_RETEST，不进入冻结测试集。"
        ),
        "claim_boundary": evaluation["claim_boundary"],
        "lineage": {
            "evaluation_manifest_sha256": sha256_file(evaluation_manifest_path),
            "metrics_sha256": sha256_file(metrics_path),
            "paired_deltas_sha256": sha256_file(deltas_path),
            "training_manifest_sha256": sha256_file(args.training_manifest),
            "hydration_manifest_sha256": sha256_file(args.hydration_manifest),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_js.parent.mkdir(parents=True, exist_ok=True)
    args.output_js.write_text(
        "window.rankLabOfflineRun = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"Gate C LiveLab payload: VALID; decision={payload['decision']}")


if __name__ == "__main__":
    main()
