#!/usr/bin/env python3
"""Evaluate Metarank and the frozen FlowLens baseline on one shared offline cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from metarank_contract import PROJECT_ROOT, sha256_file, stable_hash


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "gate4_strategies.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--rankings", type=Path, required=True)
    parser.add_argument("--rank-manifest", type=Path, required=True)
    parser.add_argument("--hydration-manifest", type=Path, required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--random-seed", type=int, default=20261009)
    return parser.parse_args()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return resolved.name


def prepare_pairs(candidates: pd.DataFrame, rankings: pd.DataFrame) -> pd.DataFrame:
    required_candidates = {
        "user_id",
        "video_id",
        "long_view",
        "is_click",
        "is_hate",
        "multitask_score",
        "author_id",
        "tag",
    }
    required_rankings = {"user_id", "video_id", "metarank_rank", "metarank_score"}
    missing_candidates = required_candidates - set(candidates.columns)
    missing_rankings = required_rankings - set(rankings.columns)
    if missing_candidates:
        raise ValueError(f"Candidate file is missing columns: {sorted(missing_candidates)}")
    if missing_rankings:
        raise ValueError(f"Rank results are missing columns: {sorted(missing_rankings)}")
    if candidates.duplicated(["user_id", "video_id"]).any():
        raise ValueError("Candidate file contains duplicate user-video pairs")
    if rankings.duplicated(["user_id", "video_id"]).any():
        raise ValueError("Rank results contain duplicate user-video pairs")

    selected_users = rankings["user_id"].drop_duplicates()
    selected = candidates[candidates["user_id"].isin(selected_users)].copy()
    pairs = selected.merge(
        rankings[["user_id", "video_id", "metarank_rank", "metarank_score"]],
        on=["user_id", "video_id"],
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    unmatched = pairs["_merge"] != "both"
    if unmatched.any():
        counts = pairs.loc[unmatched, "_merge"].value_counts().to_dict()
        raise ValueError(f"Candidate conservation failed during evaluation: {counts}")
    pairs = pairs.drop(columns="_merge")
    pairs["primary_tag"] = pairs["tag"].fillna("UNKNOWN").astype(str).str.split(",").str[0]
    return pairs


def evaluate_order(
    pairs: pd.DataFrame,
    *,
    model: str,
    order_columns: list[str],
    ascending: list[bool],
    minimum_candidates: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    summary = pairs.groupby("user_id").agg(
        candidate_count=("video_id", "size"),
        positive_count=("long_view", "sum"),
    )
    eligible_users = summary.index[
        (summary["candidate_count"] >= minimum_candidates) & (summary["positive_count"] > 0)
    ]
    eligible = pairs[pairs["user_id"].isin(eligible_users)].copy()
    ranked = eligible.sort_values(
        ["user_id", *order_columns, "video_id"],
        ascending=[True, *ascending, True],
        kind="mergesort",
    )
    ranked["rank"] = ranked.groupby("user_id").cumcount() + 1
    top10 = ranked[ranked["rank"] <= 10].copy()
    top5 = ranked[ranked["rank"] <= 5].copy()
    top10["author_repeat"] = top10.duplicated(["user_id", "author_id"])
    top10["primary_tag_repeat"] = top10.duplicated(["user_id", "primary_tag"])

    per_user = summary.loc[eligible_users].copy()
    for k in [5, 10]:
        selected = ranked[ranked["rank"] <= k].copy()
        selected["gain"] = selected["long_view"] / np.log2(selected["rank"] + 1.0)
        dcg = selected.groupby("user_id")["gain"].sum()
        ideal = per_user["positive_count"].clip(upper=k).astype(int).map(
            lambda count: float(np.sum(1.0 / np.log2(np.arange(2, count + 2))))
        )
        per_user[f"ndcg_at_{k}"] = dcg.reindex(per_user.index, fill_value=0.0) / ideal
        hits = selected.groupby("user_id")["long_view"].sum()
        per_user[f"recall_at_{k}"] = hits.reindex(per_user.index, fill_value=0.0) / per_user["positive_count"]
        for label in ["long_view", "is_click", "is_hate"]:
            per_user[f"{label}_rate_at_{k}"] = (
                selected.groupby("user_id")[label].mean().reindex(per_user.index, fill_value=0.0)
            )
    per_user["author_repeat_rate_at_10"] = (
        top10.groupby("user_id")["author_repeat"].mean().reindex(per_user.index, fill_value=0.0)
    )
    per_user["primary_tag_repeat_rate_at_10"] = (
        top10.groupby("user_id")["primary_tag_repeat"].mean().reindex(per_user.index, fill_value=0.0)
    )
    author_shares = top10["author_id"].value_counts(normalize=True)
    metrics = {
        "model": model,
        "candidate_pairs": int(len(pairs)),
        "candidate_users": int(pairs["user_id"].nunique()),
        "eligible_users": int(len(per_user)),
        "ndcg_at_5": float(per_user["ndcg_at_5"].mean()),
        "ndcg_at_10": float(per_user["ndcg_at_10"].mean()),
        "recall_at_5": float(per_user["recall_at_5"].mean()),
        "ecr_at_5": float(per_user["long_view_rate_at_5"].mean()),
        "ctr_at_5": float(per_user["is_click_rate_at_5"].mean()),
        "hate_rate_at_5": float(per_user["is_hate_rate_at_5"].mean()),
        "content_coverage_at_10": float(top10["video_id"].nunique() / max(1, eligible["video_id"].nunique())),
        "author_coverage_at_10": float(top10["author_id"].nunique() / max(1, eligible["author_id"].nunique())),
        "tag_coverage_at_10": float(top10["primary_tag"].nunique() / max(1, eligible["primary_tag"].nunique())),
        "author_hhi_at_10": float((author_shares**2).sum()),
        "author_repeat_rate_at_10": float(per_user["author_repeat_rate_at_10"].mean()),
        "primary_tag_repeat_rate_at_10": float(per_user["primary_tag_repeat_rate_at_10"].mean()),
    }
    per_user = per_user.reset_index()
    per_user.insert(0, "model", model)
    return metrics, per_user


def paired_deltas(
    baseline_users: pd.DataFrame,
    metarank_users: pd.DataFrame,
    repetitions: int,
    seed: int,
) -> list[dict[str, Any]]:
    merged = baseline_users.merge(
        metarank_users,
        on="user_id",
        suffixes=("_baseline", "_metarank"),
        validate="one_to_one",
    )
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    mapping = {
        "ndcg_at_5": "ndcg_at_5",
        "ndcg_at_10": "ndcg_at_10",
        "recall_at_5": "recall_at_5",
        "ecr_at_5": "long_view_rate_at_5",
        "ctr_at_5": "is_click_rate_at_5",
        "hate_rate_at_5": "is_hate_rate_at_5",
        "author_repeat_rate_at_10": "author_repeat_rate_at_10",
        "primary_tag_repeat_rate_at_10": "primary_tag_repeat_rate_at_10",
    }
    for output_name, source_name in mapping.items():
        differences = (
            merged[f"{source_name}_metarank"].to_numpy(dtype="float64")
            - merged[f"{source_name}_baseline"].to_numpy(dtype="float64")
        )
        bootstrap = np.array(
            [rng.choice(differences, size=len(differences), replace=True).mean() for _ in range(repetitions)]
        )
        rows.append(
            {
                "metric": output_name,
                "metarank_minus_baseline": float(differences.mean()),
                "ci_low": float(np.quantile(bootstrap, 0.025)),
                "ci_high": float(np.quantile(bootstrap, 0.975)),
                "paired_users": int(len(differences)),
            }
        )
    return rows


def evaluate_models(
    candidates: pd.DataFrame,
    rankings: pd.DataFrame,
    *,
    minimum_candidates: int,
    bootstrap_repetitions: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pairs = prepare_pairs(candidates, rankings)
    baseline_metrics, baseline_users = evaluate_order(
        pairs,
        model="MultiTaskHashSGD",
        order_columns=["multitask_score"],
        ascending=[False],
        minimum_candidates=minimum_candidates,
    )
    metarank_metrics, metarank_users = evaluate_order(
        pairs,
        model="Metarank-LambdaMART",
        order_columns=["metarank_rank"],
        ascending=[True],
        minimum_candidates=minimum_candidates,
    )
    deltas = paired_deltas(
        baseline_users,
        metarank_users,
        repetitions=bootstrap_repetitions,
        seed=seed,
    )
    metrics = pd.DataFrame([baseline_metrics, metarank_metrics])
    users = pd.concat([baseline_users, metarank_users], ignore_index=True)
    return metrics, pd.DataFrame(deltas), users


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    rank_manifest = json.loads(args.rank_manifest.read_text(encoding="utf-8"))
    hydration_manifest = json.loads(args.hydration_manifest.read_text(encoding="utf-8"))
    if rank_manifest.get("status") != "VALID":
        raise ValueError("Rank manifest must be VALID")
    if hydration_manifest.get("status") != "VALID":
        raise ValueError("Hydration manifest must be VALID")
    if hydration_manifest.get("candidate_metadata_coverage") != "PASS":
        raise ValueError("Candidate metadata coverage must pass")
    candidates = pd.read_csv(args.candidates, low_memory=False)
    rankings = pd.read_csv(args.rankings, low_memory=False)
    metrics, deltas, users = evaluate_models(
        candidates,
        rankings,
        minimum_candidates=int(config["evaluation"]["minimum_candidates_per_user"]),
        bootstrap_repetitions=int(config["evaluation"]["bootstrap_repetitions"]),
        seed=args.random_seed,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "metrics.csv"
    deltas_path = args.output_dir / "paired_deltas.csv"
    users_path = args.output_dir / "user_metrics.csv"
    metrics.to_csv(metrics_path, index=False)
    deltas.to_csv(deltas_path, index=False)
    users.to_csv(users_path, index=False)

    ndcg = deltas.set_index("metric").loc["ndcg_at_5"]
    ecr = deltas.set_index("metric").loc["ecr_at_5"]
    decision = (
        "READY_FOR_FROZEN_TEST"
        if float(ndcg["ci_low"]) > 0 and float(ecr["ci_low"]) >= 0
        else "ITERATE_AND_RETEST"
    )
    run_id = "gatec-eval-" + stable_hash(
        sha256_file(args.candidates),
        sha256_file(args.rankings),
        sha256_file(args.config),
        args.split,
        args.random_seed,
    )
    manifest = {
        "run_id": run_id,
        "status": "VALID",
        "evidence_level": "E3",
        "split": args.split,
        "decision": decision,
        "sampling": {
            "method": rank_manifest.get("request_sampling", "unknown"),
            "seed": rank_manifest.get("sample_seed"),
            "request_count": rank_manifest["request_count"],
            "candidate_count": rank_manifest["candidate_count"],
        },
        "inputs": {
            "candidates": display_path(args.candidates),
            "candidates_sha256": sha256_file(args.candidates),
            "rankings": display_path(args.rankings),
            "rankings_sha256": sha256_file(args.rankings),
            "rank_manifest": display_path(args.rank_manifest),
            "rank_manifest_sha256": sha256_file(args.rank_manifest),
            "hydration_manifest": display_path(args.hydration_manifest),
            "hydration_manifest_sha256": sha256_file(args.hydration_manifest),
        },
        "outputs": {
            "metrics": display_path(metrics_path),
            "metrics_sha256": sha256_file(metrics_path),
            "paired_deltas": display_path(deltas_path),
            "paired_deltas_sha256": sha256_file(deltas_path),
            "user_metrics": display_path(users_path),
            "user_metrics_sha256": sha256_file(users_path),
        },
        "candidate_conservation": "PASS",
        "candidate_metadata_coverage": "PASS",
        "bootstrap_repetitions": int(config["evaluation"]["bootstrap_repetitions"]),
        "claim_boundary": (
            "This is a paired E3 offline replay on a deterministic logged-exposure cohort. "
            "It is not a randomized online experiment and does not establish causal or business lift."
        ),
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Gate C evaluation: VALID; split={args.split}, decision={decision}, "
        f"users={int(metrics.iloc[0]['eligible_users'])}"
    )


if __name__ == "__main__":
    main()
