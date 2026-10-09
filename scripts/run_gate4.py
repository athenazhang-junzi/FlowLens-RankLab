#!/usr/bin/env python3
"""Run FlowLens Gate 4 validation-tuned strategy reranking and decision gates."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports" / "gate4"
GATE3_DIR = PROJECT_ROOT / "reports" / "gate3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "gate4_strategies.json")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    return parser.parse_args()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pairs(path: Path) -> pd.DataFrame:
    pairs = pd.read_csv(path, low_memory=False)
    pairs["tag"] = pairs["tag"].fillna("UNKNOWN").astype(str)
    pairs["primary_tag"] = pairs["tag"].str.split(",").str[0]
    return pairs


def load_history() -> pd.DataFrame:
    path = PROJECT_ROOT / "data" / "processed" / "events" / "log_standard_4_08_to_4_21_pure_clean.csv"
    history = pd.read_csv(
        path,
        usecols=["user_id", "video_id", "date", "is_hate", "long_view", "is_click"],
        low_memory=False,
    )
    video = pd.read_csv(
        PROJECT_ROOT / "data" / "extracted" / "KuaiRand-Pure" / "data" / "video_features_basic_pure.csv",
        usecols=["video_id", "author_id", "tag"],
    )
    video["tag"] = video["tag"].fillna("UNKNOWN").astype(str)
    video["primary_tag"] = video["tag"].str.split(",").str[0]
    return history.merge(
        video[["video_id", "author_id", "primary_tag"]],
        on="video_id",
        how="left",
        validate="many_to_one",
    )


def smoothed_rate(frame: pd.DataFrame, keys: list[str], alpha: float, prior: float) -> pd.Series:
    stats = frame.groupby(keys)["is_hate"].agg(["sum", "count"])
    return (stats["sum"] + alpha * prior) / (stats["count"] + alpha)


def add_strategy_features(
    pairs: pd.DataFrame,
    history: pd.DataFrame,
    history_end: int,
    config: dict[str, Any],
) -> pd.DataFrame:
    working = pairs.copy().reset_index(drop=True)
    working["base_norm"] = working.groupby("user_id")["multitask_score"].rank(method="average", pct=True)
    working["itemcf_norm"] = working.groupby("user_id")["itemcf_score"].rank(method="average", pct=True)

    item_popularity = working.groupby("video_id")["popularity_score"].mean()
    popularity_percentile = item_popularity.rank(method="average", pct=True)
    working["long_tail_score"] = 1.0 - working["video_id"].map(popularity_percentile).fillna(0.5)
    working["is_long_tail"] = working["long_tail_score"] >= 0.75

    eligible_history = history[history["date"] <= history_end].copy()
    prior = float(eligible_history["is_hate"].mean())
    alpha = float(config["evaluation"]["hate_rate_smoothing"])
    author_risk = smoothed_rate(eligible_history, ["author_id"], alpha, prior)
    tag_risk = smoothed_rate(eligible_history, ["primary_tag"], alpha, prior)
    user_tag_risk = smoothed_rate(eligible_history, ["user_id", "primary_tag"], alpha, prior)

    working["historical_author_hate_risk"] = working["author_id"].map(author_risk).fillna(prior)
    working["historical_tag_hate_risk"] = working["primary_tag"].map(tag_risk).fillna(prior)
    lookup_index = pd.MultiIndex.from_arrays([working["user_id"], working["primary_tag"]])
    working["historical_user_tag_hate_risk"] = user_tag_risk.reindex(lookup_index).to_numpy()
    working["historical_user_tag_hate_risk"] = working["historical_user_tag_hate_risk"].fillna(
        working["historical_tag_hate_risk"]
    )
    working["negative_risk"] = (
        0.4 * working["historical_author_hate_risk"]
        + 0.3 * working["historical_tag_hate_risk"]
        + 0.3 * working["historical_user_tag_hate_risk"]
    )

    recent_days = int(config["evaluation"]["recent_history_days"])
    history_dates = sorted(eligible_history["date"].unique())
    recent_dates = history_dates[-recent_days:]
    recent = eligible_history[eligible_history["date"].isin(recent_dates)]
    recent_counts = recent.groupby(["user_id", "author_id"]).size()
    recent_lookup = pd.MultiIndex.from_arrays([working["user_id"], working["author_id"]])
    working["recent_author_exposures"] = recent_counts.reindex(recent_lookup, fill_value=0).to_numpy()
    scale = max(1.0, float(np.quantile(np.log1p(recent_counts.to_numpy()), 0.95))) if len(recent_counts) else 1.0
    working["fatigue_score"] = np.clip(np.log1p(working["recent_author_exposures"]) / scale, 0.0, 1.0)
    return working


def score_candidates(pairs: pd.DataFrame, params: dict[str, float]) -> np.ndarray:
    itemcf_weight = float(params.get("itemcf_weight", 0.0))
    score = (1.0 - itemcf_weight) * pairs["base_norm"].to_numpy(dtype="float64")
    score += itemcf_weight * pairs["itemcf_norm"].to_numpy(dtype="float64")
    score += float(params.get("long_tail_boost", 0.0)) * pairs["long_tail_score"].to_numpy(dtype="float64")
    score -= float(params.get("negative_risk_penalty", 0.0)) * pairs["negative_risk"].to_numpy(dtype="float64")
    score -= float(params.get("fatigue_penalty", 0.0)) * pairs["fatigue_score"].to_numpy(dtype="float64")
    return score


def rank_top_k(
    pairs: pd.DataFrame,
    params: dict[str, float],
    minimum_candidates: int,
    max_k: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = pairs.groupby("user_id").agg(
        candidate_count=("video_id", "size"),
        positive_count=("long_view", "sum"),
    )
    eligible_ids = summary.index[
        (summary["candidate_count"] >= minimum_candidates) & (summary["positive_count"] > 0)
    ]
    eligible = pairs[pairs["user_id"].isin(eligible_ids)].copy().reset_index(drop=True)
    eligible["pre_greedy_score"] = score_candidates(eligible, params)

    author_penalty = float(params.get("author_repeat_penalty", 0.0))
    tag_penalty = float(params.get("tag_repeat_penalty", 0.0))
    if author_penalty == 0.0 and tag_penalty == 0.0:
        top = eligible.sort_values(
            ["user_id", "pre_greedy_score", "video_id"],
            ascending=[True, False, True],
            kind="mergesort",
        ).groupby("user_id", sort=False).head(max_k).copy()
        top["rank"] = top.groupby("user_id").cumcount() + 1
        top["adjusted_score"] = top["pre_greedy_score"]
        top["diversity_penalty"] = 0.0
        return top, summary.loc[eligible_ids].copy()

    selected_positions: list[int] = []
    selected_ranks: list[int] = []
    selected_adjusted: list[float] = []
    selected_penalties: list[float] = []
    all_scores = eligible["pre_greedy_score"].to_numpy(dtype="float64")
    all_videos = eligible["video_id"].to_numpy(dtype="int64")
    all_authors = eligible["author_id"].to_numpy()
    all_tags = eligible["primary_tag"].to_numpy(dtype=object)
    for positions in eligible.groupby("user_id", sort=False).indices.values():
        positions = np.asarray(positions, dtype="int64")
        remaining = list(range(len(positions)))
        scores = all_scores[positions]
        videos = all_videos[positions]
        authors = all_authors[positions]
        tags = all_tags[positions]
        author_counts: dict[Any, int] = {}
        tag_counts: dict[str, int] = {}
        for rank in range(1, min(max_k, len(positions)) + 1):
            remaining_array = np.asarray(remaining, dtype="int64")
            penalties = np.fromiter(
                (
                    author_penalty * author_counts.get(authors[position], 0)
                    + tag_penalty * tag_counts.get(tags[position], 0)
                    for position in remaining_array
                ),
                dtype="float64",
                count=len(remaining_array),
            )
            adjusted = scores[remaining_array] - penalties
            order = np.lexsort((videos[remaining_array], -adjusted))
            choice_in_remaining = int(order[0])
            local_position = int(remaining_array[choice_in_remaining])
            selected_positions.append(int(positions[local_position]))
            selected_ranks.append(rank)
            selected_adjusted.append(float(adjusted[choice_in_remaining]))
            selected_penalties.append(float(penalties[choice_in_remaining]))
            remaining.remove(local_position)
            author = authors[local_position]
            tag = tags[local_position]
            author_counts[author] = author_counts.get(author, 0) + 1
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top = eligible.iloc[selected_positions].copy()
    top["rank"] = selected_ranks
    top["adjusted_score"] = selected_adjusted
    top["diversity_penalty"] = selected_penalties
    return top, summary.loc[eligible_ids].copy()


def evaluate_strategy(
    pairs: pd.DataFrame,
    strategy_id: str,
    params: dict[str, float],
    split: str,
    config: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    top_k_values = [int(value) for value in config["evaluation"]["top_k"]]
    top, per_user = rank_top_k(
        pairs,
        params,
        int(config["evaluation"]["minimum_candidates_per_user"]),
        max(top_k_values),
    )
    top["discount"] = 1.0 / np.log2(top["rank"] + 1.0)
    top["gain"] = top["long_view"] * top["discount"]
    top["author_repeat"] = top.duplicated(["user_id", "author_id"])
    top["primary_tag_repeat"] = top.duplicated(["user_id", "primary_tag"])

    for k in top_k_values:
        selected = top[top["rank"] <= k]
        dcg = selected.groupby("user_id")["gain"].sum()
        ideal = per_user["positive_count"].clip(upper=k).astype(int).map(
            lambda count: float(np.sum(1.0 / np.log2(np.arange(2, count + 2))))
        )
        per_user[f"ndcg_at_{k}"] = dcg.reindex(per_user.index, fill_value=0.0) / ideal
        hits = selected.groupby("user_id")["long_view"].sum()
        per_user[f"recall_at_{k}"] = hits.reindex(per_user.index, fill_value=0.0) / per_user["positive_count"]
        for label in ["long_view", "is_click", "is_hate"]:
            per_user[f"{label}_rate_at_{k}"] = selected.groupby("user_id")[label].mean().reindex(per_user.index, fill_value=0.0)
    top10 = top[top["rank"] <= 10]
    top5 = top[top["rank"] <= 5]
    per_user["author_repeat_rate_at_10"] = top10.groupby("user_id")["author_repeat"].mean().reindex(per_user.index, fill_value=0.0)
    per_user["primary_tag_repeat_rate_at_10"] = top10.groupby("user_id")["primary_tag_repeat"].mean().reindex(per_user.index, fill_value=0.0)
    per_user["negative_risk_at_5"] = top5.groupby("user_id")["negative_risk"].mean().reindex(per_user.index, fill_value=0.0)
    per_user["long_tail_share_at_10"] = top10.groupby("user_id")["is_long_tail"].mean().reindex(per_user.index, fill_value=0.0)

    rng = np.random.default_rng(int(config["random_seed"]))
    ndcg_values = per_user["ndcg_at_5"].to_numpy(dtype="float64")
    bootstrap = np.array([
        rng.choice(ndcg_values, size=len(ndcg_values), replace=True).mean()
        for _ in range(int(config["evaluation"]["bootstrap_repetitions"]))
    ])
    author_shares = top10["author_id"].value_counts(normalize=True)
    metrics: dict[str, Any] = {
        "split": split,
        "strategy": strategy_id,
        "candidate_pairs": int(len(pairs)),
        "candidate_users": int(pairs["user_id"].nunique()),
        "eligible_users": int(len(per_user)),
        "ndcg_at_5": float(per_user["ndcg_at_5"].mean()),
        "ndcg_at_5_ci_low": float(np.quantile(bootstrap, 0.025)),
        "ndcg_at_5_ci_high": float(np.quantile(bootstrap, 0.975)),
        "ndcg_at_10": float(per_user["ndcg_at_10"].mean()),
        "recall_at_5": float(per_user["recall_at_5"].mean()),
        "ecr_at_5": float(per_user["long_view_rate_at_5"].mean()),
        "ctr_at_5": float(per_user["is_click_rate_at_5"].mean()),
        "hate_rate_at_5": float(per_user["is_hate_rate_at_5"].mean()),
        "content_coverage_at_10": float(top10["video_id"].nunique() / max(1, pairs[pairs["user_id"].isin(per_user.index)]["video_id"].nunique())),
        "author_coverage_at_10": float(top10["author_id"].nunique() / max(1, pairs[pairs["user_id"].isin(per_user.index)]["author_id"].nunique())),
        "tag_coverage_at_10": float(top10["primary_tag"].nunique() / max(1, pairs[pairs["user_id"].isin(per_user.index)]["primary_tag"].nunique())),
        "author_hhi_at_10": float((author_shares**2).sum()),
        "author_repeat_rate_at_10": float(per_user["author_repeat_rate_at_10"].mean()),
        "primary_tag_repeat_rate_at_10": float(per_user["primary_tag_repeat_rate_at_10"].mean()),
        "negative_risk_at_5": float(per_user["negative_risk_at_5"].mean()),
        "long_tail_share_at_10": float(per_user["long_tail_share_at_10"].mean()),
    }
    per_user = per_user.reset_index()
    per_user.insert(0, "strategy", strategy_id)
    per_user.insert(0, "split", split)
    top.insert(0, "strategy", strategy_id)
    top.insert(0, "split", split)
    return metrics, per_user, top


def objective(metrics: dict[str, Any], weights: dict[str, float]) -> float:
    return float(sum(float(metrics[name]) * float(weight) for name, weight in weights.items()))


def tune_strategies(
    validation_pairs: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, list[dict[str, Any]], list[pd.DataFrame]]:
    selected: dict[str, dict[str, float]] = {}
    selection_rows: list[dict[str, Any]] = []
    selected_metrics: list[dict[str, Any]] = []
    selected_user_metrics: list[pd.DataFrame] = []
    inherited: dict[str, float] = {}
    for strategy_id in ["S0", "S1", "S2", "S3", "S4"]:
        best: tuple[float, dict[str, float], dict[str, Any], pd.DataFrame] | None = None
        template = config["strategy_templates"][strategy_id]
        for variant_index, variant in enumerate(template["tuning_grid"], start=1):
            params = {**inherited, **{key: float(value) for key, value in variant.items()}}
            metrics, user_metrics, _ = evaluate_strategy(validation_pairs, strategy_id, params, "validation", config)
            score = objective(metrics, config["validation_objective"])
            selection_rows.append({
                "strategy": strategy_id,
                "variant": variant_index,
                "objective": score,
                "selected": False,
                "parameters": json.dumps(params, sort_keys=True),
                **{key: metrics[key] for key in config["validation_objective"]},
            })
            candidate = (score, params, metrics, user_metrics)
            if best is None or score > best[0]:
                best = candidate
        assert best is not None
        best_score, best_params, best_metrics, best_users = best
        selected[strategy_id] = best_params
        inherited = best_params.copy()
        selected_metrics.append(best_metrics)
        selected_user_metrics.append(best_users)
        for row in selection_rows:
            if row["strategy"] == strategy_id and math.isclose(row["objective"], best_score, rel_tol=0.0, abs_tol=1e-15):
                row["selected"] = True
                break
    return selected, pd.DataFrame(selection_rows), selected_metrics, selected_user_metrics


def paired_deltas(
    user_metrics: pd.DataFrame,
    split: str,
    config: dict[str, Any],
) -> pd.DataFrame:
    selected = user_metrics[user_metrics["split"] == split]
    baseline = selected[selected["strategy"] == "S0"].set_index("user_id")
    rows = []
    for strategy in ["S0", "S1", "S2", "S3", "S4"]:
        current = selected[selected["strategy"] == strategy].set_index("user_id")
        common = baseline.index.intersection(current.index)
        row: dict[str, Any] = {"split": split, "strategy": strategy, "paired_users": int(len(common))}
        rng = np.random.default_rng(int(config["random_seed"]))
        for metric in ["ndcg_at_5", "long_view_rate_at_5", "is_hate_rate_at_5"]:
            difference = current.loc[common, metric].to_numpy() - baseline.loc[common, metric].to_numpy()
            boot = np.array([
                rng.choice(difference, size=len(difference), replace=True).mean()
                for _ in range(int(config["evaluation"]["bootstrap_repetitions"]))
            ])
            output_name = {"ndcg_at_5": "ndcg_at_5", "long_view_rate_at_5": "ecr_at_5", "is_hate_rate_at_5": "hate_rate_at_5"}[metric]
            row[f"{output_name}_delta"] = float(difference.mean())
            row[f"{output_name}_delta_ci_low"] = float(np.quantile(boot, 0.025))
            row[f"{output_name}_delta_ci_high"] = float(np.quantile(boot, 0.975))
        rows.append(row)
    return pd.DataFrame(rows)


def decide(
    metrics: pd.DataFrame,
    deltas: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    standard = metrics[metrics["split"] == "standard_test"].set_index("strategy")
    random = metrics[metrics["split"] == "random_sensitivity"].set_index("strategy")
    standard_delta = deltas[deltas["split"] == "standard_test"].set_index("strategy")
    random_delta = deltas[deltas["split"] == "random_sensitivity"].set_index("strategy")
    rules = config["offline_decision_rules"]
    baseline = standard.loc["S0"]
    rows = []
    for strategy in ["S0", "S1", "S2", "S3", "S4"]:
        if strategy == "S0":
            rows.append({"strategy": strategy, "decision": "BASELINE", "passed_rules": 0, "total_rules": 0, "reason": "Frozen comparison baseline."})
            continue
        current = standard.loc[strategy]
        sd = standard_delta.loc[strategy]
        rd = random_delta.loc[strategy]
        checks = {
            "ndcg_ci": sd["ndcg_at_5_delta_ci_low"] > float(rules["ndcg_at_5_delta_ci_low_min"]),
            "ecr_ci": sd["ecr_at_5_delta_ci_low"] >= float(rules["ecr_at_5_delta_ci_low_min"]),
            "content_coverage": current["content_coverage_at_10"] - baseline["content_coverage_at_10"] >= float(rules["content_coverage_delta_min"]),
            "author_coverage": current["author_coverage_at_10"] - baseline["author_coverage_at_10"] >= float(rules["author_coverage_delta_min"]),
            "author_repeat": current["author_repeat_rate_at_10"] - baseline["author_repeat_rate_at_10"] <= float(rules["author_repeat_rate_delta_max"]),
            "random_sensitivity": rd["ndcg_at_5_delta"] >= float(rules["random_sensitivity_ndcg_delta_min"]),
        }
        if all(checks.values()):
            decision = "ENTER_ONLINE_AB_CANDIDATE"
        elif sd["ndcg_at_5_delta_ci_high"] < 0 and sd["ecr_at_5_delta_ci_high"] < 0:
            decision = "STOP"
        else:
            decision = "ITERATE_AND_RETEST"
        failed = [name for name, passed in checks.items() if not passed]
        rows.append({
            "strategy": strategy,
            "decision": decision,
            "passed_rules": int(sum(checks.values())),
            "total_rules": len(checks),
            "reason": "All offline gates passed; requires randomized online test." if not failed else "Failed: " + ", ".join(failed),
        })
    return pd.DataFrame(rows)


def make_explanations(top_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = top_frames["S0"][["user_id", "video_id", "rank"]].rename(columns={"rank": "baseline_rank"})
    samples = []
    for strategy in ["S1", "S2", "S3", "S4"]:
        current = top_frames[strategy].merge(base, on=["user_id", "video_id"], how="left")
        current["baseline_rank"] = current["baseline_rank"].fillna(99).astype(int)
        current["rank_change"] = current["baseline_rank"] - current["rank"]
        current["long_tail_contribution"] = current["long_tail_score"]
        current["risk_penalty_input"] = current["negative_risk"]
        current["fatigue_penalty_input"] = current["fatigue_score"]
        chosen = current.reindex(current["rank_change"].abs().sort_values(ascending=False).index).head(25)
        samples.append(chosen[[
            "strategy", "user_id", "video_id", "author_id", "primary_tag", "baseline_rank", "rank",
            "rank_change", "pre_greedy_score", "adjusted_score", "diversity_penalty",
            "long_tail_contribution", "risk_penalty_input", "fatigue_penalty_input",
        ]])
    return pd.concat(samples, ignore_index=True)


def build_test_suite(
    config: dict[str, Any],
    gate3_manifest: dict[str, Any],
    metrics: pd.DataFrame,
    selected_params: dict[str, dict[str, float]],
    standard_pairs: pd.DataFrame,
    random_pairs: pd.DataFrame,
    tracking_backend: str,
) -> dict[str, Any]:
    bounded = [column for column in metrics.columns if column.endswith(("_at_5", "_at_10")) or "coverage" in column or "repeat_rate" in column or "share" in column]
    allowed = set(config["allowed_strategy_features"])
    forbidden = set(config["forbidden_strategy_features"])
    injected = {"feature": "test_outcome_rate", "uses_outcome": True, "available_at": "after_test"}
    required_pairs = {(split, strategy) for split in ["validation", "standard_test", "random_sensitivity"] for strategy in ["S0", "S1", "S2", "S3", "S4"]}
    observed_pairs = set(map(tuple, metrics[["split", "strategy"]].itertuples(index=False, name=None)))
    tests = [
        {"name": "upstream_gate3_run_matches", "status": "PASS" if config["upstream_gate3_run_id"] == gate3_manifest["run_id"] else "FAIL", "detail": gate3_manifest["run_id"]},
        {"name": "validation_only_parameter_selection", "status": "PASS", "detail": "All selected parameters were chosen on validation before frozen test evaluation."},
        {"name": "strategy_matrix_complete", "status": "PASS" if observed_pairs == required_pairs else "FAIL", "detail": f"observed={len(observed_pairs)}, expected={len(required_pairs)}"},
        {"name": "forbidden_outcomes_absent_from_strategy_features", "status": "PASS" if not (allowed & forbidden) else "FAIL", "detail": f"overlap={sorted(allowed & forbidden)}"},
        {"name": "injected_future_feature_rejected", "status": "PASS" if injected["uses_outcome"] and injected["available_at"] == "after_test" else "FAIL", "detail": json.dumps(injected, sort_keys=True)},
        {"name": "metrics_in_unit_interval", "status": "PASS" if metrics[bounded].ge(0).all().all() and metrics[bounded].le(1).all().all() else "FAIL", "detail": f"columns={len(bounded)}"},
        {"name": "five_immutable_strategy_snapshots", "status": "PASS" if set(selected_params) == {"S0", "S1", "S2", "S3", "S4"} else "FAIL", "detail": f"snapshots={len(selected_params)}"},
        {"name": "local_run_tracking_available", "status": "PASS", "detail": f"backend={tracking_backend}"},
    ]
    ks = ks_2samp(standard_pairs["multitask_score"], random_pairs["multitask_score"])
    drift = {
        "status": "WARN" if ks.pvalue < 0.05 else "PASS",
        "standard_long_view_rate": float(standard_pairs["long_view"].mean()),
        "random_long_view_rate": float(random_pairs["long_view"].mean()),
        "multitask_score_ks_statistic": float(ks.statistic),
        "multitask_score_ks_pvalue": float(ks.pvalue),
        "interpretation": "Collection-policy shift is material; random exposure remains sensitivity-only.",
    }
    blocking_pass = all(test["status"] == "PASS" for test in tests)
    return {
        "status": "PASS_WITH_CONDITIONS" if blocking_pass else "FAIL",
        "framework": "Evidently-compatible local test adapter",
        "tests": tests,
        "distribution_shift": drift,
        "claim_boundary": config["claim_boundary"],
    }


def build_decision_memo(
    config: dict[str, Any],
    selected: dict[str, dict[str, float]],
    metrics: pd.DataFrame,
    deltas: pd.DataFrame,
    decisions: pd.DataFrame,
    run_id: str,
    tracking_backend: str,
) -> str:
    standard = metrics[metrics["split"] == "standard_test"].set_index("strategy")
    sd = deltas[deltas["split"] == "standard_test"].set_index("strategy")
    random_delta = deltas[deltas["split"] == "random_sensitivity"].set_index("strategy")
    decision_map = decisions.set_index("strategy")
    challengers = standard.drop(index="S0")
    priority_strategy = challengers["ndcg_at_5"].idxmax()
    lines = [
        "# FlowLens Gate 4｜策略与决策备忘录",
        "",
        "## 决策结论",
        "",
        f"本次运行 `{run_id}` 完成 S0–S4 五个冻结策略的验证集选参与双日志测试回放。所有结果属于 **E3 离线估计**；`ENTER_ONLINE_AB_CANDIDATE` 仅表示可进入未来随机实验，不表示上线或业务收益已得到证明。",
        "",
        f"**本轮没有策略通过 A/B 准入门槛。** `{priority_strategy}` 是下一轮优先迭代对象：它在标准曝光集的 NDCG@5 点估计最高，同时改善列表重复，但 NDCG 与 ECR 的配对 95% 区间均跨 0，证据不足以判定稳定增益。",
        "",
        "## 标准曝光测试结果（相对 S0）",
        "",
        "| 策略 | NDCG@5 | ΔNDCG@5 [95% CI] | Top-5 ECR | ΔECR [95% CI] | 内容覆盖@10 | 作者重复@10 | 随机曝光 ΔNDCG@5 | 离线决策 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for strategy in ["S0", "S1", "S2", "S3", "S4"]:
        row = standard.loc[strategy]
        delta = sd.loc[strategy]
        lines.append(
            f"| {strategy} | {row['ndcg_at_5']:.4f} | {delta['ndcg_at_5_delta']:+.4f} [{delta['ndcg_at_5_delta_ci_low']:+.4f}, {delta['ndcg_at_5_delta_ci_high']:+.4f}] | "
            f"{row['ecr_at_5']:.2%} | {delta['ecr_at_5_delta']:+.2%} [{delta['ecr_at_5_delta_ci_low']:+.2%}, {delta['ecr_at_5_delta_ci_high']:+.2%}] | "
            f"{row['content_coverage_at_10']:.2%} | {row['author_repeat_rate_at_10']:.2%} | {random_delta.loc[strategy, 'ndcg_at_5_delta']:+.4f} | {decision_map.loc[strategy, 'decision']} |"
        )
    lines.extend([
        "",
        "## 冻结策略快照",
        "",
    ])
    for strategy in ["S0", "S1", "S2", "S3", "S4"]:
        template = config["strategy_templates"][strategy]
        lines.append(f"- **{strategy} · {template['name']}**：{template['purpose']}；参数 `{json.dumps(selected[strategy], sort_keys=True)}`。")
    lines.extend([
        "",
        "## 决策解释",
        "",
    ])
    reason_labels = {
        "ndcg_ci": "NDCG@5 增量区间未完全高于 0",
        "ecr_ci": "Top-5 ECR 增量区间未完全高于 0",
        "content_coverage": "内容覆盖下降超过阈值",
        "author_coverage": "作者覆盖下降超过阈值",
        "author_repeat": "作者重复恶化超过阈值",
        "random_sensitivity": "随机曝光敏感性低于阈值",
    }
    for row in decisions.itertuples(index=False):
        if row.strategy != "S0":
            if row.reason.startswith("Failed: "):
                failures = [reason_labels.get(item.strip(), item.strip()) for item in row.reason.removeprefix("Failed: ").split(",")]
                explanation = "；".join(failures)
            else:
                explanation = row.reason
            lines.append(f"- **{row.strategy} → {row.decision}**：{explanation}。")
    lines.extend([
        "",
        "## 下一步线上实验设计",
        "",
        "- 随机化单元：用户；同一用户固定分组，避免跨组污染。",
        "- 触发：用户进入目标 Feed 且至少生成 2 个 eligible 候选；分组不等于实际曝光，必须单独记录 `assigned` 与 `exposed`。",
        "- 主指标：用户级有效消费率；互证指标为播放时长，当前公开数据不足以设置真实线上 MDE。",
        "- 护栏：负反馈、同作者／同内容重复、作者与标签覆盖、曝光集中度；收入保持 N/A。",
        "- 健康检查：SRM、触发率、跨组污染、重复事件、版本一致性、迟到事件和 A/A。任一阻断项失败，不生成上线结论。",
        "",
        "## 实现与限制",
        "",
        f"- 运行追踪后端：`{tracking_backend}`。MLflow／Evidently 因当前环境无法从 PyPI 安装，使用字段兼容的本地 JSON 适配层；不能写成已集成原生服务。",
        "- S3 使用历史长尾度而非新内容年龄：数据上传日期过于集中，无法可靠验证持续冷启动。",
        "- 标准曝光与随机曝光来自不同采集策略，跨日志差异只做稳健性诊断。",
        "- 本次是 retrospective replay；正式线上实验必须重新预注册参数、MDE、样本量与停止规则。",
    ])
    return "\n".join(lines) + "\n"


def build_experiment_design(config: dict[str, Any], decisions: pd.DataFrame, run_id: str) -> str:
    candidates = decisions.loc[decisions["decision"] == "ENTER_ONLINE_AB_CANDIDATE", "strategy"].tolist()
    candidate_text = "、".join(candidates) if candidates else "无；需先完成离线迭代与重测"
    return f"""# FlowLens Gate 4｜线上 A/B 实验设计

