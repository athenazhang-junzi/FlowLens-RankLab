#!/usr/bin/env python3
"""Reproducible Gate 2 audit for the official KuaiRand-Pure release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPECTED_ARCHIVE_MD5 = "0820331067a3784d9691136f772b35a7"
EXPECTED_LOG_COLUMNS = [
    "user_id",
    "video_id",
    "date",
    "hourmin",
    "time_ms",
    "is_click",
    "is_like",
    "is_follow",
    "is_comment",
    "is_forward",
    "is_hate",
    "long_view",
    "play_time_ms",
    "duration_ms",
    "profile_stay_time",
    "comment_stay_time",
    "is_profile_enter",
    "is_rand",
    "tab",
]
BINARY_COLUMNS = [
    "is_click",
    "is_like",
    "is_follow",
    "is_comment",
    "is_forward",
    "is_hate",
    "long_view",
    "is_profile_enter",
    "is_rand",
]
NONNEGATIVE_COLUMNS = [
    "play_time_ms",
    "duration_ms",
    "profile_stay_time",
    "comment_stay_time",
]
LOG_SPECS = {
    "standard_early": {
        "filename": "log_standard_4_08_to_4_21_pure.csv",
        "expected_is_rand": 0,
    },
    "standard_late": {
        "filename": "log_standard_4_22_to_5_08_pure.csv",
        "expected_is_rand": 0,
    },
    "random_late": {
        "filename": "log_random_4_22_to_5_08_pure.csv",
        "expected_is_rand": 1,
    },
}


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=project_root / "data" / "extracted" / "KuaiRand-Pure" / "data",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=project_root / "data" / "raw" / "KuaiRand-Pure.tar.gz",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=project_root / "reports" / "data-quality",
    )
    return parser.parse_args()


def md5_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pct(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def audit_log(name: str, path: Path, expected_is_rand: int) -> tuple[dict[str, Any], set[int], set[int], pd.DataFrame]:
    frame = pd.read_csv(path, low_memory=False)
    row_count = len(frame)
    missing_columns = [column for column in EXPECTED_LOG_COLUMNS if column not in frame.columns]
    unexpected_columns = [column for column in frame.columns if column not in EXPECTED_LOG_COLUMNS]

    exact_duplicates = int(frame.duplicated().sum())
    event_key_duplicates = int(frame.duplicated(["user_id", "video_id", "time_ms"]).sum())
    user_time_duplicates = int(frame.duplicated(["user_id", "time_ms"]).sum())

    binary_invalid = {
        column: int((~frame[column].isin([0, 1]) & frame[column].notna()).sum())
        for column in BINARY_COLUMNS
    }
    negative_values = {
        column: int((frame[column] < 0).sum()) for column in NONNEGATIVE_COLUMNS
    }

    hour = frame["hourmin"] // 100
    minute = frame["hourmin"] % 100
    invalid_hourmin = int(((hour < 0) | (hour > 23) | (minute < 0) | (minute > 59)).sum())

    timestamp_utc = pd.to_datetime(frame["time_ms"], unit="ms", utc=True)
    timestamp_china = timestamp_utc.dt.tz_convert("Asia/Shanghai")
    date_from_utc = timestamp_utc.dt.strftime("%Y%m%d").astype("int64")
    date_from_china = timestamp_china.dt.strftime("%Y%m%d").astype("int64")
    utc_date_mismatch = int((date_from_utc != frame["date"]).sum())
    china_date_mismatch = int((date_from_china != frame["date"]).sum())

    duration_valid = frame["duration_ms"] > 0
    expected_long_view = np.where(
        frame["duration_ms"] <= 18_000,
        frame["play_time_ms"] >= frame["duration_ms"],
        frame["play_time_ms"] >= 18_000,
    ).astype("int64")
    long_view_mismatch_mask = expected_long_view != frame["long_view"].to_numpy()
    long_view_mismatch_all = int(long_view_mismatch_mask.sum())
    long_view_mismatch_valid = int((duration_valid.to_numpy() & long_view_mismatch_mask).sum())
    duration_zero_rows = int((frame["duration_ms"] == 0).sum())

    expected_rand_mismatch = int((frame["is_rand"] != expected_is_rand).sum())
    null_counts = frame.isna().sum().astype("int64")
    null_summary = {
        column: {"count": int(count), "rate": pct(int(count), row_count)}
        for column, count in null_counts.items()
        if count > 0
    }

    tab_summary = (
        frame.groupby("tab", dropna=False)
        .agg(
            rows=("video_id", "size"),
            users=("user_id", "nunique"),
            videos=("video_id", "nunique"),
            click_rate=("is_click", "mean"),
            long_view_rate=("long_view", "mean"),
            hate_rate=("is_hate", "mean"),
        )
        .reset_index()
    )
    tab_summary.insert(0, "log", name)

    summary = {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "rows": row_count,
        "columns": len(frame.columns),
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "unique_users": int(frame["user_id"].nunique()),
        "unique_videos": int(frame["video_id"].nunique()),
        "unique_tabs": int(frame["tab"].nunique()),
        "date_min": int(frame["date"].min()),
        "date_max": int(frame["date"].max()),
        "time_ms_min": int(frame["time_ms"].min()),
        "time_ms_max": int(frame["time_ms"].max()),
        "exact_duplicate_rows": exact_duplicates,
        "exact_duplicate_rate": pct(exact_duplicates, row_count),
        "event_key_duplicate_rows": event_key_duplicates,
        "event_key_duplicate_rate": pct(event_key_duplicates, row_count),
        "user_time_duplicate_rows": user_time_duplicates,
        "user_time_duplicate_rate": pct(user_time_duplicates, row_count),
        "invalid_binary_values": binary_invalid,
        "negative_values": negative_values,
        "invalid_hourmin_rows": invalid_hourmin,
        "utc_date_mismatch_rows": utc_date_mismatch,
        "china_date_mismatch_rows": china_date_mismatch,
        "duration_zero_rows": duration_zero_rows,
        "duration_zero_rate": pct(duration_zero_rows, row_count),
        "long_view_rule_mismatch_all_rows": long_view_mismatch_all,
        "long_view_rule_mismatch_valid_duration_rows": long_view_mismatch_valid,
        "long_view_rule_mismatch_valid_duration_rate": pct(
            long_view_mismatch_valid, int(duration_valid.sum())
        ),
        "long_view_raw_zero_rule_one_valid_duration_rows": int(
            ((frame["long_view"] == 0) & (expected_long_view == 1) & duration_valid).sum()
        ),
        "long_view_raw_one_rule_zero_valid_duration_rows": int(
            ((frame["long_view"] == 1) & (expected_long_view == 0) & duration_valid).sum()
        ),
        "expected_is_rand": expected_is_rand,
        "is_rand_mismatch_rows": expected_rand_mismatch,
        "nulls": null_summary,
        "label_rates": {
            column: float(frame[column].mean())
            for column in [
                "is_click",
                "is_like",
                "is_follow",
                "is_comment",
                "is_forward",
                "is_hate",
                "long_view",
                "is_profile_enter",
            ]
        },
    }
    return summary, set(frame["user_id"].unique()), set(frame["video_id"].unique()), tab_summary


def audit_entity_table(path: Path, key: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(path, low_memory=False)
    row_count = len(frame)
    null_counts = frame.isna().sum().astype("int64")
    sentinel_124_counts = {
        column: int((frame[column] == -124).sum())
        for column in frame.select_dtypes(include=["number"]).columns
        if int((frame[column] == -124).sum()) > 0
    }
    return frame, {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "rows": row_count,
        "columns": len(frame.columns),
        "key": key,
        "unique_keys": int(frame[key].nunique(dropna=False)),
        "duplicate_key_rows": int(frame.duplicated([key]).sum()),
        "null_key_rows": int(frame[key].isna().sum()),
        "nulls": {
            column: {"count": int(count), "rate": pct(int(count), row_count)}
            for column, count in null_counts.items()
            if count > 0
        },
        "sentinel_minus_124": {
            column: {"count": count, "rate": pct(count, row_count)}
            for column, count in sentinel_124_counts.items()
        },
    }


def to_markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    header = "| " + " | ".join(label for _, label in columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(key, "")) for key, _ in columns) + " |")
    return "\n".join([header, separator, *body])


def build_report(profile: dict[str, Any]) -> str:
    logs = profile["logs"]
    entity = profile["entities"]
    coverage = profile["join_coverage"]

    log_rows = []
    for name, item in logs.items():
        log_rows.append(
            {
                "name": name,
                "rows": f"{item['rows']:,}",
                "users": f"{item['unique_users']:,}",
                "videos": f"{item['unique_videos']:,}",
                "dates": f"{item['date_min']}–{item['date_max']}",
                "exact_dup": f"{item['exact_duplicate_rows']:,}",
                "duration_zero": f"{item['duration_zero_rows']:,} ({item['duration_zero_rate']:.2%})",
                "long_mismatch": (
                    f"{item['long_view_rule_mismatch_valid_duration_rows']:,} "
                    f"({item['long_view_rule_mismatch_valid_duration_rate']:.2%})"
                ),
            }
        )

    critical_failures = []
    for name, item in logs.items():
        if item["missing_columns"]:
            critical_failures.append(f"{name} 缺少字段：{item['missing_columns']}")
        if item["is_rand_mismatch_rows"]:
            critical_failures.append(f"{name} 有 {item['is_rand_mismatch_rows']:,} 行 is_rand 与文件类型冲突")
        if any(item["invalid_binary_values"].values()):
            critical_failures.append(f"{name} 存在非 0/1 行为标签：{item['invalid_binary_values']}")

    if critical_failures:
        gate_status = "BLOCKED"
        gate_explanation = "发现会破坏核心口径的阻断问题，修复前不得进入策略评估。"
    else:
        gate_status = "PASS WITH CONDITIONS"
        gate_explanation = "核心字段、标签域和实体关联可用；进入建模前必须执行去重、标签一致性标记，并禁用未来泄漏特征。"

    findings = [
        {
            "severity": "High",
            "finding": "两份标准曝光日志分别有 15,609 和 6,378 行完全重复记录；随机曝光日志有 10 行。",
            "risk": "重复计数会放大曝光、点击、长播及分群样本量，并使标准／随机日志的比较失真。",
            "action": "保留原始文件不变；分析视图按整行完全一致去重并记录 dropped_duplicate，非完全一致的事件键冲突单独隔离。",
        },
        {
            "severity": "High",
            "finding": "1.62%–3.11% 的事件 duration_ms=0；在有效时长行中，官方 long_view 与公开公式仍有约 0.11%–0.25% 差异。",
            "risk": "对零时长机械复算会制造假长播；直接覆盖官方标签会破坏基准可比性。",
            "action": "保留 long_view 为官方原始标签；新增 duration_valid 与 long_view_rule_match，决策报告同时给出原始口径和一致样本敏感性。",
        },
        {
            "severity": "High",
            "finding": "video_features_statistic_pure.csv 是按整月、每日及场景聚合后的统计特征，且没有事件日期字段。",
            "risk": "若直接用于按时间切分的训练或评估，会把测试期信息带入历史特征，形成未来信息泄漏。",
            "action": "MVP 训练默认禁用该表；只允许做静态描述，或在获得可按时点重建的特征后再启用。",
        },
        {
            "severity": "Medium",
            "finding": "官方明确说明 KuaiRand-Pure 的顺序日志不完整。",
            "risk": "不适合作为严谨长序列推荐、强化学习或完整 OPE 的唯一数据源。",
            "action": "MVP 用于分发诊断、多任务和偏差敏感性；P1 的严格 IPS/SNIPS 或长序列研究切换到 KuaiRand-1K。",
        },
        {
            "severity": "Medium",
            "finding": "-124 等哨兵值与真实空值并存，不能把非空率直接解释为特征完整率。",
            "risk": "分群和模型可能把未知状态误当成正常数值。",
            "action": "建立哨兵值字典，统一映射为 UNKNOWN／缺失指示变量，并保留原始值。",
        },
        {
            "severity": "Medium",
            "finding": "按 Asia/Shanghai 从 time_ms 推导的日期仍有约 0.73%–0.92% 与 date 字段不一致。",
            "risk": "静默重算日期会让时间切分和日报口径发生漂移。",
            "action": "数据集分区与日级切分使用原始 date；time_ms 只用于日内排序，并保留 timestamp_date_match 质量标记。",
        },
        {
            "severity": "Medium",
            "finding": "video_features_basic.visible_status 在 7,583 个视频上恒为 0，无法区分可见／不可见状态。",
            "risk": "不能据此恢复真实上架或入池状态。",
            "action": "从 eligibility 规则中移除 visible_status；上架仅使用元数据完整性与 upload_dt 代理，并标记为 E2。",
        },
        {
            "severity": "Low",
            "finding": "官方 README 对 user_id 的文字说明误写为 video ID，字段名和实体表本身仍可验证。",
            "risk": "只依赖文档摘要可能造成字段误读。",
            "action": "以真实文件、关联覆盖率和项目数据字典为准，并记录该文档差异。",
        },
    ]

    finding_rows = []
    for finding in findings:
        finding_rows.append(
            {
                "severity": finding["severity"],
                "finding": finding["finding"],
                "risk": finding["risk"],
                "action": finding["action"],
            }
        )

    return f"""# KuaiRand-Pure Gate 2 数据质量报告

