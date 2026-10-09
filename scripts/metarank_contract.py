#!/usr/bin/env python3
"""Shared helpers for the FlowLens to Metarank event contract."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = PROJECT_ROOT / "config" / "integration" / "metarank_event_contract.json"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(*parts: object, length: int = 16) -> str:
    canonical = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def load_contract(path: Path = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def event_fields(event: dict[str, Any]) -> dict[str, Any]:
    return {field["name"]: field.get("value") for field in event.get("fields", [])}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
    return events


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def validate_events(
    events: list[dict[str, Any]], contract: dict[str, Any]
) -> dict[str, Any]:
    """Validate structural, linkage, time, and candidate invariants."""

    checks: list[dict[str, str]] = []
    type_counts = Counter(str(event.get("event")) for event in events)
    allowed_types = {"item", "user", "ranking", "interaction"}
    invalid_types = sorted(set(type_counts) - allowed_types)
    checks.append(_check("event_types_supported", not invalid_types, f"invalid={invalid_types}"))

    ids = [event.get("id") for event in events]
    missing_ids = sum(event_id in (None, "") for event_id in ids)
    duplicate_ids = len(ids) - len(set(ids))
    checks.append(
        _check(
            "event_ids_are_globally_unique",
            missing_ids == 0 and duplicate_ids == 0,
            f"events={len(ids)}, missing={missing_ids}, duplicates={duplicate_ids}",
        )
    )

    namespaces = contract["namespaces"]
    namespace_errors: list[str] = []
    item_events: dict[str, dict[str, Any]] = {}
    rankings: dict[str, dict[str, Any]] = {}
    interactions: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event")
        if event_type == "item":
            item_id = str(event.get("item", ""))
            if not item_id.startswith(namespaces["item"]):
                namespace_errors.append(f"item:{event.get('id')}")
            item_events[item_id] = event
        elif event_type == "ranking":
            if not str(event.get("id", "")).startswith(namespaces["ranking"]):
                namespace_errors.append(f"ranking:{event.get('id')}")
            if not str(event.get("user", "")).startswith(namespaces["user"]):
                namespace_errors.append(f"ranking_user:{event.get('id')}")
            if not str(event.get("session", "")).startswith(namespaces["session"]):
                namespace_errors.append(f"ranking_session:{event.get('id')}")
            rankings[str(event.get("id"))] = event
        elif event_type == "interaction":
            if not str(event.get("id", "")).startswith(namespaces["interaction"]):
                namespace_errors.append(f"interaction:{event.get('id')}")
            if not str(event.get("user", "")).startswith(namespaces["user"]):
                namespace_errors.append(f"interaction_user:{event.get('id')}")
            if not str(event.get("item", "")).startswith(namespaces["item"]):
                namespace_errors.append(f"interaction_item:{event.get('id')}")
            interactions.append(event)

    checks.append(
        _check(
            "namespaces_match_contract",
            not namespace_errors,
            f"errors={namespace_errors[:5]}, total={len(namespace_errors)}",
        )
    )

    candidate_errors: list[str] = []
    missing_item_events: set[str] = set()
    forbidden_feature_names = {"long_view", "is_click", "is_hate", "play_time_ms"}
    leaked_features: set[str] = set()
    ranking_splits: set[str] = set()

    for ranking_id, ranking in rankings.items():
        items = ranking.get("items", [])
        item_ids = [str(item.get("id", "")) for item in items]
        if len(item_ids) < int(contract["replay_grouping"]["minimum_unique_items"]):
            candidate_errors.append(f"{ranking_id}:too_few_items")
        if len(item_ids) != len(set(item_ids)):
            candidate_errors.append(f"{ranking_id}:duplicate_items")
        for item_id in item_ids:
            if not item_id.startswith(namespaces["item"]):
                candidate_errors.append(f"{ranking_id}:bad_item_namespace")
            if item_id not in item_events:
                missing_item_events.add(item_id)
        ranking_field_names = set(event_fields(ranking))
        ranking_splits.add(str(event_fields(ranking).get("dataset_split", "")))
        leaked_features.update(ranking_field_names & forbidden_feature_names)
        for item in items:
            leaked_features.update(set(event_fields(item)) & forbidden_feature_names)

    checks.append(
        _check(
            "ranking_candidates_valid",
            not candidate_errors,
            f"rankings={len(rankings)}, errors={candidate_errors[:5]}",
        )
    )
    checks.append(
        _check(
            "item_event_exists_for_every_candidate",
            not missing_item_events,
            f"missing={sorted(missing_item_events)[:5]}, total={len(missing_item_events)}",
        )
    )
    checks.append(
        _check(
            "forbidden_outcomes_not_ranking_features",
            not leaked_features,
            f"leaked={sorted(leaked_features)}",
        )
    )

    linkage_errors: list[str] = []
    temporal_errors: list[str] = []
    reserved_types: list[str] = []
    for interaction in interactions:
        parent_id = str(interaction.get("ranking", ""))
        parent = rankings.get(parent_id)
        if parent is None:
            linkage_errors.append(f"{interaction.get('id')}:missing_parent")
            continue
        parent_items = {str(item.get("id")) for item in parent.get("items", [])}
        if str(interaction.get("item")) not in parent_items:
            linkage_errors.append(f"{interaction.get('id')}:item_not_in_parent")
        try:
            if int(interaction["timestamp"]) <= int(parent["timestamp"]):
                temporal_errors.append(str(interaction.get("id")))
        except (KeyError, TypeError, ValueError):
            temporal_errors.append(str(interaction.get("id")))
        if interaction.get("type") in set(contract["forbidden_interaction_types"]):
            reserved_types.append(str(interaction.get("id")))

    checks.append(
        _check(
            "interaction_parent_and_item_linkage",
            not linkage_errors,
            f"errors={linkage_errors[:5]}, total={len(linkage_errors)}",
        )
    )
    checks.append(
        _check(
            "ranking_precedes_its_interactions",
            not temporal_errors,
            f"errors={temporal_errors[:5]}, total={len(temporal_errors)}",
        )
    )
    checks.append(
        _check(
            "reserved_impression_not_emitted",
            not reserved_types,
            f"events={reserved_types[:5]}, total={len(reserved_types)}",
        )
    )

    timestamps_valid = True
    out_of_order = 0
    previous: int | None = None
    for event in events:
        try:
            current = int(event["timestamp"])
        except (KeyError, TypeError, ValueError):
            timestamps_valid = False
            continue
        if previous is not None and current < previous:
            out_of_order += 1
        previous = current
    checks.append(
        _check(
            "event_stream_is_timestamp_sorted",
            timestamps_valid and out_of_order == 0,
            f"parseable={timestamps_valid}, out_of_order={out_of_order}",
        )
    )

    overall = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    return {
        "status": overall,
        "contract_id": contract["contract_id"],
        "event_counts": dict(sorted(type_counts.items())),
        "ranking_splits": sorted(ranking_splits),
        "checks": checks,
        "claim_boundary": contract["claim_boundary"],
    }