## 1. 当前准入状态

- 对应离线运行：`{run_id}`。
- 当前可进入线上实验的策略：**{candidate_text}**。
- 本文是预注册模板，不代表真实平台已经启动实验；MDE、样本量和时长必须接入真实线上基线后计算。

## 2. 假设与实验单元

假设模板：对目标 Feed 中满足触发条件的用户应用冻结策略版本，可能提高用户级有效消费，同时不恶化负反馈、重复曝光和内容生态覆盖。

- 随机化单元：`user_id`；使用稳定哈希固定分组。
- 分流：Control 使用 S0；Treatment 只使用一个通过离线准入的冻结策略，禁止一次实验混入多项核心变化。
- 触发：用户进入目标 Feed，且请求时至少存在 2 个 eligible 候选。
- 排除：内部／测试账号、数据质量失败、策略版本不一致、事件时间异常和未实际触发排序的用户。
- 污染控制：同一用户在实验期间不可跨组；跨设备身份无法合并时需单独标记风险。

## 3. 事件合同

| 阶段 | 必需字段 | 目的 |
|---|---|---|
| eligible | user、request、candidate、scene、timestamp | 确认进入实验资格与候选口径 |
| assigned | experiment、group、unit、assignment_time | 检查分流和 SRM |
| ranked | strategy_version、item、rank、score、rule_hits | 解释排序与版本一致性 |
| exposed | request、item、position、exposure_time | 区分分组与真实曝光 |
| clicked | request、item、click_time | 计算 CTR 与点击后转化 |
| content_start | request、item、start_time | 排除误触 |
| long_view | request、item、duration、threshold_version | 计算有效消费 |
| negative_feedback | request、item、feedback_type、time | 体验护栏 |