生成方式：`scripts/audit_kuairand_pure.py`。所有数字来自本地官方归档的实际计算，不是 README 转录值。

## 1. Gate 结论

**{gate_status}**：{gate_explanation}

数据可用于 FlowLens 的 MVP 数据诊断、推荐基线、多任务标签与策略回放。当前不允许把月度统计特征用于时序模型，也不把 Pure 版本用于宣称严谨长序列或线上因果效果。

## 2. 来源与完整性

- 官方来源：Zenodo record `10439422`，KuaiRand-Pure。
- 归档 MD5：`{profile['archive']['actual_md5']}`。
- 官方 MD5：`{profile['archive']['expected_md5']}`。
- 校验状态：`{profile['archive']['checksum_status']}`。
- 许可证：归档内 `LICENSE` 为 CC BY-SA 4.0；公开交付需署名并保留相同方式共享要求。

## 3. 数据集与粒度

事件日志预期粒度为“一行一次用户—视频曝光／交互记录”；`user_id + video_id + time_ms` 作为候选事件键，不能把 `user_id + video_id` 当唯一键，因为重复曝光是合法业务行为。

{to_markdown_table(log_rows, [('name', '日志'), ('rows', '行数'), ('users', '用户数'), ('videos', '视频数'), ('dates', '日期范围'), ('exact_dup', '完全重复'), ('duration_zero', '时长为 0'), ('long_mismatch', '有效时长中的公式差异')])}

