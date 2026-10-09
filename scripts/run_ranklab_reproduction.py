#!/usr/bin/env python3
"""Run a reproducible FlowLens RankLab smoke or Gate C pipeline."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metarank_contract import PROJECT_ROOT, sha256_file


LOCK_PATH = PROJECT_ROOT / "config" / "integration" / "runtime_lock.json"
COMPOSE_PATH = PROJECT_ROOT / "services" / "metarank" / "compose.yml"
REPORT_PATH = PROJECT_ROOT / "reports" / "integration" / "gated_reproduction_latest.json"
VALIDATION_CANDIDATES = PROJECT_ROOT / "reports" / "gate3" / "validation_candidate_scores.csv"
STANDARD_TEST_CANDIDATES = PROJECT_ROOT / "reports" / "gate3" / "standard_test_candidate_scores.csv"
RANDOM_TEST_CANDIDATES = PROJECT_ROOT / "reports" / "gate3" / "random_sensitivity_candidate_scores.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "gatec"), default="smoke")
    parser.add_argument(
        "--keep-service",
        action="store_true",
        help="Leave the reproduced Metarank service running after validation.",
    )
    parser.add_argument(
        "--publish-livelab",
        action="store_true",
        help="Promote a successful gatec payload to the tracked LiveLab files.",
    )
    parser.add_argument("--docker-bin", type=Path)
    parser.add_argument("--startup-timeout-seconds", type=int, default=300)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return path.name


def display_command(command: list[str]) -> list[str]:
    displayed: list[str] = []
    for token in command:
        candidate = Path(token)
        if candidate.is_absolute():
            displayed.append(display_path(candidate))
        else:
            displayed.append(token)
    return displayed


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_step(
    report: dict[str, Any],
    name: str,
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> None:
    print(f"\n==> {name}", flush=True)
    started = utc_now()
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
    step = {
        "name": name,
        "command": display_command(command),
        "started_at": started,
        "finished_at": utc_now(),
        "exit_code": result.returncode,
        "status": "PASS" if result.returncode == 0 else "FAIL",
    }
    report["steps"].append(step)
    write_report(report)
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {name} (exit {result.returncode})")


def resolve_docker(explicit: Path | None) -> str:
    candidates = []
    if explicit:
        candidates.append(str(explicit))
    if os.environ.get("DOCKER_BIN"):
        candidates.append(os.environ["DOCKER_BIN"])
    discovered = shutil.which("docker")
    if discovered:
        candidates.append(discovered)
    candidates.append("/Applications/Docker.app/Contents/Resources/bin/docker")
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("Docker CLI not found. Start Docker Desktop or pass --docker-bin.")


def wait_for_service(endpoint: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not contacted"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{endpoint}/health", timeout=3) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise TimeoutError(f"Metarank did not become ready within {timeout_seconds}s: {last_error}")


def require_inputs(profile: str) -> list[Path]:
    required = [
        LOCK_PATH,
        COMPOSE_PATH,
        PROJECT_ROOT / "services" / "metarank" / "config.yml",
        PROJECT_ROOT / "config" / "integration" / "metarank_event_contract.json",
        PROJECT_ROOT / "scripts" / "run_ranklab_reproduction.py",
        PROJECT_ROOT / "scripts" / "metarank_contract.py",
        PROJECT_ROOT / "scripts" / "export_metarank_events.py",
        PROJECT_ROOT / "scripts" / "validate_metarank_events.py",
        PROJECT_ROOT / "scripts" / "hydrate_metarank_items.py",
        PROJECT_ROOT / "scripts" / "call_metarank_rank.py",
        PROJECT_ROOT / "scripts" / "evaluate_metarank_gatec.py",
        PROJECT_ROOT / "scripts" / "build_gatec_livelab_payload.py",
        PROJECT_ROOT / "data" / "processed" / "events" / "log_standard_4_08_to_4_21_pure_clean.csv",
        PROJECT_ROOT / "data" / "extracted" / "KuaiRand-Pure" / "data" / "video_features_basic_pure.csv",
        VALIDATION_CANDIDATES,
        PROJECT_ROOT / "reports" / "gate3" / "run_manifest.json",
        PROJECT_ROOT / "config" / "gate4_strategies.json",
    ]
    if profile == "gatec":
        required.extend([STANDARD_TEST_CANDIDATES, RANDOM_TEST_CANDIDATES])
    missing = [path for path in required if not path.is_file()]
    if missing:
        formatted = ", ".join(display_path(path) for path in missing)
        raise FileNotFoundError(f"Required inputs are missing: {formatted}")
    return required


def main() -> None:
    args = parse_args()
    if args.publish_livelab and args.profile != "gatec":
        raise ValueError("--publish-livelab is only allowed with --profile gatec")
    if args.startup_timeout_seconds < 30:
        raise ValueError("--startup-timeout-seconds must be at least 30")

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    expected_python = lock["python"]["required_major_minor"]
    active_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if active_python != expected_python:
        raise RuntimeError(
            f"runtime_lock.json requires Python {expected_python}; active interpreter is {active_python}"
        )
    required_inputs = require_inputs(args.profile)
    docker = resolve_docker(args.docker_bin)
    sample = lock["sampling"]
    training_groups = int(sample[f"{args.profile}_training_groups"])
    validation_requests = int(sample[f"{args.profile}_validation_requests"])
    seed = int(sample["seed"])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"gated-{args.profile}-{timestamp}"
    run_dir = PROJECT_ROOT / "runs" / "integration" / run_id
    export_dir = run_dir / "training"
    hydration_dir = run_dir / "hydration"
    ranking_dir = run_dir / "ranking"
    evaluation_dir = run_dir / "evaluation"
    payload_dir = run_dir / "livelab"
    for path in [export_dir, hydration_dir, ranking_dir, evaluation_dir, payload_dir]:
        path.mkdir(parents=True, exist_ok=False)

    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()
    git_dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
        ).strip()
    )
    report: dict[str, Any] = {
        "schema_version": "flowlens_ranklab_reproduction_v1",
        "run_id": run_id,
        "status": "RUNNING",
        "profile": args.profile,
        "started_at": utc_now(),
        "git": {"commit": git_commit, "dirty": git_dirty},
        "runtime_lock": display_path(LOCK_PATH),
        "runtime_lock_sha256": sha256_file(LOCK_PATH),
        "parameters": {
            "training_groups": training_groups,
            "validation_requests": validation_requests,
            "sampling": "hash",
            "seed": seed,
            "publish_livelab": args.publish_livelab,
        },
        "inputs": {
            display_path(path): sha256_file(path) for path in required_inputs
        },
        "output_directory": display_path(run_dir),
        "steps": [],
        "claim_boundary": lock["evidence_boundary"],
    }
    write_report(report)

    python = sys.executable
    endpoint = "http://127.0.0.1:8080"
    compose = [docker, "compose", "-f", str(COMPOSE_PATH)]
    docker_env = os.environ.copy()
    events_path = export_dir / "events.jsonl"
    export_manifest = export_dir / "manifest.json"
    hydration_manifest = hydration_dir / "manifest.json"
    rank_manifest = ranking_dir / "manifest.json"
    service_started = False

    try:
        run_step(
            report,
            "export_training_events",
            [
                python,
                "scripts/export_metarank_events.py",
                "--output",
                str(events_path),
                "--manifest",
                str(export_manifest),
                "--max-groups",
                str(training_groups),
                "--group-sampling",
                "hash",
                "--sample-seed",
                str(seed),
            ],
        )
        run_step(
            report,
            "validate_event_contract",
            [
                python,
                "scripts/validate_metarank_events.py",
                "--events",
                str(events_path),
                "--report",
                str(export_dir / "validation.json"),
            ],
        )
        run_step(report, "validate_compose", compose + ["config", "--quiet"])
        docker_env["METARANK_EVENTS_FILE"] = str(events_path.resolve())
        run_step(
            report,
            "start_and_train_metarank",
            compose + ["up", "-d", "--force-recreate"],
            env=docker_env,
        )
        service_started = True
        print("\n==> wait_for_metarank", flush=True)
        wait_started = utc_now()
        wait_for_service(endpoint, args.startup_timeout_seconds)
        report["steps"].append(
            {
                "name": "wait_for_metarank",
                "started_at": wait_started,
                "finished_at": utc_now(),
                "status": "PASS",
            }
        )
        container_id = subprocess.check_output(
            compose + ["ps", "-q", "metarank"],
            cwd=PROJECT_ROOT,
            env=docker_env,
            text=True,
        ).strip()
        report["metarank"] = {
            "locked_image": lock["metarank"]["image"],
            "platform": lock["metarank"]["platform"],
            "container_id": container_id[:12],
            "endpoint": endpoint,
        }
        write_report(report)

        hydration_candidates = [VALIDATION_CANDIDATES]
        if args.profile == "gatec":
            hydration_candidates.extend([STANDARD_TEST_CANDIDATES, RANDOM_TEST_CANDIDATES])
        hydrate_command = [python, "scripts/hydrate_metarank_items.py"]
        for candidate in hydration_candidates:
            hydrate_command.extend(["--candidates", str(candidate)])
        hydrate_command.extend(
            [
                "--timestamp-ms",
                str(lock["timestamps_ms"]["metadata_hydration"]),
                "--endpoint",
                endpoint,
                "--events-output",
                str(hydration_dir / "item_events.jsonl"),
                "--manifest",
                str(hydration_manifest),
            ]
        )
        run_step(report, "hydrate_candidate_metadata", hydrate_command)
        run_step(
            report,
            "rank_validation_cohort",
            [
                python,
                "scripts/call_metarank_rank.py",
                "--candidates",
                str(VALIDATION_CANDIDATES),
                "--split",
                "validation",
                "--timestamp-ms",
                str(lock["timestamps_ms"]["validation_ranking"]),
                "--max-requests",
                str(validation_requests),
                "--request-sampling",
                "hash",
                "--sample-seed",
                str(seed),
                "--endpoint",
                endpoint,
                "--requests-output",
                str(ranking_dir / "requests.jsonl"),
                "--results-output",
                str(ranking_dir / "results.csv"),
                "--manifest",
                str(rank_manifest),
            ],
        )
        run_step(
            report,
            "evaluate_shared_cohort",
            [
                python,
                "scripts/evaluate_metarank_gatec.py",
                "--candidates",
                str(VALIDATION_CANDIDATES),
                "--rankings",
                str(ranking_dir / "results.csv"),
                "--rank-manifest",
                str(rank_manifest),
                "--hydration-manifest",
                str(hydration_manifest),
                "--split",
                "validation",
                "--output-dir",
                str(evaluation_dir),
                "--random-seed",
                str(seed),
            ],
        )
        run_step(
            report,
            "build_livelab_payload",
            [
                python,
                "scripts/build_gatec_livelab_payload.py",
                "--evaluation-dir",
                str(evaluation_dir),
                "--training-manifest",
                str(export_manifest),
                "--hydration-manifest",
                str(hydration_manifest),
                "--output-json",
                str(payload_dir / "ranklab_offline_run.json"),
                "--output-js",
                str(payload_dir / "ranklab_offline_run.js"),
            ],
        )
        if args.publish_livelab:
            canonical_json = PROJECT_ROOT / "reports" / "integration" / "gatec_livelab_payload.json"
            canonical_js = PROJECT_ROOT / "apps" / "livelab" / "data" / "ranklab_offline_run.js"
            shutil.copyfile(payload_dir / "ranklab_offline_run.json", canonical_json)
            shutil.copyfile(payload_dir / "ranklab_offline_run.js", canonical_js)
            report["published_livelab"] = {
                "json": display_path(canonical_json),
                "js": display_path(canonical_js),
            }

        evaluation = json.loads((evaluation_dir / "manifest.json").read_text(encoding="utf-8"))
        report["evaluation"] = {
            "manifest": display_path(evaluation_dir / "manifest.json"),
            "run_id": evaluation["run_id"],
            "status": evaluation["status"],
            "decision": evaluation["decision"],
            "request_count": evaluation["sampling"]["request_count"],
            "candidate_count": evaluation["sampling"]["candidate_count"],
        }
        canonical_files = {
            "metrics": PROJECT_ROOT / "reports" / "integration" / "gatec-validation" / "metrics.csv",
            "paired_deltas": PROJECT_ROOT
            / "reports"
            / "integration"
            / "gatec-validation"
            / "paired_deltas.csv",
        }
        reproduced_files = {
            "metrics": evaluation_dir / "metrics.csv",
            "paired_deltas": evaluation_dir / "paired_deltas.csv",
        }
        comparison = {
            name: {
                "canonical_sha256": sha256_file(canonical_files[name]),
                "reproduced_sha256": sha256_file(reproduced_files[name]),
                "match": sha256_file(canonical_files[name])
                == sha256_file(reproduced_files[name]),
            }
            for name in canonical_files
        }
        comparison["decision"] = {
            "canonical": "ITERATE_AND_RETEST",
            "reproduced": evaluation["decision"],
            "match": evaluation["decision"] == "ITERATE_AND_RETEST",
        }
        report["canonical_comparison"] = comparison
        if not all(item["match"] for item in comparison.values()):
            raise RuntimeError("Reproduced Gate C outputs do not match the canonical public result")
        report["status"] = "PASS"
        report["finished_at"] = utc_now()
        write_report(report)
        print(
            f"\nRankLab reproduction PASS: profile={args.profile}, "
            f"decision={evaluation['decision']}, run={run_id}",
            flush=True,
        )
    except Exception as exc:
        report["status"] = "FAIL"
        report["finished_at"] = utc_now()
        report["error"] = str(exc)
        write_report(report)
        raise
    finally:
        if service_started and not args.keep_service:
            subprocess.run(
                compose + ["down"],
                cwd=PROJECT_ROOT,
                env=docker_env,
                check=False,
            )


if __name__ == "__main__":
    main()
