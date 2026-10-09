#!/usr/bin/env python3
"""Verify the static, publishable FlowLens RankLab release surface."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from metarank_contract import PROJECT_ROOT, sha256_file


LOCK_PATH = PROJECT_ROOT / "config" / "integration" / "runtime_lock.json"
COMPOSE_PATH = PROJECT_ROOT / "services" / "metarank" / "compose.yml"
THIRD_PARTY_PATH = PROJECT_ROOT / "services" / "metarank" / "THIRD_PARTY.md"
PAYLOAD_JSON = PROJECT_ROOT / "reports" / "integration" / "gatec_livelab_payload.json"
PAYLOAD_JS = PROJECT_ROOT / "apps" / "livelab" / "data" / "ranklab_offline_run.js"
GATEC_MANIFEST = PROJECT_ROOT / "reports" / "integration" / "gatec-validation" / "manifest.json"
REPRODUCTION_MANIFEST = (
    PROJECT_ROOT / "reports" / "integration" / "gated_reproduction_latest.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-python-mismatch",
        action="store_true",
        help="Report but do not fail when the active Python major/minor differs from the lock.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    failures: list[str] = []
    checks: list[str] = []
    required = [
        LOCK_PATH,
        COMPOSE_PATH,
        THIRD_PARTY_PATH,
        PAYLOAD_JSON,
        PAYLOAD_JS,
        GATEC_MANIFEST,
        REPRODUCTION_MANIFEST,
        PROJECT_ROOT / "LICENSE",
        PROJECT_ROOT / "Makefile",
        PROJECT_ROOT / "docs" / "integration" / "04-reproduction-and-release.md",
        PROJECT_ROOT / ".github" / "workflows" / "ranklab-check.yml",
        PROJECT_ROOT / "scripts" / "run_ranklab_reproduction.py",
        PROJECT_ROOT / "apps" / "livelab" / "index.html",
        PROJECT_ROOT / "apps" / "livelab" / "app.js",
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.is_file()]
    if missing:
        failures.append("missing required release files: " + ", ".join(missing))
    else:
        checks.append("required_release_files")

    if not missing:
        lock = load_json(LOCK_PATH)
        expected_python = lock["python"]["required_major_minor"]
        active_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if active_python != expected_python and not args.allow_python_mismatch:
            failures.append(
                f"Python mismatch: lock requires {expected_python}, active interpreter is {active_python}"
            )
        else:
            checks.append("python_version")

        image = lock["metarank"]["image"]
        compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
        third_party_text = THIRD_PARTY_PATH.read_text(encoding="utf-8")
        digest = image.split("@", 1)[1]
        if image not in compose_text:
            failures.append("Compose image does not match runtime_lock.json")
        else:
            checks.append("metarank_image_lock")
        if digest not in third_party_text:
            failures.append("THIRD_PARTY.md does not contain the locked Metarank digest")
        else:
            checks.append("third_party_digest")

        payload = load_json(PAYLOAD_JSON)
        js_text = PAYLOAD_JS.read_text(encoding="utf-8").strip()
        match = re.fullmatch(r"window\.rankLabOfflineRun\s*=\s*(\{.*\});", js_text, re.DOTALL)
        if not match or json.loads(match.group(1)) != payload:
            failures.append("LiveLab JS payload does not exactly match the canonical JSON payload")
        else:
            checks.append("livelab_payload_parity")

        gatec = load_json(GATEC_MANIFEST)
        if gatec.get("status") != "VALID" or gatec.get("decision") != "ITERATE_AND_RETEST":
            failures.append("Canonical Gate C manifest is not VALID/ITERATE_AND_RETEST")
        else:
            checks.append("gatec_manifest_status")

        reproduction = load_json(REPRODUCTION_MANIFEST)
        comparison = reproduction.get("canonical_comparison", {})
        comparison_matches = comparison and all(
            item.get("match") is True for item in comparison.values()
        )
        if (
            reproduction.get("status") != "PASS"
            or reproduction.get("profile") != "gatec"
            or not comparison_matches
        ):
            failures.append("Latest full Gate D reproduction is not PASS or does not match Gate C")
        else:
            checks.append("gate_d_full_reproduction")
        runner_path = PROJECT_ROOT / "scripts" / "run_ranklab_reproduction.py"
        if reproduction.get("inputs", {}).get("scripts/run_ranklab_reproduction.py") != sha256_file(
            runner_path
        ):
            failures.append("Gate D reproduction does not reference the current runner hash")
        else:
            checks.append("gate_d_runner_lineage")

        lineage = payload.get("lineage", {})
        expected_hashes = {
            "evaluation_manifest_sha256": sha256_file(GATEC_MANIFEST),
            "metrics_sha256": sha256_file(GATEC_MANIFEST.parent / "metrics.csv"),
            "paired_deltas_sha256": sha256_file(GATEC_MANIFEST.parent / "paired_deltas.csv"),
        }
        for key, expected in expected_hashes.items():
            if lineage.get(key) != expected:
                failures.append(f"LiveLab lineage mismatch for {key}")
        if not any("lineage mismatch" in failure for failure in failures):
            checks.append("livelab_public_lineage")

    payload = {
        "status": "PASS" if not failures else "FAIL",
        "checks_passed": checks,
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