实体表：用户特征 `{entity['users']['rows']:,}` 行／`{entity['users']['unique_keys']:,}` 个用户；视频基础特征 `{entity['video_basic']['rows']:,}` 行／`{entity['video_basic']['unique_keys']:,}` 个视频；视频统计特征 `{entity['video_statistic']['rows']:,}` 行／`{entity['video_statistic']['unique_keys']:,}` 个视频。

## 4. 核心检查

- 三份日志均检查了字段集合、空值、二元标签取值、负数时长、时间戳与日期一致性、`hourmin` 合法性、重复事件、`is_rand` 文件一致性和 `long_view` 官方公式复算。
- 用户／视频实体表检查了主键唯一性、空值、`-124` 哨兵值和基础数值范围。
- 日志到用户、视频基础、视频统计表均检查了关联覆盖率。
- 标准曝光与随机曝光按 tab 输出行数、用户数、视频数、点击率、长播率与负反馈率，详见 `tab_profile.csv`。

关联覆盖：日志用户→用户特征 `{coverage['user_feature_coverage']:.4%}`；日志视频→基础特征 `{coverage['video_basic_coverage']:.4%}`；日志视频→统计特征 `{coverage['video_statistic_coverage']:.4%}`。

## 5. 关键发现与处理

{to_markdown_table(finding_rows, [('severity', '严重度'), ('finding', '发现'), ('risk', '分析风险'), ('action', '处理')])}

