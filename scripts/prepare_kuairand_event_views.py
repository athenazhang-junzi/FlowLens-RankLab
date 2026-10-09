#!/usr/bin/env python3
"""Create analysis-safe event views while preserving all raw source columns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


LOGS = {
    "standard_early": "log_standard_4_08_to_4_21_pure.csv",
    "standard_late": "log_standard_4_22_to_5_08_pure.csv",
    "random_late": "log_random_4_22_to_5_08_pure.csv",
}
EVENT_KEY = ["user_id", "video_id", "time_ms"]


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=project_root / "data" / "extracted" / "KuaiRand-Pure" / "data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "processed" / "events",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project_root / "reports" / "data-quality" / "cleaning_manifest.json",
    )
    return parser.parse_args()


def prepare_view(source_name: str, source_path: Path) -> tuple[pd.DataFrame, dict[str, int | float | str]]:
    raw = pd.read_csv(source_path, low_memory=False)
    raw_rows = len(raw)
    exact_duplicate_rows = int(raw.duplicated().sum())
    clean = raw.drop_duplicates().copy()

    duration_valid = clean["duration_ms"] > 0
    long_view_rule = np.where(
        clean["duration_ms"] <= 18_000,
        clean["play_time_ms"] >= clean["duration_ms"],
        clean["play_time_ms"] >= 18_000,
    )
    long_view_rule_series = pd.Series(long_view_rule, index=clean.index, dtype="Int64")
    long_view_rule_series.loc[~duration_valid] = pd.NA

    timestamp_china = pd.to_datetime(clean["time_ms"], unit="ms", utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    timestamp_date = timestamp_china.dt.strftime("%Y%m%d").astype("int64")

    clean.insert(0, "source_log", source_name)
    clean.insert(1, "collection_policy", "random" if source_name == "random_late" else "standard")
    clean["duration_valid"] = duration_valid
    clean["long_view_rule"] = long_view_rule_series
    clean["long_view_rule_match"] = (
        long_view_rule_series.eq(clean["long_view"]).astype("boolean")
    )
    clean["timestamp_date_china"] = timestamp_date
    clean["timestamp_date_match"] = timestamp_date.eq(clean["date"])
    clean["event_key_collision"] = clean.duplicated(EVENT_KEY, keep=False)

    manifest = {
        "source": source_path.name,
        "raw_rows": raw_rows,
        "clean_rows": len(clean),
        "exact_duplicate_rows_dropped": exact_duplicate_rows,
        "exact_duplicate_rate": exact_duplicate_rows / raw_rows,
        "duration_invalid_rows": int((~clean["duration_valid"]).sum()),
        "long_view_rule_unverifiable_rows": int(clean["long_view_rule"].isna().sum()),
        "long_view_rule_mismatch_rows": int((clean["long_view_rule_match"] == False).sum()),
        "timestamp_date_mismatch_rows": int((~clean["timestamp_date_match"]).sum()),
        "event_key_collision_rows_after_exact_dedup": int(clean["event_key_collision"].sum()),
    }
    return clean, manifest


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "policy": {
            "raw_files_immutable": True,
            "exact_duplicates": "drop in analysis view only",
            "event_key_collisions": "preserve and flag",
            "long_view": "preserve official raw label; derived rule is a nullable sensitivity field",
            "daily_partition": "source date",
            "within_day_order": "time_ms"
        },
        "logs": {},
    }
    for source_name, filename in LOGS.items():
        clean, log_manifest = prepare_view(source_name, args.data_dir / filename)
        output_path = args.output_dir / filename.replace(".csv", "_clean.csv")
        clean.to_csv(output_path, index=False)
        log_manifest["output"] = str(
            output_path.resolve().relative_to(Path(__file__).resolve().parents[1])
        )
        manifest["logs"][source_name] = log_manifest
        print(f"Wrote {output_path} ({len(clean):,} rows)")

    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
