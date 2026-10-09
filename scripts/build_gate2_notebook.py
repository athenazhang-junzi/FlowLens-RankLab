#!/usr/bin/env python3
"""Build, execute, and render the KuaiRand-Pure Gate 2 audit notebook."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient
from nbconvert import HTMLExporter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "01-KuaiRand-Pure-Gate2-audit.ipynb"
HTML_PATH = PROJECT_ROOT / "reports" / "data-quality" / "Gate2-notebook.html"


def markdown(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


def build_notebook():
    notebook = nbf.v4.new_notebook()
    notebook["metadata"] = {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3.12"},
    }
    notebook["cells"] = [
        markdown(
            """
# FlowLens Gate 2｜KuaiRand-Pure 数据可信度审计

## tl;dr

- 官方归档 MD5 与发布值一致，三份日志合计 **2,622,668** 条原始事件。
- 清洗视图只删除 **21,997** 条完全重复记录，保留 **2,600,671** 条；非完全相同的候选事件键冲突保留并打标。
- 三份清洗日志的 Great Expectations 契约共执行 **129** 条阻断规则，全部通过。
- 数据可进入 FlowLens 基线与分发诊断，但必须禁用无事件日期的整月视频统计特征；Pure 版本也不能用于宣称严谨长序列或线上因果效果。

> 证据边界：本 Notebook 展示公开数据的 E1 观测和确定性 E2 质量标记，不把离线数据包装为真实平台内部数据或线上 A/B 结果。
"""
        ),
        markdown(
            """
## Context & Methods

目标是判断 KuaiRand-Pure 是否足以支撑 FlowLens MVP 的分发诊断、推荐基线和策略回放，并将稳定规则固化为可自动阻断的数据契约。

### Key Assumptions

- 事件粒度按源文件“一行一次用户—视频曝光／交互记录”理解。
- `user_id + video_id + time_ms` 只是候选事件键，非完全相同冲突不会被自动删除。
- 日级切分采用源字段 `date`，`time_ms` 仅用于日内排序；两者不一致时保留质量标记。
- `long_view` 保留官方标签，公开公式复算只做敏感性检查。
- `video_features_statistic_pure.csv` 缺少事件日期，默认禁止进入任何时间切分训练／验证／测试。
"""
        ),
        code(
            """
from pathlib import Path
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display

cwd = Path.cwd().resolve()
PROJECT_ROOT = cwd if (cwd / "reports" / "data-quality").exists() else cwd.parent
REPORT_DIR = PROJECT_ROOT / "reports" / "data-quality"

plt.style.use("seaborn-v0_8-whitegrid")
plt.rcParams.update({
    "figure.figsize": (9, 4.8),
    "axes.titlesize": 13,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.edgecolor": "#334155",
    "text.color": "#172033",
    "axes.labelcolor": "#172033",
})
PALETTE = {
    "raw": "#2457A6",
    "clean": "#D6A328",
    "duplicate": "#D97706",
    "duration": "#7C8E42",
    "date": "#C04B76",
}
"""
        ),
        markdown(
            """
## Data

本 Notebook 不重复扫描 500MB 以上的原始与清洗 CSV，而是读取由全量审计脚本生成的可追溯结果：

- `reports/data-quality/profile.json`：原始日志与实体表全量 profile；
- `reports/data-quality/cleaning_manifest.json`：清洗前后行数与质量标记；
- `reports/data-quality/gx_validation_results.json`：Great Expectations 全量契约结果；
- `reports/data-quality/tab_profile.csv`：按日志和 tab 的消费指标。

复算原始审计：`python scripts/audit_kuairand_pure.py`
重建清洗视图：`python scripts/prepare_kuairand_event_views.py`
复跑契约：`python scripts/validate_kuairand_with_gx.py`
"""
        ),
        code(
            """
profile = json.loads((REPORT_DIR / "profile.json").read_text(encoding="utf-8"))
manifest = json.loads((REPORT_DIR / "cleaning_manifest.json").read_text(encoding="utf-8"))
gx_results = json.loads((REPORT_DIR / "gx_validation_results.json").read_text(encoding="utf-8"))
tab_profile = pd.read_csv(REPORT_DIR / "tab_profile.csv")