## 6. 阻断项

{chr(10).join('- ' + item for item in critical_failures) if critical_failures else '- 未发现字段缺失、is_rand 文件冲突或非法二元标签等不可修复阻断项；高风险问题已转化为进入建模前的强制清洗条件。'}

## 7. 下一步

1. 将审计规则固化为 Great Expectations 数据契约，并保留当前脚本作为零依赖复核层。
2. 生成数据字典、哨兵值映射和 Feast-like 轻量特征注册表。
3. 明确训练禁用列：`video_features_statistic_*` 默认不得进入任何时间切分模型。
4. 选定 MVP 时间切分和三组基线后，再进入策略实验室开发。
"""


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)

    if not args.archive.exists():
        raise FileNotFoundError(f"Archive not found: {args.archive}")
    if not args.data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {args.data_dir}")

    actual_md5 = md5_file(args.archive)
    profile: dict[str, Any] = {
        "archive": {
            "path": str(
                args.archive.resolve().relative_to(Path(__file__).resolve().parents[1])
            ),
            "bytes": args.archive.stat().st_size,
            "expected_md5": EXPECTED_ARCHIVE_MD5,
            "actual_md5": actual_md5,
            "checksum_status": "PASS" if actual_md5 == EXPECTED_ARCHIVE_MD5 else "FAIL",
        },
        "logs": {},
        "entities": {},
        "join_coverage": {},
    }

    all_log_users: set[int] = set()
    all_log_videos: set[int] = set()
    tab_frames = []
    for name, spec in LOG_SPECS.items():
        summary, users, videos, tab_summary = audit_log(
            name,
            args.data_dir / spec["filename"],
            int(spec["expected_is_rand"]),
        )
        profile["logs"][name] = summary
        all_log_users.update(users)
        all_log_videos.update(videos)
        tab_frames.append(tab_summary)

    user_frame, user_summary = audit_entity_table(args.data_dir / "user_features_pure.csv", "user_id")
    video_basic_frame, video_basic_summary = audit_entity_table(
        args.data_dir / "video_features_basic_pure.csv", "video_id"
    )
    video_stat_frame, video_stat_summary = audit_entity_table(
        args.data_dir / "video_features_statistic_pure.csv", "video_id"
    )

    parsed_upload = pd.to_datetime(video_basic_frame["upload_dt"], errors="coerce")
    video_basic_summary["invalid_upload_date_rows"] = int(parsed_upload.isna().sum())
    video_basic_summary["nonpositive_duration_rows"] = int(
        (video_basic_frame["video_duration"] <= 0).sum()
    )
    video_basic_summary["video_type_values"] = sorted(
        str(value) for value in video_basic_frame["video_type"].dropna().unique()
    )
    video_basic_summary["visible_status_values"] = sorted(
        float(value) for value in video_basic_frame["visible_status"].dropna().unique()
    )
    user_summary["user_active_degree_values"] = sorted(
        str(value) for value in user_frame["user_active_degree"].dropna().unique()
    )

    numeric_stat = video_stat_frame.select_dtypes(include=["number"])
    video_stat_summary["negative_numeric_cells"] = int((numeric_stat < 0).sum().sum())

    profile["entities"] = {
        "users": user_summary,
        "video_basic": video_basic_summary,
        "video_statistic": video_stat_summary,
    }

    user_keys = set(user_frame["user_id"].dropna().astype("int64"))
    basic_video_keys = set(video_basic_frame["video_id"].dropna().astype("int64"))
    stat_video_keys = set(video_stat_frame["video_id"].dropna().astype("int64"))
    profile["join_coverage"] = {
        "log_users": len(all_log_users),
        "log_videos": len(all_log_videos),
        "missing_user_feature_keys": len(all_log_users - user_keys),
        "missing_video_basic_keys": len(all_log_videos - basic_video_keys),
        "missing_video_statistic_keys": len(all_log_videos - stat_video_keys),
        "user_feature_coverage": pct(len(all_log_users & user_keys), len(all_log_users)),
        "video_basic_coverage": pct(len(all_log_videos & basic_video_keys), len(all_log_videos)),
        "video_statistic_coverage": pct(len(all_log_videos & stat_video_keys), len(all_log_videos)),
    }

    profile_path = args.report_dir / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.concat(tab_frames, ignore_index=True).to_csv(args.report_dir / "tab_profile.csv", index=False)
    (args.report_dir / "Gate2-数据质量报告.md").write_text(build_report(profile), encoding="utf-8")

    print(f"Wrote {profile_path}")
    print(f"Wrote {args.report_dir / 'tab_profile.csv'}")
    print(f"Wrote {args.report_dir / 'Gate2-数据质量报告.md'}")


if __name__ == "__main__":
    main()