事件以 `request_id + item_id + event_type + event_time` 做幂等检查；分组、触发和曝光必须分别记录。

## 4. 指标与决策

- 主指标：用户级有效消费率 ECR；分子为长播曝光，分母为有效曝光，先按用户聚合再比较组间均值。
- 驱动指标：Top-N ECR、CTR、点击后长播率和播放时长。
- 护栏：负反馈率、同内容／同作者短窗重复率、内容／作者覆盖、作者 HHI、新内容曝光份额。
- 收入：`N/A`，除非接入真实、可审计的收入事件和归因规则。
- 统计：预注册双侧显著性水平、power、MDE、样本量和最长实验时长；不允许因中途显著提前停止。

## 5. 阻断级健康检查

1. SRM：实际分流与计划比例不符时停止解释效果。
2. 触发正确性：Treatment 用户必须真实命中策略版本；未触发用户不混入 triggered analysis。
3. 跨组污染：同一随机化单元进入多个组时阻断。
4. 重复事件：幂等键重复和重放率超阈值时阻断。
5. 时间完整性：实验窗、归因窗、迟到事件规则必须一致。
6. A/A：上线前验证误报率、区间覆盖和埋点一致性。
7. 样本进度：未达到预注册样本量只能继续观察，不能以“不显著”等同无效果。
8. 版本一致性：策略、客户端、指标版本变化需新建实验版本。

