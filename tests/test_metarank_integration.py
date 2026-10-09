#!/usr/bin/env python3
"""Contract and adapter tests for the FlowLens RankLab Gate B baseline."""

from __future__ import annotations

import copy
import sys
import pandas as pd
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from call_metarank_rank import build_requests, response_rows  # noqa: E402
from export_metarank_events import build_events  # noqa: E402
from hydrate_metarank_items import build_item_events  # noqa: E402
from evaluate_metarank_gatec import evaluate_models  # noqa: E402
from metarank_contract import load_contract, validate_events  # noqa: E402


FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "integration"


class MetarankEventExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_contract()
        cls.events, cls.summary = build_events(
            FIXTURE_DIR / "events.synthetic.csv",
            FIXTURE_DIR / "video_metadata.synthetic.csv",
            cls.contract,
            split="train",
            start_date=20220409,
            end_date=20220410,
            max_groups=0,
            minimum_items=2,
            upstream_run_id="fixture-gate3",
        )

    def test_synthetic_fixture_passes_contract(self) -> None:
        result = validate_events(self.events, self.contract)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(self.summary["groups_exported"], 2)
        self.assertEqual(result["event_counts"]["ranking"], 2)
        self.assertEqual(result["event_counts"]["item"], 5)

    def test_reserved_impression_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.events)
        interaction = next(event for event in invalid if event["event"] == "interaction")
        interaction["type"] = "impression"
        result = validate_events(invalid, self.contract)
        failed = {check["check"] for check in result["checks"] if check["status"] == "FAIL"}
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("reserved_impression_not_emitted", failed)

    def test_missing_parent_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.events)
        interaction = next(event for event in invalid if event["event"] == "interaction")
        interaction["ranking"] = "flr:rank:v0.1:train:missing"
        result = validate_events(invalid, self.contract)
        failed = {check["check"] for check in result["checks"] if check["status"] == "FAIL"}
        self.assertIn("interaction_parent_and_item_linkage", failed)


class MetarankRankAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.requests = build_requests(
            FIXTURE_DIR / "candidates.synthetic.csv",
            split="validation",
            timestamp_ms=1650239999999,
            upstream_run_id="fixture-gate3",
            strategy_version="fixture-v1",
            model="flowlens",
            max_requests=0,
        )

    def test_request_sorting_and_namespaces(self) -> None:
        self.assertEqual(len(self.requests), 2)
        first = self.requests[0]
        self.assertTrue(first["id"].startswith("flr:rank:v0.1:validation:"))
        self.assertEqual(first["user"], "krp:user:101")
        self.assertEqual(
            [item["id"] for item in first["items"]],
            ["krp:video:1001", "krp:video:1003", "krp:video:1002"],
        )

    def test_response_candidate_conservation(self) -> None:
        request = self.requests[0]
        response = {
            "took": 3,
            "items": [
                {"item": item["id"], "score": float(index), "features": []}
                for index, item in enumerate(reversed(request["items"]), start=1)
            ],
        }
        rows = response_rows(request, response, "flowlens")
        self.assertEqual(len(rows), len(request["items"]))
        self.assertEqual({row["video_id"] for row in rows}, {"1001", "1002", "1003"})

    def test_hash_sampling_is_deterministic(self) -> None:
        first = build_requests(
            FIXTURE_DIR / "candidates.synthetic.csv",
            split="validation",
            timestamp_ms=1650239999999,
            upstream_run_id="fixture-gate3",
            strategy_version="fixture-v1",
            model="flowlens",
            max_requests=1,
            request_sampling="hash",
            sample_seed=42,
        )
        second = build_requests(
            FIXTURE_DIR / "candidates.synthetic.csv",
            split="validation",
            timestamp_ms=1650239999999,
            upstream_run_id="fixture-gate3",
            strategy_version="fixture-v1",
            model="flowlens",
            max_requests=1,
            request_sampling="hash",
            sample_seed=42,
        )
        self.assertEqual(first, second)

    def test_missing_response_candidate_is_rejected(self) -> None:
        request = self.requests[0]
        response = {
            "took": 3,
            "items": [{"item": request["items"][0]["id"], "score": 1.0}],
        }
        with self.assertRaisesRegex(ValueError, "Candidate conservation failed"):
            response_rows(request, response, "flowlens")


class MetarankMetadataHydrationTests(unittest.TestCase):
    def test_fixture_candidates_have_complete_metadata(self) -> None:
        events, summary = build_item_events(
            [FIXTURE_DIR / "candidates.synthetic.csv"],
            FIXTURE_DIR / "video_metadata.synthetic.csv",
            1650207850711,
        )
        self.assertEqual(summary["candidate_unique_items"], 5)
        self.assertEqual(summary["missing_metadata_ids"], 0)
        self.assertEqual(summary["missing_duration"], 0)
        self.assertEqual(len(events), 5)
        self.assertEqual({event["event"] for event in events}, {"item"})
        self.assertEqual(
            {
                next(
                    field["value"]
                    for field in event["fields"]
                    if field["name"] == "duration_missing"
                )
                for event in events
            },
            {0.0},
        )


class GateCEvaluationTests(unittest.TestCase):
    def test_shared_cohort_evaluation_preserves_candidates(self) -> None:
        candidates = pd.DataFrame(
            [
                {"user_id": 1, "video_id": 10, "long_view": 1, "is_click": 1, "is_hate": 0, "multitask_score": 0.1, "author_id": 1, "tag": "a"},
                {"user_id": 1, "video_id": 11, "long_view": 0, "is_click": 0, "is_hate": 0, "multitask_score": 0.9, "author_id": 2, "tag": "b"},
                {"user_id": 2, "video_id": 20, "long_view": 1, "is_click": 1, "is_hate": 0, "multitask_score": 0.2, "author_id": 3, "tag": "c"},
                {"user_id": 2, "video_id": 21, "long_view": 0, "is_click": 0, "is_hate": 1, "multitask_score": 0.8, "author_id": 4, "tag": "d"},
            ]
        )
        rankings = pd.DataFrame(
            [
                {"user_id": 1, "video_id": 10, "metarank_rank": 1, "metarank_score": 1.0},
                {"user_id": 1, "video_id": 11, "metarank_rank": 2, "metarank_score": 0.0},
                {"user_id": 2, "video_id": 20, "metarank_rank": 1, "metarank_score": 1.0},
                {"user_id": 2, "video_id": 21, "metarank_rank": 2, "metarank_score": 0.0},
            ]
        )
        metrics, deltas, users = evaluate_models(
            candidates,
            rankings,
            minimum_candidates=2,
            bootstrap_repetitions=20,
            seed=42,
        )
        self.assertEqual(metrics["candidate_pairs"].tolist(), [4, 4])
        self.assertEqual(metrics["eligible_users"].tolist(), [2, 2])
        self.assertGreater(
            float(deltas.set_index("metric").loc["ndcg_at_5", "metarank_minus_baseline"]),
            0,
        )
        self.assertEqual(len(users), 4)


if __name__ == "__main__":
    unittest.main()
