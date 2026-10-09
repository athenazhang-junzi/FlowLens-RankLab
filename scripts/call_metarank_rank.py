#!/usr/bin/env python3
"""Build FlowLens rank requests and optionally call a Metarank HTTP endpoint."""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any

from metarank_contract import PROJECT_ROOT, sha256_file, stable_hash, write_jsonl


OUTPUT_COLUMNS = [
    "request_id",
    "user_id",
    "video_id",
    "input_rank",
    "upstream_score",
    "metarank_rank",
    "metarank_score",
    "explain_features_json",
    "model_name",
    "response_took_ms",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--timestamp-ms", type=int, required=True)
    parser.add_argument("--upstream-run-id", default="gate3-3b42b7057a17")
    parser.add_argument("--strategy-version", default="metarank_flowlens_v0.1")
    parser.add_argument("--model", default="flowlens")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080")
    parser.add_argument("--max-requests", type=int, default=50)
    parser.add_argument(
        "--request-sampling",
        choices=["first", "hash"],
        default="first",
        help="Select the first eligible users or a deterministic hash sample.",
    )
    parser.add_argument("--sample-seed", type=int, default=20261009)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print progress every N requests, plus the first and final request.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--requests-output",
        type=Path,
        default=PROJECT_ROOT / "runs" / "integration" / "gateb-rank" / "requests.jsonl",
    )
    parser.add_argument(
        "--results-output",
        type=Path,
        default=PROJECT_ROOT / "runs" / "integration" / "gateb-rank" / "results.csv",
    )
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def parse_optional_float(row: dict[str, str], name: str) -> float | None:
    raw = row.get(name)
    if raw in (None, ""):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def build_requests(
    candidates_path: Path,
    *,
    split: str,
    timestamp_ms: int,
    upstream_run_id: str,
    strategy_version: str,
    model: str,
    max_requests: int,
    request_sampling: str = "first",
    sample_seed: int = 20261009,
) -> list[dict[str, Any]]:
    if max_requests < 0:
        raise ValueError("max_requests must be zero or positive")
    by_user: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    with candidates_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"user_id", "video_id", "multitask_score"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Candidate file is missing columns: {sorted(missing)}")
        for row in reader:
            user_id = str(row["user_id"])
            if user_id not in by_user:
                by_user[user_id] = []
            by_user[user_id].append(row)

    eligible_users = [user_id for user_id, rows in by_user.items() if len(rows) >= 2]
    if request_sampling == "hash":
        eligible_users.sort(
            key=lambda user_id: stable_hash(sample_seed, split, user_id, length=32)
        )
    if max_requests:
        eligible_users = eligible_users[:max_requests]

    requests: list[dict[str, Any]] = []
    for user_id in eligible_users:
        rows = by_user[user_id]
        if max_requests and len(requests) >= max_requests:
            break
        seen_items: set[str] = set()
        candidates: list[tuple[float, int, dict[str, str]]] = []
        for row in rows:
            item_id = str(row["video_id"])
            if item_id in seen_items:
                raise ValueError(f"Duplicate video_id={item_id} for user_id={user_id}")
            seen_items.add(item_id)
            score = float(row["multitask_score"])
            candidates.append((score, int(item_id), row))
        candidates.sort(key=lambda value: (-value[0], value[1]))

        request_id = (
            f"flr:rank:v0.1:{split}:"
            f"{stable_hash(user_id, split, model, upstream_run_id)}"
        )
        items: list[dict[str, Any]] = []
        for score, video_id, row in candidates:
            fields = [{"name": "relevancy", "value": score}]
            for source, target in [
                ("itemcf_score", "itemcf_score"),
                ("popularity_score", "popularity_score"),
            ]:
                value = parse_optional_float(row, source)
                if value is not None:
                    fields.append({"name": target, "value": value})
            items.append({"id": f"krp:video:{video_id}", "fields": fields})
        requests.append(
            {
                "id": request_id,
                "timestamp": timestamp_ms,
                "user": f"krp:user:{user_id}",
                "session": f"krp:inference:{user_id}:{split}",
                "fields": [
                    {"name": "dataset_split", "value": split},
                    {"name": "source_mode", "value": "logged_exposure_replay"},
                    {"name": "upstream_run_id", "value": upstream_run_id},
                    {"name": "strategy_version", "value": strategy_version},
                    {"name": "evidence_level", "value": "E3"},
                ],
                "items": items,
                "_flowlens": {
                    "user_id": user_id,
                    "model": model,
                    "input_order": [item["id"] for item in items],
                },
            }
        )
    if not requests:
        raise ValueError("No user has at least two unique candidates")
    return requests


