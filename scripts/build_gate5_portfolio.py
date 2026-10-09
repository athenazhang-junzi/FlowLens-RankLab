#!/usr/bin/env python3
"""Build the FlowLens web project introduction and 10-page PDF."""

from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "tmp" / "matplotlib"))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.font_manager import FontProperties
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_DIR = ROOT / "portfolio"
ASSET_DIR = PORTFOLIO_DIR / "assets"
PDF_DIR = ROOT / "output" / "pdf"
DOCS_DIR = ROOT / "docs"
HTML_PATH = PORTFOLIO_DIR / "FlowLens-推荐分发项目介绍.html"
DOCS_PATH = DOCS_DIR / "index.html"
PDF_PATH = PDF_DIR / "FlowLens-推荐分发项目介绍.pdf"

PAGE_W, PAGE_H = 960, 540
FONT = "ArialUnicode"
PDF_FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FP = FontProperties(fname=str(FONT_PATH)) if FONT_PATH.exists() else None

NAVY = "#14263D"
BLUE = "#356AE6"
BLUE_LIGHT = "#EAF0FF"
ORANGE = "#F08A4B"
ORANGE_LIGHT = "#FFF0E5"
TEAL = "#2E7D70"
TEAL_LIGHT = "#E8F4F1"
GOLD = "#D2A12F"
INK = "#172133"
MUTED = "#627084"
LINE = "#DDE3EA"
PAPER = "#F7F8FA"
WHITE = "#FFFFFF"
RED = "#B44C58"


def load_data() -> dict[str, object]:
    cleaning = json.loads((ROOT / "reports/data-quality/cleaning_manifest.json").read_text())
    gate3 = pd.read_csv(ROOT / "reports/gate3/baseline_metrics.csv")
    tags = pd.read_csv(ROOT / "reports/gate3/tag_supply_demand.csv")
    gate4 = pd.read_csv(ROOT / "reports/gate4/strategy_metrics.csv")
    deltas = pd.read_csv(ROOT / "reports/gate4/strategy_deltas.csv")
    decisions = pd.read_csv(ROOT / "reports/gate4/offline_decisions.csv")
    run3 = json.loads((ROOT / "reports/gate3/run_manifest.json").read_text())
    run4 = json.loads((ROOT / "reports/gate4/run_manifest.json").read_text())
    return {
        "cleaning": cleaning,
        "gate3": gate3,
        "tags": tags,
        "gate4": gate4,
        "deltas": deltas,
        "decisions": decisions,
        "run3": run3,
        "run4": run4,
    }


