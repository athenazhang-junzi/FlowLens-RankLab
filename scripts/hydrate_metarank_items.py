#!/usr/bin/env python3
"""Hydrate Metarank item metadata for a reproducible Gate C evaluation cohort."""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from metarank_contract import PROJECT_ROOT, sha256_file, write_jsonl


DEFAULT_METADATA = (
    PROJECT_ROOT
    / "data"
    / "extracted"
    / "KuaiRand-Pure"
    / "data"
    / "video_features_basic_pure.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, action="append", required=True)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--timestamp-ms", type=int, default=1650207850711)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--events-output",
        type=Path,
        default=PROJECT_ROOT / "runs" / "integration" / "gatec-hydration" / "item_events.jsonl",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "reports" / "integration" / "gatec_metadata_hydration.json",
    )
    return parser.parse_args()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return resolved.name


def candidate_item_ids(paths: list[Path]) -> set[int]:
    item_ids: set[int] = set()
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if "video_id" not in (reader.fieldnames or []):
                raise ValueError(f"Candidate file has no video_id column: {path}")
            for row in reader:
                item_ids.add(int(row["video_id"]))
    if not item_ids:
        raise ValueError("Candidate files contain no video IDs")
    return item_ids


def normalize_tags(value: str | None) -> list[str]:
    tags = [part.strip() for part in str(value or "").split(",") if part.strip()]
    return tags or ["UNKNOWN_TAG"]


def build_item_events(
    candidates: list[Path], metadata_path: Path, timestamp_ms: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    wanted = candidate_item_ids(candidates)
    found: set[int] = set()
    events: list[dict[str, Any]] = []
    duplicate_metadata = 0
    missing_duration = 0
    missing_author = 0
    with metadata_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"video_id", "author_id", "upload_dt", "video_duration", "tag"}
        missing_columns = required - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"Metadata file is missing columns: {sorted(missing_columns)}")
        for row in reader:
            video_id = int(row["video_id"])
            if video_id not in wanted:
                continue
            if video_id in found:
                duplicate_metadata += 1
                continue
            found.add(video_id)
            author_raw = row.get("author_id", "")
            duration_raw = row.get("video_duration", "")
            if author_raw in (None, "") or not math.isfinite(float(author_raw)):
                missing_author += 1
                continue
            duration_is_missing = duration_raw in (None, "") or not math.isfinite(float(duration_raw))
            if duration_is_missing:
                missing_duration += 1
                duration = 0.0
            else:
                duration = float(duration_raw)
            if duration < 0:
                raise ValueError(f"Negative duration for video_id={video_id}: {duration}")
            fields: list[dict[str, Any]] = [
                {"name": "author_id", "value": str(int(float(author_raw)))},
                {"name": "tags", "value": normalize_tags(row.get("tag"))},
                {"name": "duration_ms", "value": duration},
                {"name": "duration_missing", "value": 1.0 if duration_is_missing else 0.0},
                {"name": "metadata_version", "value": "kuairand_pure_basic_v1"},
            ]
            if row.get("upload_dt"):
                fields.append({"name": "upload_date", "value": row["upload_dt"]})
            events.append(
                {
                    "event": "item",
                    "id": f"flr:item:{video_id}:gatec_hydration_v1",
                    "timestamp": timestamp_ms,
                    "item": f"krp:video:{video_id}",
                    "fields": fields,
                }
            )
    missing_ids = wanted - found
    summary = {
        "candidate_unique_items": len(wanted),
        "metadata_rows_emitted": len(events),
        "missing_metadata_ids": len(missing_ids),
        "duplicate_metadata_rows": duplicate_metadata,
        "missing_duration": missing_duration,
        "missing_author": missing_author,
    }
    if missing_ids or missing_author or duplicate_metadata:
        raise ValueError(f"Candidate metadata is not complete and unique: {summary}")
    events.sort(key=lambda event: int(str(event["item"]).removeprefix("krp:video:")))
    return events, summary


def post_batch(endpoint: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/feedback",
        data=json.dumps(events, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Metarank feedback HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach Metarank feedback endpoint: {exc.reason}") from exc
    payload = json.loads(body)
    if payload.get("status") != "ok" or int(payload.get("accepted", -1)) != len(events):
        raise RuntimeError(f"Metarank rejected metadata batch: {payload}")
    return payload


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")
    events, summary = build_item_events(args.candidates, args.metadata, args.timestamp_ms)
    write_jsonl(args.events_output, events)
    accepted = 0
    updated = 0
    batches = 0
    if not args.dry_run:
        for start in range(0, len(events), args.batch_size):
            response = post_batch(args.endpoint, events[start : start + args.batch_size])
            accepted += int(response["accepted"])
            updated += int(response.get("updated", 0))
            batches += 1
    manifest = {
        "status": "DRY_RUN_VALID" if args.dry_run else "VALID",
        "evidence_level": "E2",
        "candidate_files": [display_path(path) for path in args.candidates],
        "candidate_file_sha256": {display_path(path): sha256_file(path) for path in args.candidates},
        "metadata_file": display_path(args.metadata),
        "metadata_sha256": sha256_file(args.metadata),
        "events_file": display_path(args.events_output),
        "events_sha256": sha256_file(args.events_output),
        "timestamp_ms": args.timestamp_ms,
        "summary": summary,
        "api_batches": batches,
        "api_accepted": accepted,
        "api_updated": updated,
        "candidate_metadata_coverage": "PASS",
        "duration_missing_policy": "duration_ms=0 sentinel plus duration_missing=1",
        "claim_boundary": (
            "This artifact proves static metadata coverage for the selected offline cohorts. "
            "It does not use evaluation outcomes as model features or establish ranking lift."
        ),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Metarank metadata hydration: {manifest['status']}; "
        f"items={len(events)}, accepted={accepted}"
    )


if __name__ == "__main__":
    main()