def request_body(request: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in request.items() if key != "_flowlens"}


def post_rank(
    endpoint: str,
    model: str,
    request: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    quoted_model = urllib.parse.quote(model, safe="")
    url = f"{endpoint.rstrip('/')}/rank/{quoted_model}?explain=true"
    payload = json.dumps(request_body(request)).encode("utf-8")
    http_request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Metarank HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach Metarank endpoint {url}: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Metarank returned invalid JSON: {body[:500]}") from exc


def response_rows(
    request: dict[str, Any], response: dict[str, Any], model: str
) -> list[dict[str, Any]]:
    input_items = request["items"]
    input_ids = [item["id"] for item in input_items]
    output_items = response.get("items")
    if not isinstance(output_items, list):
        raise ValueError(f"Response for {request['id']} has no items list")
    output_ids = [str(item.get("item")) for item in output_items]
    if len(output_ids) != len(set(output_ids)):
        raise ValueError(f"Response for {request['id']} contains duplicate items")
    if set(output_ids) != set(input_ids) or len(output_ids) != len(input_ids):
        raise ValueError(
            f"Candidate conservation failed for {request['id']}: "
            f"input={len(input_ids)}, output={len(output_ids)}"
        )
    input_map = {item["id"]: item for item in input_items}
    user_id = request["_flowlens"]["user_id"]
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(output_items, start=1):
        item_id = str(item["item"])
        raw_video_id = item_id.removeprefix("krp:video:")
        upstream = next(
            field["value"]
            for field in input_map[item_id]["fields"]
            if field["name"] == "relevancy"
        )
        rows.append(
            {
                "request_id": request["id"],
                "user_id": user_id,
                "video_id": raw_video_id,
                "input_rank": input_ids.index(item_id) + 1,
                "upstream_score": upstream,
                "metarank_rank": rank,
                "metarank_score": item.get("score"),
                "explain_features_json": json.dumps(
                    item.get("features", []), ensure_ascii=False, sort_keys=True
                ),
                "model_name": model,
                "response_took_ms": response.get("took"),
            }
        )
    return rows


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return resolved.name


def main() -> None:
    args = parse_args()
    if args.progress_every < 1:
        raise ValueError("progress-every must be positive")
    requests = build_requests(
        args.candidates,
        split=args.split,
        timestamp_ms=args.timestamp_ms,
        upstream_run_id=args.upstream_run_id,
        strategy_version=args.strategy_version,
        model=args.model,
        max_requests=args.max_requests,
        request_sampling=args.request_sampling,
        sample_seed=args.sample_seed,
    )
    write_jsonl(args.requests_output, [request_body(request) for request in requests])

    manifest_path = args.manifest or args.requests_output.with_name("rank_manifest.json")
    manifest: dict[str, Any] = {
        "status": "DRY_RUN_VALID" if args.dry_run else "RUNNING",
        "evidence_level": "E3",
        "model": args.model,
        "split": args.split,
        "timestamp_ms": args.timestamp_ms,
        "request_count": len(requests),
        "candidate_count": sum(len(request["items"]) for request in requests),
        "request_sampling": args.request_sampling,
        "sample_seed": args.sample_seed,
        "candidates_file": display_path(args.candidates),
        "candidates_sha256": sha256_file(args.candidates),
        "requests_file": display_path(args.requests_output),
        "requests_sha256": sha256_file(args.requests_output),
        "claim_boundary": (
            "Rank requests cover logged-exposure candidates only. A valid response does not establish "
            "online causal lift or business impact."
        ),
    }
    if args.dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"Metarank rank adapter: DRY_RUN_VALID; requests={len(requests)}, "
            f"candidates={manifest['candidate_count']}"
        )
        print(f"Requests: {display_path(args.requests_output)}")
        return

    rows: list[dict[str, Any]] = []
    for index, request in enumerate(requests, start=1):
        response = post_rank(args.endpoint, args.model, request, args.timeout_seconds)
        rows.extend(response_rows(request, response, args.model))
        if index == 1 or index % args.progress_every == 0 or index == len(requests):
            print(f"  ranked {index}/{len(requests)} requests")
    write_results(args.results_output, rows)
    manifest.update(
        {
            "status": "VALID",
            "result_rows": len(rows),
            "results_file": display_path(args.results_output),
            "results_sha256": sha256_file(args.results_output),
            "candidate_conservation": "PASS",
        }
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Metarank rank adapter: VALID; requests={len(requests)}, rows={len(rows)}")
    print(f"Results: {display_path(args.results_output)}")


if __name__ == "__main__":
    main()