def style_axis(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(LINE)
    ax.grid(axis="y", color=LINE, linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9)


def save_gate2_volume(data: dict[str, object]) -> Path:
    rows = []
    names = {"standard_early": "标准日志\n训练+验证", "standard_late": "标准日志\n测试", "random_late": "随机日志\n敏感性"}
    for key, payload in data["cleaning"]["logs"].items():
        rows.append((names[key], payload["raw_rows"], payload["clean_rows"]))
    labels = [r[0] for r in rows]
    raw = np.array([r[1] for r in rows]) / 1_000_000
    clean = np.array([r[2] for r in rows]) / 1_000_000
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8.2, 3.3), dpi=180)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    width = 0.34
    bars1 = ax.bar(x - width / 2, raw, width, color="#B8C4D3", label="原始行数")
    bars2 = ax.bar(x + width / 2, clean, width, color=BLUE, label="清洗视图")
    for bars in (bars1, bars2):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.025, f"{bar.get_height():.3f}M", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(x, labels, fontproperties=FP, fontsize=9)
    ax.set_ylabel("日志行数（百万）", fontproperties=FP, color=MUTED)
    ax.set_ylim(0, max(raw) * 1.18)
    ax.legend(frameon=False, prop=FP, loc="upper center", ncol=2)
    style_axis(ax)
    fig.tight_layout()
    path = ASSET_DIR / "gate2-log-volume.png"
    fig.savefig(path, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    return path


def save_gate3_baselines(data: dict[str, object]) -> Path:
    frame = data["gate3"]
    frame = frame[frame["split"].isin(["standard_test", "random_sensitivity"])].copy()
    splits = ["standard_test", "random_sensitivity"]
    models = ["Popularity", "ItemCF", "MultiTaskHashSGD"]
    labels = ["标准曝光测试集", "随机曝光敏感性集"]
    colors = ["#A7B4C4", ORANGE, BLUE]
    x = np.arange(2)
    width = 0.22
    fig, ax = plt.subplots(figsize=(8.2, 3.4), dpi=180)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    for idx, model in enumerate(models):
        vals = [float(frame[(frame["split"] == split) & (frame["model"] == model)]["ndcg_at_5"].iloc[0]) for split in splits]
        bars = ax.bar(x + (idx - 1) * width, vals, width, label=model, color=colors[idx])
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 0.012, f"{val:.4f}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(x, labels, fontproperties=FP, fontsize=10)
    ax.set_ylabel("NDCG@5", color=MUTED)
    ax.set_ylim(0, 0.72)
    ax.legend(frameon=False, loc="upper right", ncol=3, fontsize=8)
    style_axis(ax)
    fig.tight_layout()
    path = ASSET_DIR / "gate3-baseline-reversal.png"
    fig.savefig(path, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    return path


def save_tag_gaps(data: dict[str, object]) -> Path:
    tags = data["tags"].copy()
    dist = tags.nlargest(5, "distribution_gap").sort_values("distribution_gap")
    cons = tags.nlargest(5, "consumption_gap").sort_values("consumption_gap")
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5), dpi=180)
    fig.patch.set_facecolor(WHITE)
    for ax, frame, col, title, color in [
        (axes[0], dist, "distribution_gap", "历史需求 - 测试曝光", BLUE),
        (axes[1], cons, "consumption_gap", "测试曝光 - 测试消费", ORANGE),
    ]:
        vals = frame[col].to_numpy() * 100
        labels = [f"标签 {v}" for v in frame["tag_id"].astype(str)]
        bars = ax.barh(np.arange(len(frame)), vals, color=color, alpha=0.9)
        ax.set_yticks(np.arange(len(frame)), labels, fontproperties=FP, fontsize=9)
        ax.set_xlabel("份额差（百分点）", fontproperties=FP, color=MUTED)
        ax.set_title(title, fontproperties=FP, fontsize=11, color=INK, loc="left")
        ax.grid(axis="x", color=LINE, linewidth=0.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(LINE)
        for bar, val in zip(bars, vals):
            ax.text(val + max(vals) * 0.025, bar.get_y() + bar.get_height() / 2, f"{val:.2f}pp", va="center", fontsize=8, color=INK)
        ax.set_xlim(0, max(vals) * 1.25)
    fig.tight_layout(w_pad=3)
    path = ASSET_DIR / "gate3-tag-gaps.png"
    fig.savefig(path, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    return path


def save_gate4_intervals(data: dict[str, object]) -> Path:
    frame = data["deltas"]
    frame = frame[(frame["split"] == "standard_test") & (frame["strategy"] != "S0")].copy()
    frame = frame.sort_values("strategy", ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.4), dpi=180)
    fig.patch.set_facecolor(WHITE)
    specs = [
        ("ndcg_at_5_delta", "ndcg_at_5_delta_ci_low", "ndcg_at_5_delta_ci_high", "ΔNDCG@5（原始单位）"),
        ("ecr_at_5_delta", "ecr_at_5_delta_ci_low", "ecr_at_5_delta_ci_high", "ΔTop-5 ECR（百分点）"),
    ]
    for ax, (value, low, high, title) in zip(axes, specs):
        vals = frame[value].to_numpy()
        lows = frame[low].to_numpy()
        highs = frame[high].to_numpy()
        display_vals = vals if value.startswith("ndcg") else vals * 100
        display_lows = lows if value.startswith("ndcg") else lows * 100
        display_highs = highs if value.startswith("ndcg") else highs * 100
        y = np.arange(len(frame))
        ax.axvline(0, color=INK, linewidth=1, linestyle="--")
        ax.errorbar(
            display_vals,
            y,
            xerr=[display_vals - display_lows, display_highs - display_vals],
            fmt="o",
            color=BLUE,
            ecolor="#8EA7E8",
            capsize=4,
            markersize=6,
        )
        ax.set_yticks(y, frame["strategy"], fontsize=9)
        ax.set_title(title, fontproperties=FP, fontsize=11, color=INK, loc="left")
        ax.grid(axis="x", color=LINE, linewidth=0.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(LINE)
        ax.tick_params(colors=MUTED, labelsize=8)
        for xv, yv in zip(display_vals, y):
            label = f"{xv:+.6f}" if value.startswith("ndcg") else f"{xv:+.3f}pp"
            ax.annotate(label, (xv, yv), xytext=(4, 7), textcoords="offset points", fontsize=7.5, color=INK)
    fig.tight_layout(w_pad=3)
    path = ASSET_DIR / "gate4-paired-intervals.png"
    fig.savefig(path, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    return path


def save_gate4_guardrails(data: dict[str, object]) -> Path:
    frame = data["gate4"]
    frame = frame[(frame["split"] == "standard_test") & (frame["strategy"].isin(["S0", "S2"]))].set_index("strategy")
    metrics = [
        ("作者重复@10", "author_repeat_rate_at_10"),
        ("标签重复@10", "primary_tag_repeat_rate_at_10"),
        ("内容覆盖@10", "content_coverage_at_10"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(9.2, 2.6), dpi=180)
    fig.patch.set_facecolor(WHITE)
    for ax, (label, col) in zip(axes, metrics):
        vals = [frame.loc["S0", col] * 100, frame.loc["S2", col] * 100]
        bars = ax.bar([0, 1], vals, color=["#A7B4C4", BLUE], width=0.58)
        ax.set_xticks([0, 1], ["S0", "S2"])
        ax.set_title(label, fontproperties=FP, fontsize=10, color=INK)
        ax.set_ylim(0, max(vals) * 1.22 if max(vals) else 1)
        ax.spines[:].set_visible(False)
        ax.set_yticks([])
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, val + max(vals) * 0.035, f"{val:.2f}%", ha="center", fontsize=8.5, color=INK)
    fig.tight_layout(w_pad=2)
    path = ASSET_DIR / "gate4-guardrails.png"
    fig.savefig(path, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    return path


def para(c, text: str, x: float, y_top: float, width: float, height: float, size: float = 13, color: str = INK, leading: float | None = None, align: int = TA_LEFT) -> float:
    style = ParagraphStyle(
        name="p",
        fontName=FONT,
        fontSize=size,
        leading=leading or size * 1.48,
        textColor=HexColor(color),
        alignment=align,
        wordWrap="CJK",
        spaceAfter=0,
    )
    p = Paragraph(text, style)
    _, h = p.wrap(width, height)
    p.drawOn(c, x, y_top - h)
    return h


def card(c, x: float, y: float, w: float, h: float, fill: str = WHITE, stroke: str = LINE, radius: float = 12) -> None:
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(HexColor(stroke))
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def chip(c, text: str, x: float, y: float, fill: str = BLUE_LIGHT, color: str = BLUE, width: float | None = None) -> float:
    w = width or max(70, 16 + len(text) * 11)
    c.setFillColor(HexColor(fill))
    c.roundRect(x, y, w, 24, 12, fill=1, stroke=0)
    para(c, text, x + 8, y + 18, w - 16, 18, size=9.5, color=color, leading=11, align=TA_CENTER)
    return w


def title_block(c, number: str, title: str, subtitle: str, page: int) -> None:
    c.setFillColor(HexColor(PAPER))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(HexColor(ORANGE))
    c.rect(42, PAGE_H - 49, 30, 4, fill=1, stroke=0)
    para(c, f"{number}  FLOWLENS", 82, PAGE_H - 37, 200, 18, size=9.5, color=MUTED, leading=11)
    para(c, title, 42, PAGE_H - 52, 780, 38, size=26, color=NAVY, leading=30)
    para(c, subtitle, 42, PAGE_H - 86, 840, 32, size=11.5, color=MUTED, leading=17)
    para(c, f"{page:02d} / 10", 860, 32, 60, 15, size=9, color=MUTED, leading=10, align=TA_CENTER)


def footer(c, source: str) -> None:
    c.setStrokeColor(HexColor(LINE))
    c.line(42, 44, 830, 44)
    para(c, source, 42, 36, 760, 20, size=7.6, color=MUTED, leading=9)


def bullet_list(c, items: list[str], x: float, y_top: float, width: float, size: float = 11.5, gap: float = 8, color: str = INK) -> float:
    y = y_top
    for item in items:
        c.setFillColor(HexColor(ORANGE))
        c.circle(x + 4, y - 8, 2.5, fill=1, stroke=0)
        h = para(c, item, x + 14, y, width - 14, 80, size=size, color=color, leading=size * 1.48)
        y -= h + gap
    return y


def draw_cover(c, data: dict[str, object]) -> None:
    c.setFillColor(HexColor(NAVY))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(HexColor(BLUE))
    c.circle(850, 465, 122, fill=1, stroke=0)
    c.setFillColor(HexColor(ORANGE))
    c.circle(884, 89, 55, fill=1, stroke=0)
    c.setFillColor(HexColor("#203A5B"))
    c.roundRect(54, 382, 162, 28, 14, fill=1, stroke=0)
    para(c, "90 秒项目速览", 66, 403, 140, 20, size=10, color=WHITE, leading=12, align=TA_CENTER)
    para(c, "FlowLens", 54, 344, 540, 65, size=45, color=WHITE, leading=50)
    para(c, "我用公开短视频日志，完整模拟了一次推荐分发策略迭代", 56, 285, 700, 58, size=23, color=WHITE, leading=30)
    para(c, "从“为什么用户没有看到合适的内容”出发，我先定位供需与消费问题，再设计 4 类分发策略，最后判断它们应该上线、重测，还是停止。", 56, 212, 680, 68, size=13.5, color="#D6E0EC", leading=21)
    x = 56
    for text_, fill, color in [
        ("发现问题", "#203A5B", "#D6E0EC"),
        ("设计策略", "#203A5B", "#D6E0EC"),
        ("评估取舍", "#203A5B", "#D6E0EC"),
        ("给出决策", "#203A5B", "#D6E0EC"),
    ]:
        x += chip(c, text_, x, 145, fill=fill, color=color, width=90) + 10
    para(c, "一句话结果：找到了明确的分发缺口，但没有把不确定的离线收益包装成“可以上线”。", 56, 104, 760, 28, size=11.5, color="#D6E0EC", leading=16)
    para(c, "个人项目 · 前 3 页 90 秒看懂 · 后 7 页查看方法与证据", 56, 63, 700, 18, size=8.5, color="#9FB0C4", leading=10)
    para(c, "01 / 10", 860, 32, 60, 15, size=9, color="#9FB0C4", leading=10, align=TA_CENTER)


def draw_page2(c) -> None:
    title_block(c, "02", "把一次推荐策略迭代完整走通", "不是只训练一个模型，而是回答业务最终要做的三个决定。", 2)
    cards = [
        ("01", "问题在哪里", "把内容生产、曝光和消费串起来，区分“用户想看但没被分到”和“已经分到却没有消费”两类问题。", BLUE_LIGHT, BLUE),
        ("02", "策略怎么改", "针对问题设计协同融合、多样性、长尾探索、风险与疲劳 4 类策略，并在相同候选集上公平比较。", ORANGE_LIGHT, ORANGE),
        ("03", "值不值得上线", "同时看有效消费、重复、覆盖与负反馈。最终判断不是谁分最高，而是谁有资格进入线上 A/B。", TEAL_LIGHT, TEAL),
    ]
    positions = [(42, 216), (338, 216), (634, 216)]
    for (num, name, body, fill, accent), (x, y) in zip(cards, positions):
        card(c, x, y, 280, 190, fill=WHITE)
        c.setFillColor(HexColor(fill))
        c.circle(x + 36, y + 148, 18, fill=1, stroke=0)
        para(c, num, x + 23, y + 154, 26, 15, size=9.5, color=accent, leading=11, align=TA_CENTER)
        para(c, name, x + 64, y + 164, 190, 24, size=16, color=NAVY, leading=19)
        para(c, body, x + 22, y + 118, 236, 98, size=10.5, color=MUTED, leading=16)
    card(c, 42, 132, 872, 62, fill=NAVY, stroke=NAVY)
    para(c, "最终交付：问题清单 + 4 类策略方案 + 冻结评估结果 + 一套线上 A/B 实验蓝图。", 64, 174, 826, 28, size=12, color=WHITE, leading=17, align=TA_CENTER)
    footer(c, "第 1–3 页为非技术速览；第 4–10 页提供指标、图表与可复现证据。")


def draw_page3(c, data: dict[str, object]) -> None:
    title_block(c, "03", "三个发现，决定下一步怎么做", "项目的价值不是给出一个漂亮分数，而是把分析结果翻译成可执行动作。", 3)
    findings = [
        ("发现 1", "单一榜单会误导", "同一批模型在常规曝光和随机曝光中的排名发生反转。动作：不凭一张离线榜单直接选策略。", BLUE),
        ("发现 2", "存在内容机会", "标签 39 的需求份额比曝光份额高 5.85pp。动作：继续区分是供给不足，还是分发不足。", ORANGE),
        ("发现 3", "收益伴随代价", "多样性策略降低了重复，但内容覆盖下降，主指标区间跨 0。动作：先调权重重测，不进入 A/B。", TEAL),
    ]
    for (label, name, body, accent), x in zip(findings, [42, 338, 634]):
        card(c, x, 216, 280, 190)
        para(c, label, x + 22, 380, 90, 18, size=10, color=accent, leading=13)
        para(c, name, x + 22, 350, 236, 26, size=16, color=NAVY, leading=20)
        para(c, body, x + 22, 310, 236, 96, size=10.5, color=MUTED, leading=16)
    card(c, 42, 132, 872, 62, fill=TEAL_LIGHT, stroke=TEAL_LIGHT)
    para(c, "最终建议：保留问题方向，暂不宣称策略成功；下一轮先修复覆盖护栏，再用线上随机实验验证真实增量。", 64, 174, 826, 30, size=11.8, color=NAVY, leading=17, align=TA_CENTER)
    footer(c, "以上结论来自公开日志的离线回放，只支持发现问题与比较方案，不代表真实线上提升。")


def draw_page4(c, data: dict[str, object], chart: Path) -> None:
    title_block(c, "04", "先确认数据能回答问题", "在分析前处理重复、标签一致性、关联覆盖与时间可用性，避免用脏数据制造结论。", 4)
    c.drawImage(str(chart), 42, 196, width=548, height=232, preserveAspectRatio=True, mask="auto")
    card(c, 614, 316, 304, 106, fill=BLUE_LIGHT, stroke=BLUE_LIGHT)
    para(c, "129", 634, 397, 100, 42, size=34, color=BLUE, leading=38)
    para(c, "条 Great Expectations 规则全部通过", 634, 351, 250, 40, size=11.5, color=NAVY, leading=17)
    card(c, 614, 196, 304, 100, fill=ORANGE_LIGHT, stroke=ORANGE_LIGHT)
    para(c, "3 份日志", 634, 273, 140, 32, size=21, color=ORANGE, leading=25)
    para(c, "原始行保持不可变；只在分析视图删除完全重复行。", 634, 238, 250, 38, size=10.5, color=NAVY, leading=16)
    card(c, 42, 112, 876, 62, fill=WHITE)
    para(c, "关键规则", 62, 154, 90, 20, size=12.5, color=NAVY, leading=15)
    para(c, "二元标签合法 · 时间与时长非负 · is_rand 与来源一致 · 用户／视频外键可解析 · 结果字段与整月统计特征不得泄漏", 154, 153, 730, 34, size=10.5, color=MUTED, leading=16)
    footer(c, "Source: reports/data-quality/cleaning_manifest.json · gx_validation_results.json · Gate2-数据质量报告.md")


def draw_page5(c, data: dict[str, object], chart: Path) -> None:
    title_block(c, "05", "同一模型，在不同流量里排名会反转", "这意味着历史推荐结果会影响离线评价，不能只凭一个分数选方案。", 5)
    c.drawImage(str(chart), 42, 186, width=590, height=250, preserveAspectRatio=True, mask="auto")
    card(c, 654, 306, 264, 116, fill=NAVY, stroke=NAVY)
    para(c, "标准曝光", 676, 398, 100, 20, size=11, color="#B9C6D5", leading=14)
    para(c, "MultiTask 0.6236", 676, 368, 210, 28, size=19, color=WHITE, leading=23)
    para(c, "在已记录曝光候选上排名第一", 676, 338, 208, 32, size=9.8, color="#D6E0EC", leading=14)
    card(c, 654, 186, 264, 102, fill=ORANGE_LIGHT, stroke=ORANGE_LIGHT)
    para(c, "随机曝光敏感性", 676, 266, 130, 20, size=11, color=ORANGE, leading=14)
    para(c, "ItemCF 0.3247", 676, 238, 205, 26, size=18, color=NAVY, leading=22)
    para(c, "模型顺序发生反转", 676, 210, 205, 22, size=10, color=MUTED, leading=14)
    card(c, 42, 104, 876, 60, fill=TEAL_LIGHT, stroke=TEAL_LIGHT)
    para(c, "产品判断", 62, 145, 90, 20, size=12.5, color=TEAL, leading=15)
    para(c, "不能把单一离线榜单当作普适最优；Gate 4 必须同时报告标准日志、随机日志敏感性、有效消费和生态护栏。", 154, 145, 730, 38, size=10.8, color=NAVY, leading=16)
    footer(c, f"Source: reports/gate3/baseline_metrics.csv · Run {data['run3']['run_id']} · 用户级 bootstrap 95% CI · E3 离线证据")


def draw_page6(c, chart: Path) -> None:
    title_block(c, "06", "找到“用户想看，却没有被充分分发”的内容机会", "先用份额差找到优先级，再继续验证是供给不足、分发不足，还是人群结构差异。", 6)
    c.drawImage(str(chart), 42, 184, width=590, height=248, preserveAspectRatio=True, mask="auto")
    card(c, 654, 300, 264, 122, fill=BLUE_LIGHT, stroke=BLUE_LIGHT)
    para(c, "标签 39", 676, 396, 110, 24, size=17, color=BLUE, leading=20)
    para(c, "历史需求 - 测试曝光 = +5.85pp", 676, 365, 210, 26, size=11, color=NAVY, leading=15)
    para(c, "优先拆成“补供给”与“调曝光”两个假设。", 676, 331, 210, 40, size=10, color=MUTED, leading=15)
    card(c, 654, 184, 264, 96, fill=ORANGE_LIGHT, stroke=ORANGE_LIGHT)
    para(c, "标签 2", 676, 258, 100, 23, size=16, color=ORANGE, leading=19)
    para(c, "测试曝光 - 测试消费 = +1.42pp", 676, 229, 210, 25, size=10.8, color=NAVY, leading=15)
    para(c, "先按人群与 tab 下钻，再判断调配策略。", 676, 204, 210, 25, size=9.7, color=MUTED, leading=14)
    card(c, 42, 104, 876, 58)
    para(c, "待验证，而非结论", 62, 143, 130, 18, size=11.5, color=RED, leading=14)
    para(c, "份额差可以定位优先级，但不能证明缺口由供给不足、算法偏置或用户偏好变化造成。", 196, 143, 680, 30, size=10.6, color=MUTED, leading=15)
    footer(c, "Source: reports/gate3/tag_supply_demand.csv · 标签为公开数据中的 numeric ID · 份额均来自固定时间窗")


def draw_page7(c) -> None:
    title_block(c, "07", "针对问题，设计 4 种分发策略", "先用验证数据选参数，再固定方案比较，避免为了测试结果临时调参。", 7)
    strategies = [
        ("S0", "冻结基线", "MultiTaskHashSGD", NAVY),
        ("S1", "协同融合", "学习分数 + ItemCF", BLUE),
        ("S2", "多样性重排", "作者／标签重复惩罚", TEAL),
        ("S3", "长尾探索", "历史低曝光内容加权", GOLD),
        ("S4", "风险与疲劳", "历史负反馈 + 作者疲劳", ORANGE),
    ]
    x_positions = [42, 218, 394, 570, 746]
    for (code, name, desc, accent), x in zip(strategies, x_positions):
        card(c, x, 252, 162, 164)
        c.setFillColor(HexColor(accent))
        c.roundRect(x + 16, 372, 46, 26, 13, fill=1, stroke=0)
        para(c, code, x + 24, 391, 30, 16, size=10, color=WHITE, leading=12, align=TA_CENTER)
        para(c, name, x + 16, 348, 130, 24, size=14.5, color=NAVY, leading=18)
        para(c, desc, x + 16, 313, 130, 52, size=10.2, color=MUTED, leading=15)
        para(c, "不可变快照", x + 16, 276, 100, 20, size=9, color=accent, leading=12)
    para(c, "验证与决策流程", 42, 226, 180, 24, size=15, color=NAVY, leading=18)
    steps = ["验证集选参", "冻结策略", "标准日志回放", "随机日志敏感性", "配对区间 + 护栏", "决策门"]
    x = 42
    for idx, step in enumerate(steps):
        c.setFillColor(HexColor(BLUE if idx < 2 else ORANGE if idx == 5 else "#E5EAF0"))
        c.roundRect(x, 144, 126, 44, 10, fill=1, stroke=0)
        para(c, step, x + 8, 173, 110, 25, size=9.5, color=WHITE if idx < 2 or idx == 5 else NAVY, leading=12, align=TA_CENTER)
        if idx < len(steps) - 1:
            c.setStrokeColor(HexColor("#AAB6C4"))
            c.line(x + 130, 166, x + 145, 166)
        x += 146
    footer(c, "Source: config/gate4_strategies.json · reports/gate4/strategy_snapshots.json · validation_selection.csv")


def draw_page8(c, data: dict[str, object], interval_chart: Path, guardrail_chart: Path) -> None:
    title_block(c, "08", "一个策略看起来变好，也不能急着上线", "多样性策略降低了重复，但有效消费的改善不稳定，而且内容覆盖下降。", 8)
    c.drawImage(str(interval_chart), 42, 202, width=548, height=200, preserveAspectRatio=True, mask="auto")
    c.drawImage(str(guardrail_chart), 600, 246, width=318, height=145, preserveAspectRatio=True, mask="auto")
    card(c, 600, 174, 318, 60, fill=ORANGE_LIGHT, stroke=ORANGE_LIGHT)
    para(c, "S2 权衡", 620, 215, 80, 18, size=11.5, color=ORANGE, leading=14)
    para(c, "重复下降，但内容覆盖约 88.49% → 87.54%。", 704, 215, 190, 35, size=9.8, color=NAVY, leading=14)
    card(c, 42, 102, 876, 62, fill=NAVY, stroke=NAVY)
    para(c, "最终判定", 62, 144, 100, 20, size=12.5, color="#B9C6D5", leading=15)
    para(c, "S1–S4 全部 ITERATE_AND_RETEST；本轮没有策略进入线上 A/B 候选。", 166, 145, 710, 28, size=13, color=WHITE, leading=18)
    footer(c, f"Source: strategy_metrics.csv · strategy_deltas.csv · offline_decisions.csv · Run {data['run4']['run_id']} · 300 次用户级配对 bootstrap")


def draw_page9(c) -> None:
    title_block(c, "09", "如果进入真实业务，我会这样验证", "把离线发现变成可证伪的线上实验；本页是实验方案，不是已经执行的 A/B。", 9)
    card(c, 42, 236, 248, 170, fill=BLUE_LIGHT, stroke=BLUE_LIGHT)
    para(c, "随机化与触发", 64, 380, 160, 24, size=16, color=BLUE, leading=19)
    bullet_list(c, [
        "随机化单元：用户",
        "同一用户固定分组",
        "触发：进入目标 Feed 且至少 2 个 eligible 候选",
        "assigned 与 exposed 分开记录",
    ], 64, 340, 204, size=10.2, gap=4)
    card(c, 312, 236, 294, 170, fill=TEAL_LIGHT, stroke=TEAL_LIGHT)
    para(c, "指标树", 334, 380, 110, 24, size=16, color=TEAL, leading=19)
    bullet_list(c, [
        "主指标：用户级有效消费率",
        "互证：播放时长",
        "护栏：负反馈、作者／内容重复、覆盖与集中度",
        "收入：N/A，等待真实业务定义",
    ], 334, 340, 248, size=10.2, gap=4)
    card(c, 628, 236, 290, 170, fill=ORANGE_LIGHT, stroke=ORANGE_LIGHT)
    para(c, "实验健康", 650, 380, 120, 24, size=16, color=ORANGE, leading=19)
    bullet_list(c, [
        "SRM 与 A/A",
        "触发率和跨组污染",
        "重复事件与版本一致性",
        "迟到事件与停止规则",
    ], 650, 340, 244, size=10.2, gap=4)
    card(c, 42, 154, 876, 76)
    para(c, "决策规则", 64, 207, 100, 18, size=12.5, color=NAVY, leading=15)
    para(c, "健康检查未通过 → 不生成效果结论；主指标区间不过门 → 继续迭代；主指标与护栏同时通过 → 才进入灰度讨论。", 168, 207, 714, 48, size=11, color=MUTED, leading=17)
    card(c, 42, 92, 876, 44, fill="#FDECEE", stroke="#FDECEE")
    para(c, "未执行声明：当前公开数据不足以设置真实线上 MDE、样本量与商业指标，必须在业务环境中重新预注册。", 64, 123, 830, 24, size=10.4, color=RED, leading=14, align=TA_CENTER)
    footer(c, "Source: reports/gate4/Gate4-线上AB实验设计.md · 本页为 E4 实验设计证据")


def draw_page10(c, data: dict[str, object]) -> None:
    title_block(c, "10", "这套项目能证明什么", "价值不在于堆模型，而在于把问题、策略、评估和决策连接成闭环。", 10)
    mapping = [
        ("问题拆解", "把“推荐不好”拆成供需错配、分发效率与体验生态问题"),
        ("策略设计", "针对不同问题提出协同、多样性、长尾和疲劳控制方案"),
        ("多目标决策", "不只看消费收益，同时检查重复、覆盖和负反馈代价"),
        ("实验意识", "固定评估规则，并设计从离线重测到线上 A/B 的决策门"),
        ("边界意识", "知道哪些结论有证据，哪些仍需真实业务数据验证"),
    ]
    y = 395
    for idx, (ability, evidence) in enumerate(mapping, 1):
        c.setFillColor(HexColor(BLUE_LIGHT))
        c.circle(66, y - 7, 15, fill=1, stroke=0)
        para(c, f"{idx:02d}", 55, y + 2, 22, 14, size=8.5, color=BLUE, leading=10, align=TA_CENTER)
        para(c, ability, 96, y + 5, 120, 20, size=13, color=NAVY, leading=16)
        para(c, evidence, 220, y + 4, 650, 30, size=10.5, color=MUTED, leading=15)
        y -= 52
    card(c, 42, 80, 876, 64, fill=NAVY, stroke=NAVY)
    para(c, "一句话总结", 64, 124, 110, 18, size=11.5, color="#B9C6D5", leading=14)
    para(c, "我完成的不是一个“高分模型”，而是一套能帮助业务判断下一步该做什么的推荐策略工作流。", 176, 125, 706, 42, size=12.2, color=WHITE, leading=18)
    footer(c, "Artifact map: README.md · 04-证据索引与声明边界.md · reports/gate2–gate5 · notebooks/01–03 · scripts/validate_* · 个人项目")


def build_pdf(data: dict[str, object], assets: dict[str, Path]) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(TTFont(FONT, str(PDF_FONT_PATH)))
    c = canvas.Canvas(str(PDF_PATH), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("FlowLens 推荐分发项目介绍")
    c.setAuthor("FlowLens personal project")
    draw_cover(c, data); c.showPage()
    draw_page2(c); c.showPage()
    draw_page3(c, data); c.showPage()
    draw_page4(c, data, assets["gate2"]); c.showPage()
    draw_page5(c, data, assets["gate3"]); c.showPage()
    draw_page6(c, assets["tags"]); c.showPage()
    draw_page7(c); c.showPage()
    draw_page8(c, data, assets["intervals"], assets["guardrails"]); c.showPage()
    draw_page9(c); c.showPage()
    draw_page10(c, data); c.showPage()
    c.save()


def image_data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def section(page: int, kicker: str, title: str, subtitle: str, body: str, dark: bool = False) -> str:
    mode = " dark" if dark else ""
    return f'''<section class="page{mode}" id="p{page}">
      <div class="page-number">{page:02d} / 10</div>
      <div class="kicker">{html.escape(kicker)}</div>
      <h2>{title}</h2>
      <p class="subtitle">{subtitle}</p>
      <div class="body">{body}</div>
    </section>'''


def build_html(data: dict[str, object], assets: dict[str, Path]) -> None:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    imgs = {k: image_data_uri(v) for k, v in assets.items()}
    pages = []
    pages.append(section(1, "90 秒项目速览", "FlowLens", "我用公开短视频日志，完整模拟了一次推荐分发策略迭代", f'''
      <div class="hero-copy">从“为什么用户没有看到合适的内容”出发，我先定位供需与消费问题，再设计 4 类分发策略，最后判断它们应该上线、重测，还是停止。</div>
      <div class="chips"><span>发现问题</span><span>设计策略</span><span>评估取舍</span><span>给出决策</span></div>
      <div class="target">一句话结果：找到了明确的分发缺口，但没有把不确定的离线收益包装成“可以上线”。</div>
      <div class="meta">个人项目 · 前 3 页 90 秒看懂 · 后 7 页查看方法与证据</div>
    ''', dark=True))
    pages.append(section(2, "90 秒速览 · 我做了什么", "把一次推荐策略迭代完整走通", "不是只训练一个模型，而是回答业务最终要做的三个决定。", '''
      <div class="grid three">
        <article><b>01 · 问题在哪里</b><p>把内容生产、曝光和消费串起来，区分“用户想看但没被分到”和“已经分到却没有消费”两类问题。</p></article>
        <article><b>02 · 策略怎么改</b><p>针对问题设计协同融合、多样性、长尾探索、风险与疲劳 4 类策略，并在相同候选集上公平比较。</p></article>
        <article><b>03 · 值不值得上线</b><p>同时看有效消费、重复、覆盖与负反馈。最终判断不是谁分最高，而是谁有资格进入线上 A/B。</p></article>
      </div>
      <div class="callout dark">最终交付：问题清单 + 4 类策略方案 + 冻结评估结果 + 一套线上 A/B 实验蓝图。</div>
      <div class="source">第 1–3 页为非技术速览；第 4–10 页提供指标、图表与可复现证据。</div>
    '''))
    pages.append(section(3, "90 秒速览 · 关键结论", "三个发现，决定下一步怎么做", "项目的价值不是给出一个漂亮分数，而是把分析结果翻译成可执行动作。", '''
      <div class="grid three">
        <article><b>发现 1 · 单一榜单会误导</b><p>同一批模型在常规曝光和随机曝光中的排名发生反转。动作：不凭一张离线榜单直接选策略。</p></article>
        <article><b>发现 2 · 存在内容机会</b><p>标签 39 的需求份额比曝光份额高 5.85pp。动作：继续区分是供给不足，还是分发不足。</p></article>
        <article><b>发现 3 · 收益伴随代价</b><p>多样性策略降低了重复，但内容覆盖下降，主指标区间跨 0。动作：先调权重重测，不进入 A/B。</p></article>
      </div>
      <div class="callout teal">最终建议：保留问题方向，暂不宣称策略成功；下一轮先修复覆盖护栏，再用线上随机实验验证真实增量。</div>
      <div class="source">以上结论来自公开日志的离线回放，只支持发现问题与比较方案，不代表真实线上提升。</div>
    '''))
    pages.append(section(4, "深入材料 · 数据是否可信", "先确认数据能回答问题", "在分析前处理重复、标签一致性、关联覆盖与时间可用性，避免用脏数据制造结论。", f'''
      <div class="layout chart-aside"><img src="{imgs['gate2']}" alt="三份日志原始与清洗行数对比"><div><div class="metric"><strong>129</strong><span>条 Great Expectations 规则全部通过</span></div><div class="metric warm"><strong>3 份日志</strong><span>原始行不可变，只在分析视图删除完全重复行</span></div></div></div>
      <div class="callout">关键规则：二元标签合法 · 时间与时长非负 · is_rand 与来源一致 · 外键可解析 · 结果字段和整月统计不得泄漏</div>
      <div class="source">Source: cleaning_manifest.json · gx_validation_results.json · Gate2-数据质量报告.md</div>
    '''))
    pages.append(section(5, "深入材料 · 基线选择", "同一模型，在不同流量里排名会反转", "这意味着历史推荐结果会影响离线评价，不能只凭一个分数选方案。", f'''
      <div class="layout chart-aside"><img src="{imgs['gate3']}" alt="标准与随机曝光日志上的三种模型NDCG对比"><div><div class="metric dark"><span>标准曝光</span><strong>MultiTask 0.6236</strong></div><div class="metric warm"><span>随机曝光敏感性</span><strong>ItemCF 0.3247</strong></div></div></div>
      <div class="callout teal">产品判断：不能把单一离线榜单当作普适最优；策略对比必须同时报告敏感性、有效消费和生态护栏。</div>
      <div class="source">Source: baseline_metrics.csv · 用户级 bootstrap 95% CI · E3 离线证据</div>
    '''))
    pages.append(section(6, "深入材料 · 问题定位", "找到“用户想看，却没有被充分分发”的内容机会", "先用份额差找到优先级，再继续验证是供给不足、分发不足，还是人群结构差异。", f'''
      <div class="layout chart-aside"><img src="{imgs['tags']}" alt="标签供需与消费份额缺口"><div><div class="metric"><strong>标签 39</strong><span>需求 - 曝光 = +5.85pp<br>拆成补供给与调曝光两个假设</span></div><div class="metric warm"><strong>标签 2</strong><span>曝光 - 消费 = +1.42pp<br>先按人群与 tab 下钻</span></div></div></div>
      <div class="callout risk">份额差能定位优先级，但不能证明缺口的因果来源。</div>
      <div class="source">Source: reports/gate3/tag_supply_demand.csv · 标签为 numeric ID</div>
    '''))
    pages.append(section(7, "深入材料 · 策略设计", "针对问题，设计 4 种分发策略", "先用验证数据选参数，再固定方案比较，避免为了测试结果临时调参。", '''
      <div class="strategy-row"><article><b>S0</b><h3>冻结基线</h3><p>MultiTaskHashSGD</p></article><article><b>S1</b><h3>协同融合</h3><p>学习分数 + ItemCF</p></article><article><b>S2</b><h3>多样性重排</h3><p>作者／标签重复惩罚</p></article><article><b>S3</b><h3>长尾探索</h3><p>历史低曝光内容加权</p></article><article><b>S4</b><h3>风险与疲劳</h3><p>负反馈 + 作者疲劳</p></article></div>
      <div class="process"><span>验证集选参</span><i>→</i><span>冻结策略</span><i>→</i><span>双日志回放</span><i>→</i><span>配对区间</span><i>→</i><span>多目标护栏</span><i>→</i><span>决策门</span></div>
      <div class="source">Source: gate4_strategies.json · strategy_snapshots.json · validation_selection.csv</div>
    '''))
    pages.append(section(8, "深入材料 · 最终决策", "一个策略看起来变好，也不能急着上线", "多样性策略降低了重复，但有效消费的改善不稳定，而且内容覆盖下降。", f'''
      <div class="grid two visuals"><img src="{imgs['intervals']}" alt="S1到S4相对S0的配对增量置信区间"><img src="{imgs['guardrails']}" alt="S0与S2的重复率和覆盖率对比"></div>
      <div class="callout dark">S1–S4 全部 ITERATE_AND_RETEST；本轮没有策略进入线上 A/B 候选。</div>
      <div class="source">Source: strategy_metrics.csv · strategy_deltas.csv · offline_decisions.csv · 300 次用户级配对 bootstrap</div>
    '''))
    pages.append(section(9, "深入材料 · 下一步", "如果进入真实业务，我会这样验证", "把离线发现变成可证伪的线上实验；本页是实验方案，不是已经执行的 A/B。", '''
      <div class="grid three"><article><b>随机化与触发</b><ul><li>用户级固定分组</li><li>进入目标 Feed 且至少 2 个候选</li><li>assigned 与 exposed 分开</li></ul></article><article><b>指标树</b><ul><li>主指标：用户级有效消费率</li><li>互证：播放时长</li><li>护栏：负反馈、重复、覆盖、集中度</li></ul></article><article><b>实验健康</b><ul><li>SRM 与 A/A</li><li>触发率与跨组污染</li><li>版本、重复事件和迟到事件</li></ul></article></div>
      <div class="callout">健康检查失败则不生成效果结论；主指标区间不过门则继续迭代；主指标与护栏同时通过才进入灰度讨论。</div>
      <div class="callout risk">当前公开数据不足以设置真实线上 MDE、样本量与商业指标，必须在业务环境中重新预注册。</div>
      <div class="source">Source: reports/gate4/Gate4-线上AB实验设计.md · E4 设计证据</div>
    '''))
    pages.append(section(10, "面试官可继续追问", "这套项目能证明什么", "价值不在于堆模型，而在于把问题、策略、评估和决策连接成闭环。", '''
      <div class="mapping"><div><b>问题拆解</b><span>把“推荐不好”拆成供需错配、分发效率与体验生态问题</span></div><div><b>策略设计</b><span>针对不同问题提出协同、多样性、长尾和疲劳控制方案</span></div><div><b>多目标决策</b><span>不只看消费收益，同时检查重复、覆盖和负反馈代价</span></div><div><b>实验意识</b><span>固定评估规则，并设计从离线重测到线上 A/B 的决策门</span></div><div><b>边界意识</b><span>知道哪些结论有证据，哪些仍需真实业务数据验证</span></div></div>
      <div class="callout dark final">我完成的不是一个“高分模型”，而是一套能帮助业务判断下一步该做什么的推荐策略工作流。</div>
      <div class="source">Artifact map: README.md · 04-证据索引与声明边界.md · reports/ · notebooks/ · scripts/validate_*</div>
    '''))

    css = f'''
    :root{{--navy:{NAVY};--blue:{BLUE};--orange:{ORANGE};--teal:{TEAL};--ink:{INK};--muted:{MUTED};--line:{LINE};--paper:{PAPER};}}
    *{{box-sizing:border-box}} body{{margin:0;background:#e9edf2;color:var(--ink);font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}}
    .page{{position:relative;width:min(1280px,calc(100vw - 24px));aspect-ratio:16/9;margin:24px auto;padding:54px 58px 44px;background:var(--paper);box-shadow:0 12px 44px rgba(20,38,61,.12);overflow:hidden}}
    .page.dark{{background:var(--navy);color:white}} .page-number{{position:absolute;right:38px;bottom:24px;font-size:12px;color:#8190a2}}
    .kicker{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--orange);font-weight:700;margin-bottom:14px}}
    h2{{font-size:34px;line-height:1.15;margin:0 0 10px;color:var(--navy)}} .dark h2{{font-size:62px;color:white;margin-top:52px}}
    .subtitle{{font-size:16px;line-height:1.6;color:var(--muted);margin:0 0 22px}} .dark .subtitle{{font-size:31px;color:white;max-width:860px}}
    .body{{height:calc(100% - 112px)}} .dark .body{{height:auto}}
    .hero-copy{{font-size:21px;line-height:1.65;color:#d5dfeb;max-width:760px;margin-top:30px}} .chips{{display:flex;gap:12px;margin-top:34px}}
    .chips span,.process span{{padding:9px 16px;border-radius:999px;background:#203a5b;color:#d6e0ec;font-size:13px}} .target{{margin-top:38px;color:#d6e0ec;font-size:15px}} .meta{{margin-top:18px;color:#91a4ba;font-size:12px}}
    .grid{{display:grid;gap:20px}} .grid.two{{grid-template-columns:1fr 1fr}} .grid.three{{grid-template-columns:repeat(3,1fr)}} article{{background:white;border:1px solid var(--line);border-radius:16px;padding:22px}}
    article b{{display:block;color:var(--navy);font-size:20px;margin-bottom:10px}} article p,article li{{color:var(--muted);font-size:14px;line-height:1.65}} article.navy{{background:var(--navy)}} article.navy b,article.navy li{{color:white}}
    .source{{position:absolute;left:58px;right:105px;bottom:24px;padding-top:8px;border-top:1px solid var(--line);font-size:10px;color:#7d8998}}
    .callout{{margin-top:18px;padding:14px 18px;border-radius:12px;background:white;border:1px solid var(--line);font-size:14px;line-height:1.55}} .callout.orange{{background:{ORANGE_LIGHT};border-color:{ORANGE_LIGHT}}} .callout.teal{{background:{TEAL_LIGHT};border-color:{TEAL_LIGHT}}} .callout.risk{{background:#fdecee;border-color:#fdecee;color:{RED}}} .callout.dark{{background:var(--navy);border-color:var(--navy);color:white}}
    .layout.chart-aside{{display:grid;grid-template-columns:2fr 1fr;gap:24px;align-items:center}} img{{width:100%;height:auto;display:block}} .metric{{padding:18px;border-radius:14px;background:{BLUE_LIGHT};margin-bottom:14px}} .metric.warm{{background:{ORANGE_LIGHT}}} .metric.dark{{background:var(--navy);color:white}} .metric strong{{display:block;font-size:26px;color:var(--blue);margin-bottom:7px}} .metric.warm strong{{color:var(--orange)}} .metric.dark strong{{color:white}} .metric span{{display:block;font-size:13px;line-height:1.55}}
    .strategy-row{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}} .strategy-row article{{padding:16px;min-height:150px}} .strategy-row b{{display:inline-block;background:var(--blue);color:white;border-radius:999px;padding:5px 11px;font-size:12px}} .strategy-row h3{{font-size:17px;margin:14px 0 7px}} .strategy-row p{{font-size:12px}}
    .process{{display:flex;align-items:center;justify-content:space-between;margin-top:28px}} .process span{{background:#e4eaf1;color:var(--navy)}} .process i{{font-style:normal;color:#8b98a8}} .visuals img{{background:white;border:1px solid var(--line);border-radius:14px;padding:10px}}
    .mapping{{display:grid;gap:10px}} .mapping div{{display:grid;grid-template-columns:150px 1fr;padding:14px 18px;background:white;border:1px solid var(--line);border-radius:12px}} .mapping b{{color:var(--navy);font-size:16px}} .mapping span{{color:var(--muted);font-size:14px}} .final{{margin-top:20px;font-size:17px;text-align:center}}
    @media(max-width:800px){{.page{{width:100%;margin:0 0 12px;aspect-ratio:auto;min-height:100vh;padding:36px 24px}}.grid.two,.grid.three,.layout.chart-aside,.strategy-row{{grid-template-columns:1fr}}.page{{overflow:visible}}.body{{height:auto}}.source{{position:static;margin-top:24px}}.process{{flex-wrap:wrap;gap:8px}}}}
    @media print{{@page{{size:13.333in 7.5in;margin:0}}body{{background:white}}.page{{width:13.333in;height:7.5in;margin:0;box-shadow:none;page-break-after:always}}}}
    '''
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FlowLens 推荐分发项目介绍</title><style>{css}</style></head><body>{''.join(pages)}</body></html>'''
    HTML_PATH.write_text(document, encoding="utf-8")
    DOCS_PATH.write_text(document, encoding="utf-8")


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "tmp" / "matplotlib").mkdir(parents=True, exist_ok=True)
    data = load_data()
    assets = {
        "gate2": save_gate2_volume(data),
        "gate3": save_gate3_baselines(data),
        "tags": save_tag_gaps(data),
        "intervals": save_gate4_intervals(data),
        "guardrails": save_gate4_guardrails(data),
    }
    build_html(data, assets)
    build_pdf(data, assets)
    print(f"Wrote HTML: {HTML_PATH}")
    print(f"Wrote GitHub Pages entry: {DOCS_PATH}")
    print(f"Wrote PDF: {PDF_PATH}")


if __name__ == "__main__":
    main()
