#!/usr/bin/env python3
"""Export KuaiRand-Pure replay groups as contract-valid Metarank events."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from metarank_contract import (
    DEFAULT_CONTRACT_PATH,
    PROJECT_ROOT,
    load_contract,
    sha256_file,
    stable_hash,
    validate_events,
    write_jsonl,
)


EVENT_COLUMNS = [
    "user_id",
    "video_id",
    "date",
    "time_ms",
    "is_click",
    "is_hate",
    "long_view",
    "tab",
]
METADATA_COLUMNS = [
    "video_id",
    "author_id",
    "upload_dt",
    "video_duration",
    "tag",
]
EVENT_TYPE_ORDER = {"item": 0, "user": 1, "ranking": 2, "interaction": 3}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "events" / "log_standard_4_08_to_4_21_pure_clean.csv",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "extracted"
        / "KuaiRand-Pure"
        / "data"
        / "video_features_basic_pure.csv",
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument(
        "--gate3-config",
        type=Path,
        default=PROJECT_ROOT / "config" / "gate3_baseline.json",
    )
    parser.add_argument(
        "--gate3-manifest",
        type=Path,
        default=PROJECT_ROOT / "reports" / "gate3" / "run_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "runs" / "integration" / "gateb-contract" / "events.jsonl",
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--split", default="train")
    parser.add_argument("--start-date", type=int)
    parser.add_argument("--end-date", type=int)
    parser.add_argument(
        "--max-groups",
        type=int,
        default=200,
        help="Maximum replay groups to export; use 0 for all eligible groups.",
    )
    parser.add_argument(
        "--group-sampling",
        choices=["first", "hash"],
        default="first",
        help="Select the first eligible groups or a deterministic hash sample.",
    )
    parser.add_argument("--sample-seed", type=int, default=20261009)
    parser.add_argument("--minimum-items", type=int, default=2)
    return parser.parse_args()


def normalize_tags(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ["UNKNOWN_TAG"]
    tags = [part.strip() for part in str(value).split(",") if part.strip()]
    return tags or ["UNKNOWN_TAG"]


def metadata_fields(row: pd.Series) -> list[dict[str, Any]]:
    author_id = float(row["author_id"])
    if not math.isfinite(author_id):
        raise ValueError(f"Missing author_id for video_id={row.name}")
    fields: list[dict[str, Any]] = [
        {"name": "author_id", "value": str(int(author_id))},
        {"name": "tags", "value": normalize_tags(row["tag"])},
        {"name": "metadata_version", "value": "kuairand_pure_basic_v1"},
    ]
    upload_date = row["upload_dt"]
    if upload_date is not None and not pd.isna(upload_date):
        fields.append({"name": "upload_date", "value": str(upload_date)})
    duration = row["video_duration"]
    duration_missing = duration is None or pd.isna(duration)
    if not duration_missing:
        duration_value = float(duration)
        if duration_value < 0:
            raise ValueError(f"Negative duration for video_id={row.name}: {duration_value}")
        fields.append({"name": "duration_ms", "value": duration_value})
    else:
        fields.append({"name": "duration_ms", "value": 0.0})
    fields.append({"name": "duration_missing", "value": 1.0 if duration_missing else 0.0})
    return fields


def build_events(
    events_path: Path,
    metadata_path: Path,
    contract: dict[str, Any],
    *,
    split: str,
    start_date: int,
    end_date: int,
    max_groups: int,
    minimum_items: int,
    upstream_run_id: str,
    group_sampling: str = "first",
    sample_seed: int = 20261009,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_groups < 0:
        raise ValueError("max_groups must be zero or positive")
    if minimum_items < 2:
        raise ValueError("minimum_items must be at least 2")

    frame = pd.read_csv(events_path, usecols=EVENT_COLUMNS, low_memory=False)
    frame[EVENT_COLUMNS] = frame[EVENT_COLUMNS].astype("int64")
    frame = frame[(frame["date"] >= start_date) & (frame["date"] <= end_date)].copy()
    if frame.empty:
        raise ValueError("No source events remain after the requested date filter")
    frame = frame.sort_values(
        ["user_id", "date", "tab", "time_ms", "video_id"], kind="mergesort"
    )

    group_columns = ["user_id", "date", "tab"]
    group_sizes = frame.groupby(group_columns, sort=False)["video_id"].nunique()
    eligible_groups = group_sizes[group_sizes >= minimum_items].reset_index()[group_columns]
    groups_seen = int(len(group_sizes))
    groups_below_minimum = int((group_sizes < minimum_items).sum())
    if max_groups and len(eligible_groups) > max_groups:
        if group_sampling == "hash":
            eligible_groups = eligible_groups.assign(
                _sample_key=[
                    stable_hash(sample_seed, row.user_id, row.date, row.tab, length=32)
                    for row in eligible_groups.itertuples(index=False)
                ]
            ).sort_values("_sample_key", kind="mergesort").head(max_groups)
        else:
            eligible_groups = eligible_groups.head(max_groups)
    selected_keys = {
        (int(row.user_id), int(row.date), int(row.tab))
        for row in eligible_groups.itertuples(index=False)
    }
    selected_groups = [
        (tuple(int(value) for value in key), group.copy())
        for key, group in frame.groupby(group_columns, sort=False)
        if tuple(int(value) for value in key) in selected_keys
    ]
    if not selected_groups:
        raise ValueError("No replay group satisfies the minimum candidate requirement")

    selected_video_ids = sorted(
        {
            int(video_id)
            for _, group in selected_groups
            for video_id in group["video_id"].unique()
        }
    )
    metadata = pd.read_csv(metadata_path, usecols=METADATA_COLUMNS, low_memory=False)
    metadata = metadata[metadata["video_id"].isin(selected_video_ids)].copy()
    if metadata["video_id"].duplicated().any():
        raise ValueError("Video metadata contains duplicate video_id values")
    metadata = metadata.set_index("video_id")
    missing_metadata = sorted(set(selected_video_ids) - set(metadata.index.astype(int)))
    if missing_metadata:
        raise ValueError(f"Missing metadata for video IDs: {missing_metadata[:10]}")

    namespaces = contract["namespaces"]
    output: list[dict[str, Any]] = []
    first_seen: dict[int, int] = {}
    for _, group in selected_groups:
        for row in group[["video_id", "time_ms"]].itertuples(index=False):
            video_id = int(row.video_id)
            first_seen[video_id] = min(first_seen.get(video_id, int(row.time_ms)), int(row.time_ms))

    for video_id in selected_video_ids:
        row = metadata.loc[video_id]
        output.append(
            {
                "event": "item",
                "id": f"flr:item:{video_id}:kuairand_pure_basic_v1",
                "timestamp": first_seen[video_id] - 2,
                "item": f"{namespaces['item']}{video_id}",
                "fields": metadata_fields(row),
            }
        )

    interaction_count = 0
    candidate_count = 0
    for (user_id, date, tab), group in selected_groups:
        ordered = group.sort_values(["time_ms", "video_id"], kind="mergesort")
        first_candidates = ordered.drop_duplicates("video_id", keep="first")
        ranking_id = (
            f"{namespaces['ranking']}{split}:"
            f"{stable_hash(user_id, date, tab, split, contract['contract_id'])}"
        )
        session = f"{namespaces['session']}{user_id}:{date}:{tab}"
        user = f"{namespaces['user']}{user_id}"
        item_rows: list[dict[str, Any]] = []
        for position, row in enumerate(first_candidates.itertuples(index=False), start=1):
            exposure_count = int((group["video_id"] == int(row.video_id)).sum())
            item_rows.append(
                {
                    "id": f"{namespaces['item']}{int(row.video_id)}",
                    "fields": [
                        {"name": "source_exposure_count", "value": exposure_count},
                        {"name": "source_sequence_position", "value": position},
                    ],
                }
            )
        candidate_count += len(item_rows)
        ranking_timestamp = int(ordered["time_ms"].min()) - 1
        output.append(
            {
                "event": "ranking",
                "id": ranking_id,
                "timestamp": ranking_timestamp,
                "user": user,
                "session": session,
                "fields": [
                    {"name": "scene_tab", "value": str(tab)},
                    {"name": "source_date", "value": str(date)},
                    {"name": "dataset_split", "value": split},
                    {"name": "source_mode", "value": "logged_exposure_replay"},
                    {"name": "upstream_run_id", "value": upstream_run_id},
                    {"name": "strategy_version", "value": "historical_logged_order_v1"},
                    {"name": "evidence_level", "value": "E3"},
                ],
                "items": item_rows,
            }
        )

        for interaction_type, source_column in [
            ("click", "is_click"),
            ("long_view", "long_view"),
            ("negative_feedback", "is_hate"),
        ]:
            positive = ordered[ordered[source_column] == 1]
            if positive.empty:
                continue
            for video_id, item_group in positive.groupby("video_id", sort=False):
                timestamp = int(item_group["time_ms"].min())
                output.append(
                    {
                        "event": "interaction",
                        "id": (
                            f"{namespaces['interaction']}{interaction_type}:"
                            f"{stable_hash(ranking_id, interaction_type, int(video_id))}"
                        ),
                        "ranking": ranking_id,
                        "timestamp": timestamp,
                        "user": user,
                        "session": session,
                        "type": interaction_type,
                        "item": f"{namespaces['item']}{int(video_id)}",
                        "fields": [
                            {"name": "source_dataset", "value": "KuaiRand-Pure"},
                            {"name": "evidence_level", "value": "E1"},
                        ],
                    }
                )
                interaction_count += 1

    output.sort(
        key=lambda event: (
            int(event["timestamp"]),
            EVENT_TYPE_ORDER.get(str(event.get("event")), 99),
            str(event.get("id")),
        )
    )
    summary = {
        "source_rows_in_date_window": int(len(frame)),
        "groups_scanned_until_limit": groups_seen,
        "groups_below_minimum": groups_below_minimum,
        "groups_exported": len(selected_groups),
        "group_sampling": group_sampling,
        "sample_seed": sample_seed,
        "unique_items_exported": len(selected_video_ids),
        "ranking_candidates_exported": candidate_count,
        "interactions_exported": interaction_count,
        "items_with_missing_duration": int(metadata["video_duration"].isna().sum()),
    }
    return output, summary


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return resolved.name


def main() -> None:
    args = parse_args()
    contract = load_contract(args.contract)
    gate3_config = json.loads(args.gate3_config.read_text(encoding="utf-8"))
    gate3_manifest = json.loads(args.gate3_manifest.read_text(encoding="utf-8"))
    split_config = gate3_config["time_split"].get(args.split)
    if split_config is None:
        raise ValueError(f"Split {args.split!r} is not present in the Gate 3 config")
    start_date = args.start_date or int(split_config["start"])
    end_date = args.end_date or int(split_config["end"])

    events, summary = build_events(
        args.events,
        args.metadata,
        contract,
        split=args.split,
        start_date=start_date,
        end_date=end_date,
        max_groups=args.max_groups,
        minimum_items=args.minimum_items,
        upstream_run_id=gate3_manifest["run_id"],
        group_sampling=args.group_sampling,
        sample_seed=args.sample_seed,
    )
    validation = validate_events(events, contract)
    if validation["status"] != "PASS":
        failed = [check for check in validation["checks"] if check["status"] == "FAIL"]
        raise ValueError(f"Generated events failed contract validation: {failed}")
    write_jsonl(args.output, events)

    manifest_path = args.manifest or args.output.with_name("export_manifest.json")
    parameters = {
        "split": args.split,
        "start_date": start_date,
        "end_date": end_date,
        "max_groups": args.max_groups,
        "minimum_items": args.minimum_items,
        "group_sampling": args.group_sampling,
        "sample_seed": args.sample_seed,
    }
    run_hash = stable_hash(
        contract["contract_id"],
        sha256_file(args.events),
        sha256_file(args.metadata),
        json.dumps(parameters, sort_keys=True),
    )
    manifest = {
        "run_id": f"gateb-export-{run_hash}",
        "status": "VALID",
        "evidence_level": "E3",
        "contract_id": contract["contract_id"],
        "upstream_gate3_run_id": gate3_manifest["run_id"],
        "source_events": display_path(args.events),
        "source_events_sha256": sha256_file(args.events),
        "source_metadata": display_path(args.metadata),
        "source_metadata_sha256": sha256_file(args.metadata),
        "contract_sha256": sha256_file(args.contract),
        "script_sha256": sha256_file(Path(__file__)),
        "output": display_path(args.output),
        "output_sha256": sha256_file(args.output),
        "parameters": parameters,
        "summary": summary,
        "validation_checks": len(validation["checks"]),
        "claim_boundary": contract["claim_boundary"],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Metarank event export: VALID; groups={summary['groups_exported']}, "
        f"events={len(events)}, interactions={summary['interactions_exported']}"
    )
    print(f"Output: {display_path(args.output)}")
    print(f"Manifest: {display_path(manifest_path)}")


if __name__ == "__main__":
    main()