log_order = ["standard_early", "standard_late", "random_late"]
summary_rows = []
for log_name in log_order:
    raw = profile["logs"][log_name]
    clean = manifest["logs"][log_name]
    gx_log = gx_results["logs"][log_name]
    summary_rows.append({
        "log": log_name,
        "raw_rows": raw["rows"],
        "clean_rows": clean["clean_rows"],
        "exact_duplicates": raw["exact_duplicate_rows"],
        "duplicate_rate": raw["exact_duplicate_rate"],
        "duration_zero_rate": raw["duration_zero_rate"],
        "date_mismatch_rate": raw["china_date_mismatch_rows"] / raw["rows"],
        "formula_mismatch_valid_rate": raw["long_view_rule_mismatch_valid_duration_rate"],
        "gx_expectations": gx_log["statistics"]["evaluated_expectations"],
        "gx_success": gx_log["success"],
    })

summary = pd.DataFrame(summary_rows)
display(summary.assign(
    duplicate_rate=summary["duplicate_rate"].map(lambda x: f"{x:.2%}"),
    duration_zero_rate=summary["duration_zero_rate"].map(lambda x: f"{x:.2%}"),
    date_mismatch_rate=summary["date_mismatch_rate"].map(lambda x: f"{x:.2%}"),
    formula_mismatch_valid_rate=summary["formula_mismatch_valid_rate"].map(lambda x: f"{x:.2%}"),
))
"""
        ),
        code(
            """
assert profile["archive"]["checksum_status"] == "PASS"
assert profile["archive"]["actual_md5"] == profile["archive"]["expected_md5"]
assert summary["raw_rows"].sum() == 2_622_668
assert summary["clean_rows"].sum() == 2_600_671
assert summary["exact_duplicates"].sum() == 21_997
assert gx_results["success"] is True
assert summary["gx_expectations"].sum() == 129
assert summary["gx_success"].all()

join_coverage = profile["join_coverage"]
join_coverage
"""
        ),
        markdown(
            """
## Results

### 1. 原始事件与清洗视图

标准曝光日志存在明显的完全重复记录；随机曝光日志几乎没有。清洗只删除整行完全一致的记录，因此不会把合法重复曝光误删。
"""
        ),
        code(
            """
x = np.arange(len(summary))
width = 0.36
fig, ax = plt.subplots()
raw_bars = ax.bar(x - width / 2, summary["raw_rows"], width, label="Raw rows", color=PALETTE["raw"])
clean_bars = ax.bar(x + width / 2, summary["clean_rows"], width, label="Clean rows", color=PALETTE["clean"])
ax.set_title("Raw and clean event rows by log")
ax.set_ylabel("Rows")
ax.set_xticks(x, summary["log"])
ax.ticklabel_format(axis="y", style="plain")
ax.legend(frameon=False, ncol=2)
for bars in [raw_bars, clean_bars]:
    ax.bar_label(bars, labels=[f"{int(v):,}" for v in bars.datavalues], padding=3, fontsize=8)
ax.set_ylim(0, summary["raw_rows"].max() * 1.14)
fig.tight_layout()
plt.show()
"""
        ),
        markdown(
            """
### 2. 质量问题的相对规模

三类比例代表不同问题，不能相加：完全重复影响计数；零时长使公式复算不可验证；时间戳日期差异会影响时间切分口径。日期不一致不直接判定源数据错误，因此保留源 `date`。
"""
        ),
        code(
            """
quality_metrics = pd.DataFrame({
    "Exact duplicate": summary.set_index("log")["duplicate_rate"],
    "Zero duration": summary.set_index("log")["duration_zero_rate"],
    "Timestamp/date mismatch": summary.set_index("log")["date_mismatch_rate"],
}) * 100