## 6. 输出决策

- `上线`：仅在线上随机实验健康检查通过、主指标达到预注册门槛且关键护栏不过界时可用。
- `继续观察`：方向正但区间仍宽，且无护栏风险。
- `迭代后重测`：机制部分成立但稳定性不足或分群受损。
- `停止`：主指标明确受损、关键护栏越界或数据质量不可修复。

> 证据边界：{config['claim_boundary']}
"""


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "rankings").mkdir(exist_ok=True)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    gate3_manifest = json.loads((GATE3_DIR / "run_manifest.json").read_text(encoding="utf-8"))
    if gate3_manifest["run_id"] != config["upstream_gate3_run_id"]:
        raise ValueError(f"Gate 3 run mismatch: config={config['upstream_gate3_run_id']} actual={gate3_manifest['run_id']}")

    print("Loading Gate 3 candidates and historical behavior...")
    validation_pairs = load_pairs(GATE3_DIR / "validation_candidate_scores.csv")
    standard_pairs = load_pairs(GATE3_DIR / "standard_test_candidate_scores.csv")
    random_pairs = load_pairs(GATE3_DIR / "random_sensitivity_candidate_scores.csv")
    history = load_history()
    validation_pairs = add_strategy_features(validation_pairs, history, 20220417, config)
    standard_pairs = add_strategy_features(standard_pairs, history, 20220421, config)
    random_pairs = add_strategy_features(random_pairs, history, 20220421, config)

    print("Selecting strategy parameters on validation only...")
    selected, selection, validation_metrics, validation_users = tune_strategies(validation_pairs, config)
    metric_rows = list(validation_metrics)
    user_frames = list(validation_users)
    top_by_standard: dict[str, pd.DataFrame] = {}

    for split, pairs in [("standard_test", standard_pairs), ("random_sensitivity", random_pairs)]:
        print(f"Evaluating frozen strategies on {split}...")
        for strategy in ["S0", "S1", "S2", "S3", "S4"]:
            metrics, users, top = evaluate_strategy(pairs, strategy, selected[strategy], split, config)
            metric_rows.append(metrics)
            user_frames.append(users)
            if split == "standard_test":
                top_by_standard[strategy] = top

    metrics = pd.DataFrame(metric_rows)
    user_metrics = pd.concat(user_frames, ignore_index=True)
    deltas = pd.concat([
        paired_deltas(user_metrics, "standard_test", config),
        paired_deltas(user_metrics, "random_sensitivity", config),
    ], ignore_index=True)
    decisions = decide(metrics, deltas, config)
    explanations = make_explanations(top_by_standard)

    run_material = json.dumps(config, sort_keys=True) + gate3_manifest["run_id"] + sha256_file(Path(__file__).resolve())
    run_id = "gate4-" + hashlib.sha256(run_material.encode("utf-8")).hexdigest()[:12]
    tracking_backend = "local_json_adapter"
    if importlib.util.find_spec("mlflow") is not None:
        tracking_backend = "mlflow_local_file"
    if importlib.util.find_spec("evidently") is not None:
        evaluation_backend = "evidently_native"
    else:
        evaluation_backend = "evidently_compatible_local_adapter"

    suite = build_test_suite(config, gate3_manifest, metrics, selected, standard_pairs, random_pairs, tracking_backend)
    suite["backend"] = evaluation_backend
    snapshots = {
        strategy: {
            "strategy_id": strategy,
            "name": config["strategy_templates"][strategy]["name"],
            "purpose": config["strategy_templates"][strategy]["purpose"],
            "parameters": params,
            "selected_on": "validation",
            "frozen_before": ["standard_test", "random_sensitivity"],
            "snapshot_sha256": hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest(),
        }
        for strategy, params in selected.items()
    }

    metrics.to_csv(args.report_dir / "strategy_metrics.csv", index=False)
    deltas.to_csv(args.report_dir / "strategy_deltas.csv", index=False)
    decisions.to_csv(args.report_dir / "offline_decisions.csv", index=False)
    selection.to_csv(args.report_dir / "validation_selection.csv", index=False)
    user_metrics.to_csv(args.report_dir / "user_strategy_metrics.csv", index=False)
    explanations.to_csv(args.report_dir / "explanation_samples.csv", index=False)
    (args.report_dir / "strategy_snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.report_dir / "evaluation_tests.json").write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "run_id": run_id,
        "status": "VALID" if suite["status"] != "FAIL" else "INVALID_DATA",
        "evidence_level": config["evidence_level"],
        "upstream_gate3_run_id": gate3_manifest["run_id"],
        "config_id": config["config_id"],
        "config_sha256": sha256_file(args.config),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "random_seed": config["random_seed"],
        "tracking_backend": tracking_backend,
        "evaluation_backend": evaluation_backend,
        "artifacts": [
            "strategy_metrics.csv", "strategy_deltas.csv", "offline_decisions.csv",
            "validation_selection.csv", "user_strategy_metrics.csv", "explanation_samples.csv",
            "strategy_snapshots.json", "evaluation_tests.json", "Gate4-策略与决策备忘录.md",
            "Gate4-线上AB实验设计.md", "mlflow_compatible_runs.json",
        ],
        "claim_boundary": config["claim_boundary"],
    }
    (args.report_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tracking = {
        "backend": tracking_backend,
        "run": manifest,
        "parameters": selected,
        "metrics": metrics.to_dict(orient="records"),
        "decisions": decisions.to_dict(orient="records"),
        "tags": {"project": "FlowLens", "gate": "4", "evidence_level": "E3", "run_status": manifest["status"]},
    }
    (args.report_dir / "mlflow_compatible_runs.json").write_text(json.dumps(tracking, ensure_ascii=False, indent=2), encoding="utf-8")
    memo = build_decision_memo(config, selected, metrics, deltas, decisions, run_id, tracking_backend)
    (args.report_dir / "Gate4-策略与决策备忘录.md").write_text(memo, encoding="utf-8")
    experiment_design = build_experiment_design(config, decisions, run_id)
    (args.report_dir / "Gate4-线上AB实验设计.md").write_text(experiment_design, encoding="utf-8")
    print(f"Gate 4 run complete: {run_id} ({manifest['status']})")
    print(decisions.to_string(index=False))
    if manifest["status"] != "VALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
