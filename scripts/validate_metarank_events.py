#!/usr/bin/env python3
"""Validate a FlowLens Metarank JSONL export against the frozen contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from metarank_contract import (
    DEFAULT_CONTRACT_PATH,
    PROJECT_ROOT,
    load_contract,
    read_jsonl,
    sha256_file,
    validate_events,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "reports" / "integration" / "gateb_event_validation.json",
    )
    return parser.parse_args()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return resolved.name


def main() -> None:
    args = parse_args()
    events = read_jsonl(args.events)
    payload = validate_events(events, load_contract(args.contract))
    payload.update(
        {
            "events_file": display_path(args.events),
            "events_sha256": sha256_file(args.events),
            "event_count": len(events),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Metarank event validation: {payload['status']} ({len(payload['checks'])} checks)")
    print(f"Events: {len(events)}; report: {display_path(args.report)}")
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