ax = quality_metrics.plot.bar(
    color=[PALETTE["duplicate"], PALETTE["duration"], PALETTE["date"]],
    width=0.76,
    figsize=(9, 4.8),
)
ax.set_title("Observed data-quality rates by log")
ax.set_ylabel("Share of rows (%)")
ax.set_xlabel("")
ax.set_xticklabels(quality_metrics.index, rotation=0)
ax.legend(frameon=False, ncol=3, loc="upper center")
for container in ax.containers:
    ax.bar_label(container, fmt="%.2f%%", padding=3, fontsize=8)
ax.set_ylim(0, quality_metrics.to_numpy().max() * 1.25)
plt.tight_layout()
plt.show()
"""
        ),
        markdown(
            """
### 3. 标准曝光与随机曝光不可直接当作同一分布

日志的采样策略不同，点击率和长播率存在显著描述性差异。这里仅用于提示选择偏差风险，不解释为策略因果效果，也不据此宣称随机日志“更差”。
"""
        ),
        code(
            """
label_rows = []
for log_name in log_order:
    rates = profile["logs"][log_name]["label_rates"]
    label_rows.append({
        "log": log_name,
        "Click rate": rates["is_click"] * 100,
        "Long-view rate": rates["long_view"] * 100,
    })
label_rates = pd.DataFrame(label_rows).set_index("log")

ax = label_rates.plot.bar(color=[PALETTE["raw"], PALETTE["clean"]], width=0.7, figsize=(9, 4.8))
ax.set_title("Observed consumption labels by collection log")
ax.set_ylabel("Share of events (%)")
ax.set_xlabel("")
ax.set_xticklabels(label_rates.index, rotation=0)
ax.legend(frameon=False, ncol=2)
for container in ax.containers:
    ax.bar_label(container, fmt="%.1f%%", padding=3, fontsize=8)
ax.set_ylim(0, label_rates.to_numpy().max() * 1.22)
plt.tight_layout()
plt.show()

display(tab_profile.sort_values(["log", "rows"], ascending=[True, False]).groupby("log").head(5))
"""
        ),
        markdown(
            """
### 4. 自动化契约结果

Great Expectations 对每份清洗日志执行 43 条稳定规则；三份共 129 条，全部通过。已知但不能稳定判断真假的问题保留为质量标记，不被错误地转化为阻断项。
"""
        ),
        code(
            """
gx_summary = pd.DataFrame([
    {
        "log": name,
        "evaluated": result["statistics"]["evaluated_expectations"],
        "passed": result["statistics"]["successful_expectations"],
        "failed": result["statistics"]["unsuccessful_expectations"],
        "status": "PASS" if result["success"] else "FAIL",
    }
    for name, result in gx_results["logs"].items()
])
display(gx_summary)
"""
        ),
        markdown(
            """
## Takeaways

1. **可进入 Gate 3。** 核心字段、标签域、实体关联与清洗视图满足基线开发要求；用户、视频基础表和视频统计表的关联覆盖率均为 100%。
2. **训练边界必须写进代码。** 整月视频统计特征没有事件日期，禁止进入时间切分训练、验证与测试；后续特征必须做 point-in-time 检查。
3. **不把数据缺陷“洗掉”。** 零时长、官方长播公式差异、日期差异与候选事件键冲突均保留审计字段，以便做敏感性分析。
4. **不越过因果边界。** 标准与随机曝光差异是描述性证据；Pure 的不完整顺序日志不足以支持线上增量或严谨长序列结论。
5. **Gate 3 的最小任务。** 固定时间切分、建立 Popularity／ItemCF／轻量多任务基线，并先通过未来信息泄漏测试，再开始策略重排。
"""
        ),
    ]
    return notebook


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)

    notebook = build_notebook()
    client = NotebookClient(
        notebook,
        timeout=300,
        kernel_name="python3",
        resources={"metadata": {"path": str(PROJECT_ROOT)}},
    )
    executed = client.execute()
    nbf.write(executed, NOTEBOOK_PATH)

    exporter = HTMLExporter(template_name="lab")
    html, _ = exporter.from_notebook_node(executed)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote executed notebook: {NOTEBOOK_PATH}")
    print(f"Wrote HTML preview: {HTML_PATH}")


if __name__ == "__main__":
    main()
