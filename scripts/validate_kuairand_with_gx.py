#!/usr/bin/env python3
"""Run the FlowLens Gate 2 contract with Great Expectations.

The script validates the cleaned KuaiRand-Pure event views. It deliberately
keeps source quirks such as event-key collisions and nullable derived labels;
only stable, blocking rules are encoded as expectations.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Any

import great_expectations as gx
import great_expectations.expectations as gxe
import pandas as pd
from great_expectations import ExpectationSuite, ValidationDefinition


LOG_SPECS = {
    "standard_early": {
        "filename": "log_standard_4_08_to_4_21_pure_clean.csv",
        "is_rand": 0,
        "collection_policy": "standard",
    },
    "standard_late": {
        "filename": "log_standard_4_22_to_5_08_pure_clean.csv",
        "is_rand": 0,
        "collection_policy": "standard",
    },
    "random_late": {
        "filename": "log_random_4_22_to_5_08_pure_clean.csv",
        "is_rand": 1,
        "collection_policy": "random",
    },
}

NONNEGATIVE_COLUMNS = [
    "time_ms",
    "play_time_ms",
    "duration_ms",
    "profile_stay_time",
    "comment_stay_time",
]


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events-dir",
        type=Path,
        default=project_root / "data" / "processed" / "events",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=project_root / "config" / "data_contract.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project_root / "reports" / "data-quality" / "cleaning_manifest.json",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=project_root / "reports" / "data-quality" / "gx_validation_results.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project_root / "reports" / "data-quality" / "GX-数据契约验证.md",
    )
    return parser.parse_args()


def build_suite(
    *,
    name: str,
    required_columns: list[str],
    binary_columns: list[str],
    expected_rows: int,
    expected_is_rand: int,
    expected_policy: str,
) -> ExpectationSuite:
    suite = ExpectationSuite(
        name=f"kuairand_pure_{name}_gate2",
        meta={
            "contract_id": "kuairand_pure_v1",
            "scope": "stable blocking rules on cleaned event views",
        },
    )
    suite.add_expectation(
        gxe.ExpectTableRowCountToBeBetween(
            min_value=expected_rows,
            max_value=expected_rows,
            description="Clean row count must reconcile to the cleaning manifest.",
        )
    )
    for column in required_columns:
        suite.add_expectation(gxe.ExpectColumnToExist(column=column))

    for column in ["user_id", "video_id", "date", "time_ms", "is_rand"]:
        suite.add_expectation(gxe.ExpectColumnValuesToNotBeNull(column=column))

    for column in binary_columns:
        suite.add_expectation(
            gxe.ExpectColumnValuesToBeInSet(column=column, value_set=[0, 1])
        )

    for column in NONNEGATIVE_COLUMNS:
        suite.add_expectation(
            gxe.ExpectColumnValuesToBeBetween(column=column, min_value=0)
        )

    suite.add_expectation(
        gxe.ExpectColumnValuesToBeInSet(column="is_rand", value_set=[expected_is_rand])
    )
    suite.add_expectation(
        gxe.ExpectColumnValuesToBeInSet(column="source_log", value_set=[name])
    )
    suite.add_expectation(
        gxe.ExpectColumnValuesToBeInSet(
            column="collection_policy", value_set=[expected_policy]
        )
    )
    suite.add_expectation(
        gxe.ExpectCompoundColumnsToBeUnique(
            column_list=required_columns,
            ignore_row_if="never",
            description="Exact source-row duplicates must already be removed in the analysis view.",
        )
    )
    return suite


def validate_frame(
    *, name: str, frame: pd.DataFrame, suite: ExpectationSuite, context: Any
) -> dict[str, Any]:
    datasource = context.data_sources.add_pandas(name=f"pandas_{name}")
    asset = datasource.add_dataframe_asset(name=f"events_{name}")
    batch_definition = asset.add_batch_definition_whole_dataframe(name="whole_frame")
    suite = context.suites.add(suite)
    validation = ValidationDefinition(
        name=f"validate_{name}", data=batch_definition, suite=suite
    )
    validation = context.validation_definitions.add(validation)
    result = validation.run(batch_parameters={"dataframe": frame})
    return result.describe_dict()


def failure_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for expectation in result["expectations"]:
        if expectation["success"]:
            continue
        details = expectation.get("result", {})
        failures.append(
            {
                "expectation_type": expectation["expectation_type"],
                "column": expectation.get("kwargs", {}).get("column"),
                "unexpected_count": details.get("unexpected_count"),
                "unexpected_percent": details.get("unexpected_percent"),
            }
        )
    return failures


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Great Expectations 数据契约验证",
        "",
        f"总结果：**{'PASS' if payload['success'] else 'FAIL'}**。",
        "",
        "该验证只编码稳定、可阻断的规则。候选事件键冲突、零时长和官方长播公式差异属于已知质量标记，不被静默删除或改写。",
        "",
        "| 日志 | 行数 | 期望数 | GX expectations | 失败数 | 结果 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, result in payload["logs"].items():
        stats = result["statistics"]
        lines.append(
            f"| {name} | {result['rows']:,} | {result['expected_rows']:,} | "
            f"{stats['evaluated_expectations']} | {stats['unsuccessful_expectations']} | "
            f"{'PASS' if result['success'] else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "## 阻断规则",
            "",
            "- 清洗行数与 manifest 精确一致。",
            "- 必需事件字段全部存在；核心 ID 与时间字段非空。",
            "- 所有二元标签只能取 0/1。",
            "- 时间戳与播放／停留时长不得为负。",
            "- `is_rand`、`source_log`、`collection_policy` 与文件身份一致。",
            "- 清洗视图内不再存在完全相同的原始事件行。",
            "",
            "## 已知但不阻断",
            "",
            "- `user_id + video_id + time_ms` 的非完全相同冲突会保留并打标，因为公开数据无法证明哪条才是错误记录。",
            "- `duration_ms = 0` 的事件保留，相关公式标签设为不可验证。",
            "- `long_view` 保留官方标签；派生公式只用于敏感性检查。",
        ]
    )
    failed = {
        name: result["failures"]
        for name, result in payload["logs"].items()
        if result["failures"]
    }
    if failed:
        lines.extend(["", "## 失败明细", "", "```json", json.dumps(failed, ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    payload: dict[str, Any] = {
        "contract_id": contract["contract_id"],
        "great_expectations_version": gx.__version__,
        "success": True,
        "logs": {},
    }

    for name, spec in LOG_SPECS.items():
        path = args.events_dir / spec["filename"]
        frame = pd.read_csv(path, low_memory=False)
        expected_rows = int(manifest["logs"][name]["clean_rows"])
        context = gx.get_context(mode="ephemeral")
        suite = build_suite(
            name=name,
            required_columns=contract["required_event_columns"],
            binary_columns=contract["binary_columns"],
            expected_rows=expected_rows,
            expected_is_rand=spec["is_rand"],
            expected_policy=spec["collection_policy"],
        )
        gx_result = validate_frame(
            name=name, frame=frame, suite=suite, context=context
        )
        result = {
            "file": str(
                path.resolve().relative_to(Path(__file__).resolve().parents[1])
            ),
            "rows": len(frame),
            "expected_rows": expected_rows,
            "success": bool(gx_result["success"]),
            "statistics": gx_result["statistics"],
            "failures": failure_rows(gx_result),
            "expectations": gx_result["expectations"],
        }
        payload["logs"][name] = result
        payload["success"] = payload["success"] and result["success"]
        print(
            f"{name}: {'PASS' if result['success'] else 'FAIL'} "
            f"({result['statistics']['evaluated_expectations']} expectations)"
        )
        del frame, suite, gx_result, context
        gc.collect()

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(f"Wrote {args.json_output}")
    print(f"Wrote {args.markdown_output}")
    if not payload["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
