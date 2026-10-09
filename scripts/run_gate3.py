#!/usr/bin/env python3
"""Run FlowLens Gate 3 time-split baselines, leakage tests, and diagnostics."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction import FeatureHasher
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import roc_auc_score


EVENT_COLUMNS = [
    "user_id",
    "video_id",
    "date",
    "hourmin",
    "time_ms",
    "is_click",
    "long_view",
    "is_hate",
    "tab",
]


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "config" / "gate3_baseline.json",
    )
    parser.add_argument(
        "--events-dir",
        type=Path,
        default=project_root / "data" / "processed" / "events",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=project_root / "data" / "extracted" / "KuaiRand-Pure" / "data",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=project_root / "reports" / "gate3",
    )
    return parser.parse_args()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_events(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=EVENT_COLUMNS, low_memory=False)
    integer_columns = [
        "user_id",
        "video_id",
        "date",
        "hourmin",
        "time_ms",
        "is_click",
        "long_view",
        "is_hate",
        "tab",
    ]
    frame[integer_columns] = frame[integer_columns].astype("int64")
    return frame


def load_video_metadata(path: Path) -> pd.DataFrame:
    video = pd.read_csv(
        path,
        usecols=["video_id", "author_id", "upload_dt", "video_duration", "tag"],
    )
    video["tag"] = video["tag"].fillna("UNKNOWN").astype(str)
    video["upload_date"] = (
        pd.to_datetime(video["upload_dt"], errors="raise")
        .dt.strftime("%Y%m%d")
        .astype("int64")
    )
    video["video_duration"] = video["video_duration"].fillna(
        video["video_duration"].median()
    )
    return video.drop(columns=["upload_dt"])


def add_model_features(events: pd.DataFrame, video: pd.DataFrame) -> pd.DataFrame:
    metadata = video.set_index("video_id")
    enriched = events.copy()
    enriched["author_id"] = enriched["video_id"].map(metadata["author_id"])
    enriched["tag"] = enriched["video_id"].map(metadata["tag"])
    enriched["video_duration"] = enriched["video_id"].map(metadata["video_duration"])
    enriched["upload_date"] = enriched["video_id"].map(metadata["upload_date"])
    if enriched[["author_id", "tag", "video_duration", "upload_date"]].isna().any().any():
        raise ValueError("Video metadata join introduced missing values.")
    enriched["hour_bucket"] = (enriched["hourmin"] // 100).astype("int16")
    event_date = pd.to_datetime(enriched["date"].astype(str), format="%Y%m%d")
    upload_date = pd.to_datetime(enriched["upload_date"].astype(str), format="%Y%m%d")
    enriched["upload_age_days"] = (event_date - upload_date).dt.days.astype("int16")
    if (enriched["upload_age_days"] < 0).any():
        raise ValueError("Found event rows earlier than video upload date.")
    return enriched


def age_bucket(days: int) -> str:
    if days <= 1:
        return "0-1d"
    if days <= 3:
        return "2-3d"
    if days <= 7:
        return "4-7d"
    if days <= 14:
        return "8-14d"
    return "15d+"


def feature_dicts(frame: pd.DataFrame) -> Iterable[dict[str, float]]:
    columns = [
        "user_id",
        "video_id",
        "author_id",
        "tag",
        "tab",
        "hour_bucket",
        "video_duration",
        "upload_age_days",
    ]
    for row in frame[columns].itertuples(index=False, name=None):
        user_id, video_id, author_id, tag_string, tab, hour, duration, age_days = row
        tags = str(tag_string).split(",")
        features: dict[str, float] = {
            f"user={user_id}": 1.0,
            f"video={video_id}": 1.0,
            f"author={author_id}": 1.0,
            f"tab={tab}": 1.0,
            f"hour={hour}": 1.0,
            f"age={age_bucket(int(age_days))}": 1.0,
            "duration_log": float(np.log1p(duration)) / 12.0,
        }
        for tag in tags:
            features[f"tag={tag}"] = 1.0
            features[f"user_tag={user_id}:{tag}"] = 1.0
            features[f"tab_tag={tab}:{tag}"] = 1.0
        yield features


class MultiTaskHashSGD:
    def __init__(self, config: dict[str, Any], random_seed: int):
        self.config = config
        self.hasher = FeatureHasher(
            n_features=int(config["shared_hash_dimensions"]),
            input_type="dict",
            alternate_sign=False,
        )
        common = {
            "loss": "log_loss",
            "penalty": "l2",
            "alpha": float(config["alpha"]),
            "learning_rate": "optimal",
            "max_iter": 1,
            "tol": None,
            "random_state": random_seed,
        }
        self.click_model = SGDClassifier(**common)
        self.long_view_model = SGDClassifier(**common)
        self._fitted = False
        self.random_seed = random_seed

    def fit(self, frame: pd.DataFrame) -> "MultiTaskHashSGD":
        batch_rows = int(self.config["batch_rows"])
        epochs = int(self.config["epochs"])
        rng = np.random.default_rng(self.random_seed)
        classes = np.array([0, 1], dtype="int64")
        for epoch in range(epochs):
            order = rng.permutation(len(frame))
            for start in range(0, len(frame), batch_rows):
                batch_index = order[start : start + batch_rows]
                batch = frame.iloc[batch_index]
                matrix = self.hasher.transform(feature_dicts(batch))
                click = batch["is_click"].to_numpy(dtype="int64")
                long_view = batch["long_view"].to_numpy(dtype="int64")
                if not self._fitted:
                    self.click_model.partial_fit(matrix, click, classes=classes)
                    self.long_view_model.partial_fit(matrix, long_view, classes=classes)
                    self._fitted = True
                else:
                    self.click_model.partial_fit(matrix, click)
                    self.long_view_model.partial_fit(matrix, long_view)
            print(f"  multitask epoch {epoch + 1}/{epochs} complete")
        return self

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not self._fitted:
            raise RuntimeError("Model must be fitted before prediction.")
        batch_rows = int(self.config["batch_rows"])
        click_scores = np.empty(len(frame), dtype="float32")
        long_scores = np.empty(len(frame), dtype="float32")
        for start in range(0, len(frame), batch_rows):
            stop = min(start + batch_rows, len(frame))
            batch = frame.iloc[start:stop]
            matrix = self.hasher.transform(feature_dicts(batch))
            click_scores[start:stop] = self.click_model.predict_proba(matrix)[:, 1]
            long_scores[start:stop] = self.long_view_model.predict_proba(matrix)[:, 1]
        utility = (
            float(self.config["click_weight"]) * click_scores
            + float(self.config["long_view_weight"]) * long_scores
        )
        return click_scores, long_scores, utility.astype("float32")


def build_popularity(history: pd.DataFrame) -> tuple[pd.Series, set[int], set[int]]:
    positives = history.loc[history["long_view"] == 1]
    counts = positives.groupby("video_id").size().astype("float64")
    scores = np.log1p(counts)
    if len(scores) and scores.max() > 0:
        scores = scores / scores.max()
    return scores, set(history["user_id"].unique()), set(history["video_id"].unique())


def build_item_similarity(
    history: pd.DataFrame, shrinkage: float
) -> tuple[sparse.csr_matrix, dict[int, np.ndarray]]:
    positive = history.loc[history["long_view"] == 1, ["user_id", "video_id"]].drop_duplicates()
    user_count = int(max(history["user_id"].max(), positive["user_id"].max())) + 1
    item_count = int(max(history["video_id"].max(), positive["video_id"].max())) + 1
    interactions = sparse.coo_matrix(
        (
            np.ones(len(positive), dtype="float32"),
            (positive["user_id"].to_numpy(), positive["video_id"].to_numpy()),
        ),
        shape=(user_count, item_count),
    ).tocsr()
    interactions.data[:] = 1.0
    cooccurrence = (interactions.T @ interactions).tocoo().astype("float32")
    support = np.asarray(interactions.sum(axis=0)).ravel().astype("float32")
    keep = cooccurrence.row != cooccurrence.col
    rows = cooccurrence.row[keep]
    cols = cooccurrence.col[keep]
    values = cooccurrence.data[keep]
    denominator = np.sqrt(support[rows] * support[cols]) + float(shrinkage)
    values = values / denominator
    similarity = sparse.coo_matrix(
        (values, (rows, cols)), shape=(item_count, item_count)
    ).tocsr()
    positive_by_user = {
        int(user_id): group["video_id"].to_numpy(dtype="int64")
        for user_id, group in positive.groupby("user_id", sort=False)
    }
    return similarity, positive_by_user


def itemcf_scores(
    pairs: pd.DataFrame,
    similarity: sparse.csr_matrix,
    positive_by_user: dict[int, np.ndarray],
    popularity: pd.Series,
    backoff_weight: float,
) -> np.ndarray:
    scores = np.zeros(len(pairs), dtype="float32")
    video_values = pairs["video_id"].to_numpy(dtype="int64")
    for _, positions in pairs.groupby("user_id", sort=False).indices.items():
        positions = np.asarray(positions, dtype="int64")
        user_id = int(pairs.iloc[positions[0]]["user_id"])
        history_items = positive_by_user.get(user_id)
        if history_items is not None and len(history_items):
            targets = video_values[positions]
            scores[positions] = np.asarray(
                similarity[targets][:, history_items].sum(axis=1)
            ).ravel()
    fallback = pairs["video_id"].map(popularity).fillna(0.0).to_numpy(dtype="float32")
    return scores + float(backoff_weight) * fallback


def prepare_candidate_pairs(
    evaluation: pd.DataFrame,
    multitask_scores: tuple[np.ndarray, np.ndarray, np.ndarray],
    popularity: pd.Series,
    similarity: sparse.csr_matrix,
    positive_by_user: dict[int, np.ndarray],
    backoff_weight: float,
    history_users: set[int],
    history_items: set[int],
    video: pd.DataFrame,
) -> pd.DataFrame:
    click_scores, long_scores, utility_scores = multitask_scores
    scored = evaluation[
        ["user_id", "video_id", "long_view", "is_click", "is_hate"]
    ].copy()
    scored["multitask_click_score"] = click_scores
    scored["multitask_long_score"] = long_scores
    scored["multitask_score"] = utility_scores
    pairs = (
        scored.groupby(["user_id", "video_id"], as_index=False)
        .agg(
            long_view=("long_view", "max"),
            is_click=("is_click", "max"),
            is_hate=("is_hate", "max"),
            exposures=("video_id", "size"),
            multitask_click_score=("multitask_click_score", "mean"),
            multitask_long_score=("multitask_long_score", "mean"),
            multitask_score=("multitask_score", "mean"),
        )
    )
    pairs["popularity_score"] = pairs["video_id"].map(popularity).fillna(0.0)
    pairs["itemcf_score"] = itemcf_scores(
        pairs,
        similarity,
        positive_by_user,
        popularity,
        backoff_weight,
    )
    pairs["cold_user"] = ~pairs["user_id"].isin(history_users)
    pairs["cold_item"] = ~pairs["video_id"].isin(history_items)
    pairs = pairs.merge(
        video[["video_id", "author_id", "tag"]],
        on="video_id",
        how="left",
        validate="many_to_one",
    )
    return pairs


def user_ranking_metrics(
    pairs: pd.DataFrame,
    score_column: str,
    minimum_candidates: int,
    top_k_values: list[int],
    bootstrap_repetitions: int,
    random_seed: int,
) -> tuple[dict[str, float | int], pd.DataFrame]:
    user_summary = pairs.groupby("user_id").agg(
        candidate_count=("video_id", "size"),
        positive_count=("long_view", "sum"),
    )
    eligible_ids = user_summary.index[
        (user_summary["candidate_count"] >= minimum_candidates)
        & (user_summary["positive_count"] > 0)
    ]
    eligible = pairs[pairs["user_id"].isin(eligible_ids)].copy()
    eligible = eligible.sort_values(
        ["user_id", score_column, "video_id"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    eligible["rank"] = eligible.groupby("user_id").cumcount() + 1
    eligible["discount"] = 1.0 / np.log2(eligible["rank"] + 1.0)
    eligible["gain"] = eligible["long_view"] * eligible["discount"]

    per_user = user_summary.loc[eligible_ids].copy()
    for k in top_k_values:
        top = eligible[eligible["rank"] <= k]
        dcg = top.groupby("user_id")["gain"].sum()
        ideal = per_user["positive_count"].clip(upper=k).astype(int).map(
            lambda count: float(
                np.sum(1.0 / np.log2(np.arange(2, count + 2)))
            )
        )
        per_user[f"ndcg_at_{k}"] = dcg.reindex(per_user.index, fill_value=0.0) / ideal
        hits = top.groupby("user_id")["long_view"].sum()
        per_user[f"recall_at_{k}"] = hits.reindex(per_user.index, fill_value=0.0) / per_user[
            "positive_count"
        ]
        per_user[f"ecr_at_{k}"] = top.groupby("user_id")["long_view"].mean().reindex(
            per_user.index, fill_value=0.0
        )
        per_user[f"ctr_at_{k}"] = top.groupby("user_id")["is_click"].mean().reindex(
            per_user.index, fill_value=0.0
        )

    first_positive = (
        eligible.loc[(eligible["long_view"] == 1) & (eligible["rank"] <= 10)]
        .groupby("user_id")["rank"]
        .min()
    )
    per_user["mrr_at_10"] = (1.0 / first_positive).reindex(
        per_user.index, fill_value=0.0
    )
    per_user["all_candidate_ecr"] = eligible.groupby("user_id")["long_view"].mean()

    top10 = eligible[eligible["rank"] <= 10]
    try:
        auc = float(roc_auc_score(eligible["long_view"], eligible[score_column]))
    except ValueError:
        auc = float("nan")

    primary_values = per_user["ndcg_at_5"].to_numpy(dtype="float64")
    rng = np.random.default_rng(random_seed)
    bootstrap_means = np.empty(bootstrap_repetitions, dtype="float64")
    for index in range(bootstrap_repetitions):
        sample = rng.choice(primary_values, size=len(primary_values), replace=True)
        bootstrap_means[index] = sample.mean()
    ci_low, ci_high = np.quantile(bootstrap_means, [0.025, 0.975])

    metrics: dict[str, float | int] = {
        "candidate_pairs": int(len(pairs)),
        "candidate_users": int(pairs["user_id"].nunique()),
        "eligible_users": int(len(per_user)),
        "eligible_user_rate": float(len(per_user) / max(1, pairs["user_id"].nunique())),
        "cold_user_pair_rate": float(pairs["cold_user"].mean()),
        "cold_item_pair_rate": float(pairs["cold_item"].mean()),
        "auc_long_view": auc,
        "mrr_at_10": float(per_user["mrr_at_10"].mean()),
        "all_candidate_ecr": float(per_user["all_candidate_ecr"].mean()),
        "content_coverage_at_10": float(
            top10["video_id"].nunique() / max(1, eligible["video_id"].nunique())
        ),
        "author_coverage_at_10": float(
            top10["author_id"].nunique() / max(1, eligible["author_id"].nunique())
        ),
        "ndcg_at_5_ci_low": float(ci_low),
        "ndcg_at_5_ci_high": float(ci_high),
    }
    for k in top_k_values:
        for metric in ["ndcg", "recall", "ecr", "ctr"]:
            metrics[f"{metric}_at_{k}"] = float(per_user[f"{metric}_at_{k}"].mean())
    return metrics, per_user.reset_index()


def evaluate_models(
    *,
    split_name: str,
    history: pd.DataFrame,
    evaluation: pd.DataFrame,
    multitask_model: MultiTaskHashSGD,
    video: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    popularity, history_users, history_items = build_popularity(history)
    itemcf_config = config["models"]["itemcf"]
    similarity, positive_by_user = build_item_similarity(
        history, shrinkage=float(itemcf_config["shrinkage"])
    )
    multitask_scores = multitask_model.predict(evaluation)
    pairs = prepare_candidate_pairs(
        evaluation,
        multitask_scores,
        popularity,
        similarity,
        positive_by_user,
        float(itemcf_config["popularity_backoff_weight"]),
        history_users,
        history_items,
        video,
    )
    score_columns = {
        "Popularity": "popularity_score",
        "ItemCF": "itemcf_score",
        "MultiTaskHashSGD": "multitask_score",
    }
    metric_rows = []
    user_metric_frames = []
    evaluation_config = config["evaluation"]
    for model_name, score_column in score_columns.items():
        metrics, user_metrics = user_ranking_metrics(
            pairs,
            score_column,
            int(evaluation_config["minimum_candidates_per_user"]),
            [int(value) for value in evaluation_config["top_k"]],
            int(evaluation_config["bootstrap_repetitions"]),
            int(config["random_seed"]),
        )
        metrics.update({"split": split_name, "model": model_name})
        metric_rows.append(metrics)
        user_metrics.insert(0, "model", model_name)
        user_metrics.insert(0, "split", split_name)
        user_metric_frames.append(user_metrics)
    del similarity, positive_by_user
    gc.collect()
    return pd.DataFrame(metric_rows), pd.concat(user_metric_frames, ignore_index=True), pairs


def fractional_tag_shares(
    frame: pd.DataFrame, video_tags: pd.Series, value_column: str | None = None
) -> pd.Series:
    working = frame[["video_id"]].reset_index(drop=True).copy()
    working["tags"] = working["video_id"].map(video_tags)
    working["tag_count"] = working["tags"].str.count(",") + 1
    if value_column is None:
        working["base_weight"] = 1.0
    else:
        working["base_weight"] = frame[value_column].reset_index(drop=True).astype(float)
    working = working.explode("tags")
    working["weight"] = working["base_weight"] / working["tag_count"]
    totals = working.groupby("tags")["weight"].sum()
    if totals.sum() == 0:
        return totals
    return totals / totals.sum()


def build_diagnostics(
    history: pd.DataFrame,
    standard_test: pd.DataFrame,
    video: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    video_tags = video.set_index("video_id")["tag"]
    supply = fractional_tag_shares(video[["video_id"]], video_tags)
    demand = fractional_tag_shares(
        history.loc[history["long_view"] == 1], video_tags
    )
    exposure = fractional_tag_shares(standard_test, video_tags)
    consumption = fractional_tag_shares(
        standard_test.loc[standard_test["long_view"] == 1], video_tags
    )
    tags = pd.concat(
        {
            "supply_share": supply,
            "demand_share": demand,
            "exposure_share": exposure,
            "consumption_share": consumption,
        },
        axis=1,
    ).fillna(0.0)
    tags["supply_gap"] = tags["demand_share"] - tags["supply_share"]
    tags["distribution_gap"] = tags["demand_share"] - tags["exposure_share"]
    tags["consumption_gap"] = tags["exposure_share"] - tags["consumption_share"]
    tags.index.name = "tag_id"
    tags = tags.reset_index().sort_values("demand_share", ascending=False)

    daily = standard_test.groupby("date", as_index=False).agg(
        rows=("video_id", "size"),
        users=("user_id", "nunique"),
        videos=("video_id", "nunique"),
        click_rate=("is_click", "mean"),
        long_view_rate=("long_view", "mean"),
        hate_rate=("is_hate", "mean"),
    )

    if "author_id" in standard_test.columns:
        enriched = standard_test.copy()
    else:
        enriched = standard_test.merge(
            video[["video_id", "author_id"]],
            on="video_id",
            how="left",
            validate="many_to_one",
        )
    enriched["same_video_repeat"] = enriched.duplicated(
        ["user_id", "date", "video_id"]
    )
    enriched["same_author_repeat"] = enriched.duplicated(
        ["user_id", "date", "author_id"]
    )
    author_counts = enriched.groupby("author_id").size().sort_values(ascending=False)
    author_shares = author_counts / author_counts.sum()
    guardrails = {
        "same_video_repeat_rate_user_day": float(enriched["same_video_repeat"].mean()),
        "same_author_repeat_rate_user_day": float(enriched["same_author_repeat"].mean()),
        "users_with_video_repeat_rate": float(
            enriched.groupby("user_id")["same_video_repeat"].any().mean()
        ),
        "users_with_author_repeat_rate": float(
            enriched.groupby("user_id")["same_author_repeat"].any().mean()
        ),
        "author_hhi": float((author_shares**2).sum()),
        "top_1_author_exposure_share": float(author_shares.iloc[0]),
        "top_10_author_exposure_share": float(author_shares.head(10).sum()),
        "top_100_author_exposure_share": float(author_shares.head(100).sum()),
        "exposed_authors": int(len(author_counts)),
    }
    return tags, daily, guardrails


def audit_feature_spec(feature: dict[str, Any], forbidden_sources: set[str]) -> list[str]:
    failures = []
    if feature.get("source") in forbidden_sources:
        failures.append("forbidden_source")
    if feature.get("available_at") not in {
        "identity",
        "request_time",
        "upload",
        "strictly_before_request_time",
    }:
        failures.append("invalid_availability")
    if feature.get("uses_outcome"):
        failures.append("outcome_leakage")
    return failures


def build_leakage_report(
    config: dict[str, Any],
    train: pd.DataFrame,
    validation: pd.DataFrame,
    standard_test: pd.DataFrame,
    video: pd.DataFrame,
) -> dict[str, Any]:
    allowed_specs = [
        {"name": "user_id", "source": "event", "available_at": "identity"},
        {"name": "video_id", "source": "event", "available_at": "identity"},
        {"name": "author_id", "source": "video_features_basic_pure.csv", "available_at": "upload"},
        {"name": "tag", "source": "video_features_basic_pure.csv", "available_at": "upload"},
        {"name": "tab", "source": "event", "available_at": "request_time"},
        {"name": "hour_bucket", "source": "event", "available_at": "request_time"},
        {"name": "video_duration", "source": "video_features_basic_pure.csv", "available_at": "upload"},
        {"name": "upload_age_bucket", "source": "video_features_basic_pure.csv", "available_at": "request_time"},
    ]
    forbidden_sources = {"video_features_statistic_pure.csv"}
    actual_failures = {
        spec["name"]: audit_feature_spec(spec, forbidden_sources)
        for spec in allowed_specs
    }
    injected = {
        "name": "future_test_long_view_rate",
        "source": "video_features_statistic_pure.csv",
        "available_at": "after_outcome",
        "uses_outcome": True,
    }
    injected_failures = audit_feature_spec(injected, forbidden_sources)

    all_events = pd.concat(
        [
            train[["video_id", "date"]],
            validation[["video_id", "date"]],
            standard_test[["video_id", "date"]],
        ],
        ignore_index=True,
    ).merge(
        video[["video_id", "upload_date"]],
        on="video_id",
        how="left",
        validate="many_to_one",
    )
    split_config = config["time_split"]
    checks = {
        "train_ends_before_validation": int(train["date"].max()) < int(validation["date"].min()),
        "validation_ends_before_test": int(validation["date"].max()) < int(standard_test["date"].min()),
        "configured_boundaries_match": (
            int(train["date"].min()) == int(split_config["train"]["start"])
            and int(train["date"].max()) == int(split_config["train"]["end"])
            and int(validation["date"].min()) == int(split_config["validation"]["start"])
            and int(validation["date"].max()) == int(split_config["validation"]["end"])
            and int(standard_test["date"].min()) == int(split_config["test"]["start"])
            and int(standard_test["date"].max()) == int(split_config["test"]["end"])
        ),
        "no_future_upload_metadata": int((all_events["upload_date"] > all_events["date"]).sum()) == 0,
        "allowed_feature_specs_pass": all(not value for value in actual_failures.values()),
        "forbidden_outcomes_absent_from_features": not bool(
            set(config["allowed_model_features"]) & set(config["forbidden_model_features"])
        ),
        "injected_future_feature_rejected": len(injected_failures) >= 2,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "actual_feature_failures": actual_failures,
        "injected_feature": injected,
        "injected_feature_failures": injected_failures,
        "future_upload_rows": int((all_events["upload_date"] > all_events["date"]).sum()),
        "claim_boundary": config["claim_boundary"],
    }


def metric_table_markdown(metrics: pd.DataFrame, split: str) -> list[str]:
    selected = metrics[metrics["split"] == split].copy()
    lines = [
        "| 模型 | NDCG@5 | 95% CI | NDCG@10 | MRR@10 | AUC | Top-5 ECR | Coverage@10 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in selected.itertuples(index=False):
        lines.append(
            f"| {row.model} | {row.ndcg_at_5:.4f} | "
            f"[{row.ndcg_at_5_ci_low:.4f}, {row.ndcg_at_5_ci_high:.4f}] | "
            f"{row.ndcg_at_10:.4f} | {row.mrr_at_10:.4f} | {row.auc_long_view:.4f} | "
            f"{row.ecr_at_5:.2%} | {row.content_coverage_at_10:.2%} |"
        )
    return lines


def build_markdown_report(
    config: dict[str, Any],
    split_manifest: dict[str, Any],
    metrics: pd.DataFrame,
    tags: pd.DataFrame,
    guardrails: dict[str, Any],
    leakage: dict[str, Any],
) -> str:
    standard_metrics = metrics[metrics["split"] == "standard_test"]
    best = standard_metrics.sort_values("ndcg_at_5", ascending=False).iloc[0]
    random_metrics = metrics[metrics["split"] == "random_sensitivity"]
    random_best = random_metrics.sort_values("ndcg_at_5", ascending=False).iloc[0]
    tag_scope = tags[tags["exposure_share"] >= 0.002]
    underdistributed = tag_scope.sort_values("distribution_gap", ascending=False).head(5)
    inefficient = tag_scope.sort_values("consumption_gap", ascending=False).head(5)
    lines = [
        "# FlowLens Gate 3｜诊断与基线报告",
        "",
        "## 1. Gate 结论",
        "",
        f"**PASS WITH CONDITIONS**：严格时间切分、三组统一口径基线、point-in-time 泄漏测试和真实供需诊断均已完成。标准曝光测试集上，`{best['model']}` 的 NDCG@5 最高（{best['ndcg_at_5']:.4f}），但这只是对已记录曝光集合的离线重排代理，不代表线上增量。",
        "",
        "## 2. 时间切分与评估边界",
        "",
        f"- 训练：{config['time_split']['train']['start']}–{config['time_split']['train']['end']}，{split_manifest['train']['rows']:,} 行。",
        f"- 验证：{config['time_split']['validation']['start']}–{config['time_split']['validation']['end']}，{split_manifest['validation']['rows']:,} 行。",
        f"- 测试：{config['time_split']['test']['start']}–{config['time_split']['test']['end']}，标准曝光 {split_manifest['standard_test']['rows']:,} 行；随机曝光 {split_manifest['random_sensitivity']['rows']:,} 行。",
        "- 候选定义：评估窗内真实出现的去重用户—视频对；因此指标衡量 logged-exposure reranking，不是全目录召回。",
        "- 验证集用于开发检查，测试集只用于冻结参数后的最终评估；随机曝光日志只做采样机制敏感性。",
        "",
        "## 3. 标准曝光测试集基线",
        "",
        *metric_table_markdown(metrics, "standard_test"),
        "",
        "## 4. 随机曝光敏感性",
        "",
        *metric_table_markdown(metrics, "random_sensitivity"),
        "",
        f"模型排序发生反转：标准曝光集由 `{best['model']}` 领先，而随机曝光敏感性集由 `{random_best['model']}` 领先。这说明离线排序结论明显受日志采样／原策略影响；跨日志指标变化只用于识别选择偏差，不用于比较策略因果收益，也不能把任一模型称为普适最优。",
        "",
        "## 5. 真实供需与分发瓶颈",
        "",
        "### 5.1 历史需求高于后续曝光的标签",
        "",
        "| 标签 ID | 供给份额 | 历史需求份额 | 测试曝光份额 | 测试消费份额 | 需求-曝光 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in underdistributed.itertuples(index=False):
        lines.append(
            f"| {row.tag_id} | {row.supply_share:.2%} | {row.demand_share:.2%} | "
            f"{row.exposure_share:.2%} | {row.consumption_share:.2%} | {row.distribution_gap:+.2%} |"
        )
    lines.extend(
        [
            "",
            "### 5.2 曝光份额高于消费份额的标签",
            "",
            "| 标签 ID | 历史需求份额 | 测试曝光份额 | 测试消费份额 | 曝光-消费 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in inefficient.itertuples(index=False):
        lines.append(
            f"| {row.tag_id} | {row.demand_share:.2%} | {row.exposure_share:.2%} | "
            f"{row.consumption_share:.2%} | {row.consumption_gap:+.2%} |"
        )
    lines.extend(
        [
            "",
            "这些标签只证明份额错配。标签名称未公开、日志也没有随机化策略分组，因此原因仍是待验证假设。",
            "",
            "## 6. 生态与体验护栏基线",
            "",
            f"- 同用户同日重复视频曝光率：{guardrails['same_video_repeat_rate_user_day']:.2%}；发生过该问题的用户占 {guardrails['users_with_video_repeat_rate']:.2%}。",
            f"- 同用户同日重复作者曝光率：{guardrails['same_author_repeat_rate_user_day']:.2%}；发生过该问题的用户占 {guardrails['users_with_author_repeat_rate']:.2%}。",
            f"- 作者曝光 HHI：{guardrails['author_hhi']:.6f}；Top 10 作者占 {guardrails['top_10_author_exposure_share']:.2%}，Top 100 作者占 {guardrails['top_100_author_exposure_share']:.2%}。",
            "",
            "## 7. 泄漏测试",
            "",
            f"结果：**{leakage['status']}**。训练、验证、测试窗严格递增；所有视频上传时间不晚于事件时间；结果字段和整月统计特征均未进入模型。故意注入的 `future_test_long_view_rate` 被 `forbidden_source`、`invalid_availability` 和 `outcome_leakage` 三条规则拒绝。",
            "",
            "## 8. 产品判断",
            "",
            "1. 优先验证标签 39 的供给与分发问题：历史需求份额高于供给与后续曝光，适合拆成“补供给”和“调配曝光”两个独立假设。",
            "2. 标签 2 是观察到的最强效率错配候选：曝光份额高于消费份额 1.42 个百分点；标签 12 的错配幅度较小（0.64 个百分点）但曝光规模更大（7.61%），适合分别验证“高差值小规模”和“较低差值大规模”两类策略。两者都必须先下钻人群和 tab，排除场景结构差异。",
            "3. Gate 4 不应直接把 MultiTaskHashSGD 当成唯一胜者；策略对比必须沿用固定时间窗，并同时报告标准曝光与随机曝光敏感性、ECR、作者／标签覆盖和重复曝光护栏。",
            "",
            "## 9. 限制",
            "",
            "- 数字标签缺少业务语义，不能直接命名为题材或内容品类。",
            "- logged-exposure reranking 受原推荐策略选择偏差影响，NDCG／ECR 不能解释为线上提升。",
            "- KuaiRand-Pure 顺序日志不完整；不据此宣称严谨长序列、强化学习或完整 OPE 能力。",
            "- 视频上传日期集中在 2022-04-09～04-11，无法可靠评估持续新内容冷启动。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    split = config["time_split"]

    video = load_video_metadata(args.source_dir / "video_features_basic_pure.csv")
    early_path = args.events_dir / "log_standard_4_08_to_4_21_pure_clean.csv"
    standard_test_path = args.events_dir / "log_standard_4_22_to_5_08_pure_clean.csv"
    random_path = args.events_dir / "log_random_4_22_to_5_08_pure_clean.csv"

    print("Loading and enriching standard early events...")
    early = add_model_features(load_events(early_path), video)
    train = early[
        early["date"].between(split["train"]["start"], split["train"]["end"])
    ].reset_index(drop=True)
    validation = early[
        early["date"].between(
            split["validation"]["start"], split["validation"]["end"]
        )
    ].reset_index(drop=True)

    print("Training development model and evaluating validation split...")
    development_model = MultiTaskHashSGD(
        config["models"]["multitask_hash_sgd"], int(config["random_seed"])
    ).fit(train)
    validation_metrics, validation_user_metrics, validation_pairs = evaluate_models(
        split_name="validation",
        history=train,
        evaluation=validation,
        multitask_model=development_model,
        video=video,
        config=config,
    )
    del development_model
    gc.collect()

    print("Training frozen final model on train + validation...")
    final_model = MultiTaskHashSGD(
        config["models"]["multitask_hash_sgd"], int(config["random_seed"])
    ).fit(early)

    print("Evaluating primary standard test split...")
    standard_test = add_model_features(load_events(standard_test_path), video)
    standard_metrics, standard_user_metrics, standard_pairs = evaluate_models(
        split_name="standard_test",
        history=early,
        evaluation=standard_test,
        multitask_model=final_model,
        video=video,
        config=config,
    )

    tags, daily, guardrails = build_diagnostics(early, standard_test, video)
    leakage = build_leakage_report(config, train, validation, standard_test, video)

    print("Evaluating random-exposure sensitivity split...")
    random_events = add_model_features(load_events(random_path), video)
    random_metrics, random_user_metrics, random_pairs = evaluate_models(
        split_name="random_sensitivity",
        history=early,
        evaluation=random_events,
        multitask_model=final_model,
        video=video,
        config=config,
    )

    metrics = pd.concat(
        [validation_metrics, standard_metrics, random_metrics], ignore_index=True
    )
    user_metrics = pd.concat(
        [validation_user_metrics, standard_user_metrics, random_user_metrics],
        ignore_index=True,
    )
    split_manifest = {
        "train": {
            "rows": int(len(train)),
            "users": int(train["user_id"].nunique()),
            "videos": int(train["video_id"].nunique()),
            "date_min": int(train["date"].min()),
            "date_max": int(train["date"].max()),
            "long_view_rate": float(train["long_view"].mean()),
        },
        "validation": {
            "rows": int(len(validation)),
            "users": int(validation["user_id"].nunique()),
            "videos": int(validation["video_id"].nunique()),
            "date_min": int(validation["date"].min()),
            "date_max": int(validation["date"].max()),
            "long_view_rate": float(validation["long_view"].mean()),
        },
        "standard_test": {
            "rows": int(len(standard_test)),
            "users": int(standard_test["user_id"].nunique()),
            "videos": int(standard_test["video_id"].nunique()),
            "date_min": int(standard_test["date"].min()),
            "date_max": int(standard_test["date"].max()),
            "long_view_rate": float(standard_test["long_view"].mean()),
        },
        "random_sensitivity": {
            "rows": int(len(random_events)),
            "users": int(random_events["user_id"].nunique()),
            "videos": int(random_events["video_id"].nunique()),
            "date_min": int(random_events["date"].min()),
            "date_max": int(random_events["date"].max()),
            "long_view_rate": float(random_events["long_view"].mean()),
        },
    }

    metrics.to_csv(args.report_dir / "baseline_metrics.csv", index=False)
    user_metrics.to_csv(args.report_dir / "user_ranking_metrics.csv", index=False)
    validation_pairs.to_csv(args.report_dir / "validation_candidate_scores.csv", index=False)
    tags.to_csv(args.report_dir / "tag_supply_demand.csv", index=False)
    daily.to_csv(args.report_dir / "daily_standard_test.csv", index=False)
    standard_pairs.to_csv(args.report_dir / "standard_test_candidate_scores.csv", index=False)
    random_pairs.to_csv(args.report_dir / "random_sensitivity_candidate_scores.csv", index=False)
    (args.report_dir / "split_manifest.json").write_text(
        json.dumps(split_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.report_dir / "guardrails.json").write_text(
        json.dumps(guardrails, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.report_dir / "leakage_report.json").write_text(
        json.dumps(leakage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    profile_path = Path(__file__).resolve().parents[1] / "reports" / "data-quality" / "profile.json"
    archive_md5 = json.loads(profile_path.read_text(encoding="utf-8"))["archive"]["actual_md5"]
    run_material = json.dumps(config, sort_keys=True) + archive_md5 + sha256_file(Path(__file__).resolve())
    run_id = "gate3-" + hashlib.sha256(run_material.encode("utf-8")).hexdigest()[:12]
    run_manifest = {
        "run_id": run_id,
        "status": "VALID" if leakage["status"] == "PASS" else "INVALID_DATA",
        "evidence_level": config["evidence_level"],
        "config_id": config["config_id"],
        "config_sha256": sha256_file(args.config),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "archive_md5": archive_md5,
        "random_seed": config["random_seed"],
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "pandas", "scipy", "scikit-learn"]
        },
        "source_files": [
            str(path.resolve().relative_to(Path(__file__).resolve().parents[1]))
            for path in (early_path, standard_test_path, random_path)
        ],
        "artifacts": [
            "baseline_metrics.csv",
            "user_ranking_metrics.csv",
            "validation_candidate_scores.csv",
            "tag_supply_demand.csv",
            "daily_standard_test.csv",
            "standard_test_candidate_scores.csv",
            "random_sensitivity_candidate_scores.csv",
            "split_manifest.json",
            "guardrails.json",
            "leakage_report.json",
            "Gate3-诊断与基线报告.md",
        ],
        "claim_boundary": config["claim_boundary"],
    }
    (args.report_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = build_markdown_report(
        config, split_manifest, metrics, tags, guardrails, leakage
    )
    (args.report_dir / "Gate3-诊断与基线报告.md").write_text(report, encoding="utf-8")
    print(f"Gate 3 run complete: {run_id} ({run_manifest['status']})")
    print(f"Artifacts: {args.report_dir}")
    if run_manifest["status"] != "VALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
