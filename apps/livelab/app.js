"use strict";

const offlineRun = window.rankLabOfflineRun || null;

const experiments = [
  {
    id: "SIM-FEED-241",
    name: "首页新鲜度 × 去重复",
    objective: "比较当前排序与“作者去重复 + 新鲜度补偿”策略，观察长播率与负反馈的描述性变化。",
    status: "running",
    stage: "模拟第 3 批次",
    owner: "策略产品 / 算法联调",
    seed: 40271,
    batch: 3,
    allocation: [0.5, 0.5],
    primaryMetric: "曝光后长播率",
    guardrails: "负反馈率、内容覆盖率",
    eventWindow: "24 h",
    behavior: { srmBias: 0, contamRate: 0.0007, violationRate: 0.0009, mismatchRate: 0 },
    variants: [
      {
        key: "A",
        name: "S0 当前排序",
        description: "维持当前相关性、热度与时效权重，作为策略基线。",
        version: "rank-sim-v2.3",
      },
      {
        key: "B",
        name: "S2 去重复 + 新鲜度",
        description: "对高频作者进行滑窗降权，并为近 48 小时内容增加轻量补偿。",
        version: "rank-sim-v2.3",
      },
    ],
    counts: {
      eligible: 25481,
      assignedA: 12760,
      assignedB: 12721,
      exposedA: 10564,
      exposedB: 10493,
      clickedA: 926,
      clickedB: 951,
      startedA: 804,
      startedB: 829,
      longA: 398,
      longB: 432,
      negativeA: 67,
      negativeB: 61,
      contamination: 19,
      violations: 2,
      versionMismatch: 0,
    },
    recent: [
      "第 3 批：事件链校验完成，未发现版本混用",
      "第 2 批：触发率稳定在演示阈值以上",
      "第 1 批：完成 50/50 稳定分流",
    ],
  },
  {
    id: "SIM-CHANNEL-087",
    name: "频道页兴趣扩展",
    objective: "测试跨兴趣簇召回能否提升点击后的有效播放，同时监控跨组污染和人群分配偏差。",
    status: "running",
    stage: "模拟第 2 批次",
    owner: "频道策略 / 数据分析",
    seed: 73119,
    batch: 2,
    allocation: [0.5, 0.5],
    primaryMetric: "点击后有效播放率",
    guardrails: "跳出率、负反馈率",
    eventWindow: "12 h",
    behavior: { srmBias: 0.045, contamRate: 0.0062, violationRate: 0.018, mismatchRate: 0.003 },
    variants: [
      {
        key: "A",
        name: "单兴趣簇召回",
        description: "只从用户最近活跃兴趣簇中召回频道内容。",
        version: "channel-sim-v1.8",
      },
      {
        key: "B",
        name: "跨簇探索召回",
        description: "保留主兴趣簇，并加入 15% 相邻兴趣内容作为探索流量。",
        version: "channel-sim-v1.9",
      },
    ],
    counts: {
      eligible: 14037,
      assignedA: 7619,
      assignedB: 6418,
      exposedA: 5037,
      exposedB: 4096,
      clickedA: 582,
      clickedB: 511,
      startedA: 449,
      startedB: 386,
      longA: 191,
      longB: 171,
      negativeA: 54,
      negativeB: 62,
      contamination: 87,
      violations: 31,
      versionMismatch: 37,
    },
    recent: [
      "第 2 批：检测到策略版本混用，需要核对发布范围",
      "第 2 批：A/B 分配偏离预期，触发 SRM 风险",
      "第 1 批：跨组用户污染超过演示阈值",
    ],
  },
  {
    id: "SIM-IMMERSIVE-163",
    name: "沉浸流起播前置",
    objective: "演示一个已结束实验的复盘状态：健康检查通过，但结果仍只作为模拟样本的描述性差异。",
    status: "ended",
    stage: "模拟已结束",
    owner: "沉浸流策略 / 客户端",
    seed: 91507,
    batch: 5,
    allocation: [0.6, 0.4],
    primaryMetric: "有效起播率",
    guardrails: "首帧耗时、退出率",
    eventWindow: "48 h",
    behavior: { srmBias: 0, contamRate: 0.0004, violationRate: 0.0005, mismatchRate: 0 },
    variants: [
      {
        key: "A",
        name: "点击后起播",
        description: "用户点击卡片后再请求播放资源，作为控制策略。",
        version: "player-sim-v3.1",
      },
      {
        key: "B",
        name: "可视区轻预取",
        description: "卡片进入可视区后预取首段资源，降低起播等待。",
        version: "player-sim-v3.1",
      },
    ],
    counts: {
      eligible: 38217,
      assignedA: 22948,
      assignedB: 15269,
      exposedA: 20491,
      exposedB: 13658,
      clickedA: 2017,
      clickedB: 1421,
      startedA: 1778,
      startedB: 1284,
      longA: 831,
      longB: 613,
      negativeA: 128,
      negativeB: 79,
      contamination: 13,
      violations: 1,
      versionMismatch: 0,
    },
    recent: [
      "第 5 批：达到预设模拟样本上限，实验结束",
      "第 4 批：健康检查持续通过",
      "第 3 批：确认客户端版本一致",
    ],
  },
];

const state = {
  activeExperimentId: experiments[0].id,
  activeView: "overview",
  filter: "all",
  focusedCheckId: null,
  selectedMetricIndex: 2,
  lastBatchReceipt: null,
  isSimulating: false,
  simulationPhase: "",
  toastTimer: null,
};

const els = {
  experimentList: document.querySelector("#experiment-list"),
  experimentCount: document.querySelector("#experiment-count"),
  experimentContext: document.querySelector("#experiment-context"),
  viewTabs: document.querySelector("#view-tabs"),
  viewRoot: document.querySelector("#view-root"),
  healthChecks: document.querySelector("#health-checks"),
  healthSummary: document.querySelector("#health-summary"),
  toggleRun: document.querySelector("#toggle-run"),
  simulateBatch: document.querySelector("#simulate-batch"),
  toast: document.querySelector("#toast"),
  offlineRun: document.querySelector("#offline-run-shell"),
};

const formatInteger = new Intl.NumberFormat("zh-CN");

function icon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getExperiment() {
  return experiments.find((experiment) => experiment.id === state.activeExperimentId);
}

function total(experiment, keyA, keyB) {
  return experiment.counts[keyA] + experiment.counts[keyB];
}

function safeRate(numerator, denominator) {
  return denominator > 0 ? numerator / denominator : 0;
}

function percent(value, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function points(value, digits = 2) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)} pp`;
}

function offlineMetricValue(metric, value) {
  return metric.key.startsWith("ndcg") ? Number(value).toFixed(4) : percent(Number(value), 2);
}

function offlineMetricDelta(metric) {
  const value = Number(metric.delta);
  const sign = value > 0 ? "+" : "";
  return metric.key.startsWith("ndcg") ? `${sign}${value.toFixed(4)}` : points(value, 2);
}

function renderOfflineRun() {
  if (!els.offlineRun || !offlineRun) return;
  const ndcg = offlineRun.metrics.find((metric) => metric.key === "ndcg_at_5");
  const ecr = offlineRun.metrics.find((metric) => metric.key === "ecr_at_5");
  const checksPassed = offlineRun.health_checks.filter((check) => check.status === "PASS").length;
  els.offlineRun.hidden = false;
  els.offlineRun.innerHTML = `
    <div class="offline-run-heading">
      <div>
        <span class="eyebrow">RANKLAB REAL OFFLINE ARTIFACT · ${escapeHtml(offlineRun.evidence_level)}</span>
        <h2 id="offline-run-title">${escapeHtml(offlineRun.name)}</h2>
        <p>${escapeHtml(offlineRun.summary)}</p>
      </div>
      <span class="badge badge-warning">${escapeHtml(offlineRun.decision)}</span>
    </div>
    <div class="offline-run-grid">
      <article><span>统一评估 cohort</span><strong>${formatInteger.format(offlineRun.eligible_users)} 用户</strong><small>${formatInteger.format(offlineRun.sampling.request_count)} 请求 · ${formatInteger.format(offlineRun.sampling.candidate_count)} 候选</small></article>
      <article><span>NDCG@5</span><strong>${offlineMetricValue(ndcg, ndcg.baseline)} → ${offlineMetricValue(ndcg, ndcg.metarank)}</strong><small>差异 ${offlineMetricDelta(ndcg)} · 95% CI [${Number(ndcg.ci_low).toFixed(4)}, ${Number(ndcg.ci_high).toFixed(4)}]</small></article>
      <article><span>Top-5 ECR</span><strong>${offlineMetricValue(ecr, ecr.baseline)} → ${offlineMetricValue(ecr, ecr.metarank)}</strong><small>差异 ${offlineMetricDelta(ecr)} · 验证集未过门</small></article>
      <article><span>证据健康</span><strong>${checksPassed} / ${offlineRun.health_checks.length} 通过</strong><small>冻结测试集 ${offlineRun.health_checks.at(-1).status} · 未偷看</small></article>
    </div>
    <div class="offline-run-footnote">
      <span>${icon("shield")}候选守恒与元数据覆盖通过</span>
      <span>${icon("file")}运行 ${escapeHtml(offlineRun.id)}</span>
      <span>${icon("alert")}${formatInteger.format(offlineRun.metadata.missing_duration_items)} 个时长缺失采用哨兵值 + 缺失标记</span>
    </div>
  `;
}

function relativeChange(control, treatment) {
  if (!control) return 0;
  return (treatment - control) / control;
}

function erfc(x) {
  const z = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * z);
  const polynomial =
    (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t);
  const erf = 1 - polynomial * Math.exp(-z * z);
  return x >= 0 ? 1 - erf : 1 + erf;
}

function srmPValue(experiment) {
  const observed = [experiment.counts.assignedA, experiment.counts.assignedB];
  const n = observed[0] + observed[1];
  const expected = [n * experiment.allocation[0], n * experiment.allocation[1]];
  const chiSquare = observed.reduce((sum, value, index) => {
    return sum + (value - expected[index]) ** 2 / expected[index];
  }, 0);
  return Math.max(0, Math.min(1, erfc(Math.sqrt(chiSquare / 2))));
}

function healthChecks(experiment) {
  const assigned = total(experiment, "assignedA", "assignedB");
  const exposed = total(experiment, "exposedA", "exposedB");
  const starts = total(experiment, "startedA", "startedB");
  const pValue = srmPValue(experiment);
  const triggerRate = safeRate(exposed, assigned);
  const contaminationRate = safeRate(experiment.counts.contamination, assigned);
  const completeness = 1 - safeRate(experiment.counts.violations, Math.max(starts, 1));
  const mismatchRate = safeRate(experiment.counts.versionMismatch, exposed);

  return [
    {
      id: "srm",
      name: "分流比例（SRM）",
      level: pValue < 0.01 ? "danger" : "healthy",
      reading: `p = ${pValue < 0.0001 ? "< 0.0001" : pValue.toFixed(4)}`,
      detail:
        pValue < 0.01
          ? "观察分配与预设比例显著偏离；先排查分桶、资格人群或埋点。"
          : "未触发演示阈值；这不是对随机化正确性的绝对证明。",
      rule: "演示规则：p < 0.01 触发风险",
    },
    {
      id: "trigger",
      name: "实验触发率",
      level: triggerRate >= 0.75 ? "healthy" : triggerRate >= 0.6 ? "warning" : "danger",
      reading: percent(triggerRate, 1),
      detail:
        triggerRate >= 0.75
          ? "进入分流的用户大多实际看到策略结果。"
          : "分流后未曝光比例偏高，指标可能被未触发用户稀释。",
      rule: "演示规则：≥75% 通过，60%–75% 关注",
    },
    {
      id: "contamination",
      name: "跨组污染",
      level:
        contaminationRate <= 0.002
          ? "healthy"
          : contaminationRate <= 0.005
            ? "warning"
            : "danger",
      reading: `${formatInteger.format(experiment.counts.contamination)} 人 · ${percent(contaminationRate, 2)}`,
      detail:
        contaminationRate <= 0.002
          ? "跨组用户占比处于演示容忍范围。"
          : "存在用户同时接触 A/B 策略的风险，需要核对分桶主键与缓存。",
      rule: "演示规则：≤0.20% 通过，0.20%–0.50% 关注",
    },
    {
      id: "completeness",
      name: "事件链完整性",
      level: completeness >= 0.995 ? "healthy" : completeness >= 0.985 ? "warning" : "danger",
      reading: percent(completeness, 2),
      detail:
        completeness >= 0.995
          ? "关键事件顺序和上游事件引用基本完整。"
          : "发现缺少曝光或起播前置事件的记录，转化链暂不可直接解释。",
      rule: "演示规则：≥99.50% 通过，98.50%–99.50% 关注",
    },
    {
      id: "version",
      name: "策略版本一致性",
      level: experiment.counts.versionMismatch === 0 ? "healthy" : "danger",
      reading:
        experiment.counts.versionMismatch === 0
          ? "0 条混用"
          : `${formatInteger.format(experiment.counts.versionMismatch)} 条混用 · ${percent(mismatchRate, 2)}`,
      detail:
        experiment.counts.versionMismatch === 0
          ? "两组事件均携带预期策略版本。"
          : "检测到非预期策略版本；需要核对发布批次和客户端缓存。",
      rule: "演示规则：必须为 0",
    },
  ];
}

function healthRollup(experiment) {
  const checks = healthChecks(experiment);
  const danger = checks.filter((check) => check.level === "danger").length;
  const warning = checks.filter((check) => check.level === "warning").length;
  const healthy = checks.filter((check) => check.level === "healthy").length;
  return {
    checks,
    danger,
    warning,
    healthy,
    level: danger > 0 ? "danger" : warning > 0 ? "warning" : "healthy",
  };
}

function statusCopy(experiment) {
  if (experiment.status === "ended") return { label: "已结束", className: "ended" };
  if (experiment.status === "paused") return { label: "已暂停", className: "attention" };
  return { label: "运行中", className: "running" };
}

function showToast(message) {
  clearTimeout(state.toastTimer);
  els.toast.textContent = message;
  els.toast.classList.add("is-visible");
  state.toastTimer = setTimeout(() => {
    els.toast.classList.remove("is-visible");
  }, 2600);
}

function renderExperimentList() {
  const visible = experiments.filter((experiment) => {
    if (state.filter === "all") return true;
    if (state.filter === "running") return experiment.status === "running";
    return healthRollup(experiment).level !== "healthy";
  });

  els.experimentCount.textContent = String(visible.length);
  if (!visible.length) {
    els.experimentList.innerHTML = '<div class="empty-filter">当前筛选下没有实验。切换到“全部”查看完整队列。</div>';
    return;
  }

  els.experimentList.innerHTML = visible
    .map((experiment) => {
      const status = statusCopy(experiment);
      const rollup = healthRollup(experiment);
      const healthLabel =
        rollup.level === "healthy" ? "健康" : rollup.level === "warning" ? "关注" : "阻断";
      return `
        <button
          class="experiment-item"
          type="button"
          data-experiment-id="${experiment.id}"
          aria-current="${experiment.id === state.activeExperimentId}"
        >
          <span class="experiment-indicator" aria-hidden="true"></span>
          <span class="experiment-copy">
            <span class="status-line"><span class="status-dot ${status.className}"></span>${status.label} · ${healthLabel}</span>
            <strong>${escapeHtml(experiment.name)}</strong>
            <small>${experiment.id} · ${formatInteger.format(experiment.counts.eligible)} eligible</small>
          </span>
          ${icon("chevron")}
        </button>
      `;
    })
    .join("");
}

function renderContext(experiment) {
  const status = statusCopy(experiment);
  els.experimentContext.innerHTML = `
    <div class="context-title">
      <span class="badge badge-info">${icon("flask")}模拟实验 · ${experiment.id}</span>
      <h2>${escapeHtml(experiment.name)}</h2>
      <p>${escapeHtml(experiment.objective)}</p>
    </div>
    <div class="context-meta">
      <span class="badge"><span class="status-dot ${status.className}"></span>${status.label}</span>
      <span class="badge">${escapeHtml(experiment.stage)}</span>
      <span class="badge">${escapeHtml(experiment.eventWindow)} 窗口</span>
    </div>
  `;
}

function renderRunControls(experiment) {
  const isEnded = experiment.status === "ended";
  const isPaused = experiment.status === "paused";

  els.toggleRun.disabled = isEnded || state.isSimulating;
  els.toggleRun.innerHTML = isEnded
    ? `${icon("check")}<span>实验已结束</span>`
    : isPaused
      ? `${icon("play")}<span>恢复实验</span>`
      : `${icon("pause")}<span>暂停实验</span>`;

  els.simulateBatch.disabled = isEnded || isPaused || state.isSimulating;
  els.simulateBatch.setAttribute("aria-busy", String(state.isSimulating));
  els.simulateBatch.innerHTML = state.isSimulating
    ? `${icon("activity")}<span>${escapeHtml(state.simulationPhase || "正在准备模拟…")}</span>`
    : `${icon("play")}<span>模拟下一批事件</span>`;
}

function renderTabs() {
  els.viewTabs.querySelectorAll("button[data-view]").forEach((button) => {
    if (button.dataset.view === state.activeView) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
}

function experimentMetrics(experiment) {
  const c = experiment.counts;
  return [
    {
      name: "曝光点击率",
      definition: "clicked / exposed",
      a: safeRate(c.clickedA, c.exposedA),
      b: safeRate(c.clickedB, c.exposedB),
      numeratorA: c.clickedA,
      denominatorA: c.exposedA,
      numeratorB: c.clickedB,
      denominatorB: c.exposedB,
      guardrail: false,
      better: "higher",
      interpretation: "衡量策略曝光是否带来进一步点击，适合判断卡片与排序结果的即时吸引力。",
    },
    {
      name: "曝光后起播率",
      definition: "content_start / exposed",
      a: safeRate(c.startedA, c.exposedA),
      b: safeRate(c.startedB, c.exposedB),
      numeratorA: c.startedA,
      denominatorA: c.exposedA,
      numeratorB: c.startedB,
      denominatorB: c.exposedB,
      guardrail: false,
      better: "higher",
      interpretation: "衡量曝光后是否真正进入内容消费，避免只用点击衡量策略价值。",
    },
    {
      name: "曝光后长播率",
      definition: "long_view / exposed",
      a: safeRate(c.longA, c.exposedA),
      b: safeRate(c.longB, c.exposedB),
      numeratorA: c.longA,
      denominatorA: c.exposedA,
      numeratorB: c.longB,
      denominatorB: c.exposedB,
      guardrail: false,
      better: "higher",
      interpretation: "这是当前主指标，关注策略是否把用户带到更有持续消费价值的内容。",
    },
    {
      name: "负反馈率",
      definition: "negative_feedback / exposed",
      a: safeRate(c.negativeA, c.exposedA),
      b: safeRate(c.negativeB, c.exposedB),
      numeratorA: c.negativeA,
      denominatorA: c.exposedA,
      numeratorB: c.negativeB,
      denominatorB: c.exposedB,
      guardrail: true,
      better: "lower",
      interpretation: "这是护栏指标，用来防止主指标改善的同时增加不喜欢、屏蔽等负向体验。",
    },
  ];
}

function renderOverview(experiment) {
  const c = experiment.counts;
  const assigned = total(experiment, "assignedA", "assignedB");
  const exposed = total(experiment, "exposedA", "exposedB");
  const clicked = total(experiment, "clickedA", "clickedB");
  const started = total(experiment, "startedA", "startedB");
  const longView = total(experiment, "longA", "longB");
  const rollup = healthRollup(experiment);
  const longA = safeRate(c.longA, c.exposedA);
  const longB = safeRate(c.longB, c.exposedB);
  const relative = relativeChange(longA, longB);
  const funnel = [
    ["Eligible", c.eligible],
    ["Assigned", assigned],
    ["Exposed", exposed],
    ["Clicked", clicked],
    ["Content start", started],
    ["Long view", longView],
  ];
  const narrativeTone = rollup.level === "danger" ? "danger" : rollup.level === "warning" ? "warning" : "";
  const narrativeTitle =
    rollup.level === "healthy"
      ? "当前可继续收集模拟样本"
      : rollup.level === "warning"
        ? "先关注实验质量，再扩大样本"
        : "暂停结果解读，优先修复实验质量";
  const narrativeBody =
    rollup.level === "healthy"
      ? "五项健康检查均未触发演示风险。B 组长播率的描述性差异可作为继续观察的线索，但还不能被写成真实线上增量。"
      : "当前至少一项检查未通过。即使指标看起来改善，也可能受到分流、触发、污染或事件缺失影响。";
  const receipt = state.lastBatchReceipt?.experimentId === experiment.id ? state.lastBatchReceipt : null;

  return `
    <div class="section-stack">
      <section class="stats-grid" aria-label="实验摘要指标">
        <article class="stat-card"><span>Eligible 用户</span><strong>${formatInteger.format(c.eligible)}</strong><small>固定种子模拟人群</small></article>
        <article class="stat-card"><span>触发率</span><strong>${percent(safeRate(exposed, assigned), 1)}</strong><small>exposed / assigned</small></article>
        <article class="stat-card" data-tone="${relative >= 0 ? "success" : "warning"}"><span>B 组长播率相对差异</span><strong>${relative >= 0 ? "+" : ""}${percent(relative, 1)}</strong><small>描述性差异，不是因果结论</small></article>
        <article class="stat-card" data-tone="${rollup.level === "healthy" ? "success" : "warning"}"><span>健康检查</span><strong>${rollup.healthy} / ${rollup.checks.length}</strong><small>${rollup.danger} 阻断 · ${rollup.warning} 关注</small></article>
      </section>

      ${
        receipt
          ? `<section class="batch-receipt" role="status" aria-live="polite">
              <span class="receipt-icon">${icon(receipt.level === "healthy" ? "check" : "alert")}</span>
              <div class="receipt-copy">
                <span class="eyebrow">SIMULATION RECEIPT · BATCH ${receipt.batch}</span>
                <h3>新批次已生成，诊断结果已同步更新</h3>
                <div class="receipt-stats">
                  <span><strong>+${formatInteger.format(receipt.eligibleAdded)}</strong> eligible</span>
                  <span><strong>${percent(receipt.triggerBefore, 1)} → ${percent(receipt.triggerAfter, 1)}</strong> 触发率</span>
                  <span><strong>${receipt.healthy}/${receipt.total}</strong> 健康检查通过</span>
                </div>
              </div>
              <div class="receipt-actions">
                <button class="button button-secondary receipt-review" type="button" data-focus-first-issue>${receipt.level === "healthy" ? "查看健康明细" : "定位首个异常"}</button>
                <button class="receipt-close" type="button" data-dismiss-receipt aria-label="关闭本次批次回执">${icon("x")}</button>
              </div>
            </section>`
          : ""
      }

      <div class="two-column">
        <section class="panel" aria-labelledby="funnel-title">
          <div class="panel-heading">
            <div><h3 id="funnel-title">事件漏斗</h3><p>从符合资格到长播的模拟事件链</p></div>
            <span class="badge badge-info">批次 ${experiment.batch}</span>
          </div>
          <div class="funnel-list">
            ${funnel
              .map(
                ([label, value]) => `
                  <div class="funnel-row">
                    <span class="funnel-label">${label}</span>
                    <span class="funnel-track" aria-hidden="true"><span class="funnel-fill" style="transform:scaleX(${safeRate(value, c.eligible).toFixed(4)})"></span></span>
                    <span class="funnel-value">${formatInteger.format(value)}</span>
                  </div>`,
              )
              .join("")}
          </div>
        </section>

        <section class="panel" aria-labelledby="reading-title">
          <div class="panel-heading"><div><h3 id="reading-title">当前解读</h3><p>把实验质量放在结果之前</p></div></div>
          <div class="narrative-box ${narrativeTone}">
            <h3>${narrativeTitle}</h3>
            <p>${narrativeBody}</p>
          </div>
          <dl class="definition-list">
            <div class="definition-row"><dt>主指标</dt><dd>${escapeHtml(experiment.primaryMetric)}</dd></div>
            <div class="definition-row"><dt>护栏指标</dt><dd>${escapeHtml(experiment.guardrails)}</dd></div>
            <div class="definition-row"><dt>负责人</dt><dd>${escapeHtml(experiment.owner)}</dd></div>
          </dl>
        </section>
      </div>

      <section class="panel" aria-labelledby="recent-title">
        <div class="panel-heading"><div><h3 id="recent-title">最近模拟事件</h3><p>用于讲解实验状态如何随批次变化</p></div></div>
        <div class="health-detail-list">
          ${experiment.recent
            .map(
              (item, index) => `
                <div class="health-detail" data-level="healthy">
                  <span class="health-detail-icon">${icon(index === 0 ? "activity" : "check")}</span>
                  <div><h3>${escapeHtml(item)}</h3><p>${index === 0 ? "最近批次" : `历史记录 ${index + 1}`}</p></div>
                  <span class="health-detail-value">SIM LOG</span>
                </div>`,
            )
            .join("")}
        </div>
      </section>
    </div>
  `;
}

function renderStrategy(experiment) {
  const assigned = total(experiment, "assignedA", "assignedB");
  return `
    <div class="section-stack">
      <section class="panel" aria-labelledby="variant-title">
        <div class="panel-heading">
          <div><h3 id="variant-title">策略方案与流量</h3><p>两个组只改变声明的策略变量，保持事件口径一致</p></div>
          <span class="badge badge-info">${Math.round(experiment.allocation[0] * 100)} / ${Math.round(experiment.allocation[1] * 100)}</span>
        </div>
        <div class="variant-grid">
          ${experiment.variants
            .map((variant, index) => {
              const assignedValue = index === 0 ? experiment.counts.assignedA : experiment.counts.assignedB;
              return `
                <article class="variant-card" data-variant="${variant.key}">
                  <div class="variant-topline">
                    <span class="variant-letter">${variant.key}</span>
                    <span class="badge ${index === 1 ? "badge-success" : ""}">${percent(safeRate(assignedValue, assigned), 1)} 实际分配</span>
                  </div>
                  <h3>${escapeHtml(variant.name)}</h3>
                  <p>${escapeHtml(variant.description)}</p>
                  <dl class="definition-list">
                    <div class="definition-row"><dt>预设流量</dt><dd>${percent(experiment.allocation[index], 0)}</dd></div>
                    <div class="definition-row"><dt>Assigned</dt><dd>${formatInteger.format(assignedValue)} 人</dd></div>
                    <div class="definition-row"><dt>策略版本</dt><dd>${escapeHtml(variant.version)}</dd></div>
                  </dl>
                </article>`;
            })
            .join("")}
        </div>
      </section>

      <section class="panel" aria-labelledby="contract-title">
        <div class="panel-heading"><div><h3 id="contract-title">实验合同</h3><p>面试中可以直接说明“什么变、什么不变、如何判断”</p></div></div>
        <dl class="definition-list">
          <div class="definition-row"><dt>目标问题</dt><dd>${escapeHtml(experiment.objective)}</dd></div>
          <div class="definition-row"><dt>唯一策略差异</dt><dd>${escapeHtml(experiment.variants[1].description)}</dd></div>
          <div class="definition-row"><dt>主指标</dt><dd>${escapeHtml(experiment.primaryMetric)}</dd></div>
          <div class="definition-row"><dt>护栏</dt><dd>${escapeHtml(experiment.guardrails)}</dd></div>
          <div class="definition-row"><dt>事件链</dt><dd>eligible → assigned → exposed → clicked → content_start → long_view / negative_feedback</dd></div>
          <div class="definition-row"><dt>证据等级</dt><dd>本地固定种子模拟，仅验证流程与诊断逻辑</dd></div>
        </dl>
      </section>
    </div>
  `;
}

function levelLabel(level) {
  if (level === "healthy") return "通过";
  if (level === "warning") return "关注";
  return "阻断";
}

function levelIcon(level) {
  if (level === "healthy") return "check";
  if (level === "warning") return "alert";
  return "x";
}

function levelBadge(level) {
  if (level === "healthy") return "badge-success";
  if (level === "warning") return "badge-warning";
  return "badge-danger";
}

function checkNextAction(checkId) {
  const actions = {
    srm: "核对分桶主键、资格人群过滤与 assigned 事件是否一致。",
    trigger: "按端版本和场景拆分 assigned → exposed 漏斗，定位未触发环节。",
    contamination: "排查用户标识、跨端缓存与策略降级是否导致同时进入 A/B。",
    completeness: "抽查事件顺序与上游 event_id，确认曝光、起播和长播链路可回溯。",
    version: "对照发布批次、客户端缓存与事件中的 strategy_version 字段。",
  };
  return actions[checkId] || "结合事件合同继续排查。";
}

function renderHealth(experiment) {
  const rollup = healthRollup(experiment);
  return `
    <div class="section-stack">
      <section class="panel" aria-labelledby="health-detail-title">
        <div class="panel-heading">
          <div><h3 id="health-detail-title">健康检查明细</h3><p>先验证实验是否可解释，再查看指标方向</p></div>
          <span class="badge ${levelBadge(rollup.level)}">${rollup.healthy} / ${rollup.checks.length} 通过</span>
        </div>
        <div class="health-detail-list">
          ${rollup.checks
            .map(
              (check) => `
                <article class="health-detail ${state.focusedCheckId === check.id ? "is-focused" : ""}" data-level="${check.level}" data-check-detail="${check.id}" tabindex="-1">
                  <span class="health-detail-icon">${icon(levelIcon(check.level))}</span>
                  <div>
                    <h3>${check.name} · ${levelLabel(check.level)}</h3>
                    <p>${check.detail}</p>
                    <p><strong>${check.rule}</strong></p>
                    <div class="health-action"><span>建议排查</span><strong>${checkNextAction(check.id)}</strong></div>
                  </div>
                  <span class="health-detail-value">${check.reading}</span>
                </article>`,
            )
            .join("")}
        </div>
      </section>

      <section class="narrative-box ${rollup.level === "danger" ? "danger" : rollup.level === "warning" ? "warning" : ""}" aria-label="健康检查结论">
        <h3>${rollup.level === "healthy" ? "可以继续模拟实验流程" : "当前不应直接解释 uplift"}</h3>
        <p>这些规则用于演示实验治理思路。生产环境还需要结合业务周期、分层抽样、功效分析、多重检验和真实告警策略。</p>
      </section>
    </div>
  `;
}

function renderMetrics(experiment) {
  const metrics = experimentMetrics(experiment);
  const rollup = healthRollup(experiment);
  const selectedIndex = Math.min(state.selectedMetricIndex, metrics.length - 1);
  const selected = metrics[selectedIndex];
  const selectedDelta = selected.b - selected.a;
  const selectedFavorable = selected.better === "higher" ? selectedDelta >= 0 : selectedDelta <= 0;
  return `
    <div class="section-stack">
      <section class="panel" aria-labelledby="metrics-title">
        <div class="panel-heading">
          <div><h3 id="metrics-title">A/B 描述性指标</h3><p>所有数字来自浏览器本地模拟；不计算或宣称真实业务显著性</p></div>
          <span class="badge ${levelBadge(rollup.level)}">${rollup.level === "healthy" ? "健康检查通过" : "结果解读受限"}</span>
        </div>
        <div class="metric-table-wrap">
          <table class="metric-table">
            <thead><tr><th>指标</th><th>A 控制组</th><th>B 实验组</th><th>绝对差异</th><th>相对差异</th></tr></thead>
            <tbody>
              ${metrics
                .map((metric, index) => {
                  const delta = metric.b - metric.a;
                  const relative = relativeChange(metric.a, metric.b);
                  const favorable = metric.better === "higher" ? delta >= 0 : delta <= 0;
                  return `
                    <tr class="${index === selectedIndex ? "is-selected" : ""}">
                      <td><button class="metric-select" type="button" data-metric-index="${index}" aria-pressed="${index === selectedIndex}"><strong>${metric.name}</strong><small>${metric.definition}${metric.guardrail ? " · 护栏" : ""}</small>${icon("chevron")}</button></td>
                      <td>${percent(metric.a, 2)}</td>
                      <td>${percent(metric.b, 2)}</td>
                      <td class="${favorable ? "delta-positive" : "delta-negative"}">${points(delta, 2)}</td>
                      <td class="${favorable ? "delta-positive" : "delta-negative"}">${relative >= 0 ? "+" : ""}${percent(relative, 1)}</td>
                    </tr>`;
                })
                .join("")}
            </tbody>
          </table>
        </div>
        <section class="metric-inspector" aria-live="polite" tabindex="-1">
          <div class="metric-inspector-heading">
            <div><span class="eyebrow">SELECTED METRIC</span><h3>${selected.name}</h3></div>
            <span class="badge ${selected.guardrail ? "badge-warning" : "badge-info"}">${selected.guardrail ? "护栏指标" : "核心行为指标"}</span>
          </div>
          <p>${selected.interpretation}</p>
          <div class="metric-breakdown-grid">
            <div class="metric-breakdown"><span>A 控制组</span><strong>${formatInteger.format(selected.numeratorA)} / ${formatInteger.format(selected.denominatorA)}</strong><small>${selected.definition} = ${percent(selected.a, 2)}</small></div>
            <div class="metric-breakdown"><span>B 实验组</span><strong>${formatInteger.format(selected.numeratorB)} / ${formatInteger.format(selected.denominatorB)}</strong><small>${selected.definition} = ${percent(selected.b, 2)}</small></div>
            <div class="metric-breakdown ${selectedFavorable ? "is-favorable" : "is-unfavorable"}"><span>方向判断</span><strong>${points(selectedDelta, 2)}</strong><small>${selectedFavorable ? "描述性方向符合预期" : "描述性方向需要关注"}；仍非真实因果结论</small></div>
          </div>
        </section>
      </section>

      <div class="two-column">
        <section class="panel">
          <div class="panel-heading"><div><h3>怎样解释这些数字</h3><p>推荐策略产品的结果页不能只报一个 uplift</p></div></div>
          <dl class="definition-list">
            <div class="definition-row"><dt>方向</dt><dd>先看主指标是否朝预期方向变化，再检查护栏是否恶化。</dd></div>
            <div class="definition-row"><dt>可信度</dt><dd>健康检查未通过时，差异只能用于定位问题，不能支持决策。</dd></div>
            <div class="definition-row"><dt>下一步</dt><dd>生产实验还需样本量/功效、置信区间、异质性和长期效应检查。</dd></div>
          </dl>
        </section>
        <section class="narrative-box warning">
          <h3>模拟结果声明</h3>
          <p>这里的 A/B 差异由预置概率和固定种子生成。它可以验证分析流程，但不能被写进简历为真实线上提升。</p>
        </section>
      </div>
    </div>
  `;
}

function defaultDecision(experiment) {
  const rollup = healthRollup(experiment);
  if (rollup.level === "healthy") {
    return {
      choice: experiment.status === "ended" ? "iterate" : "continue",
      note: `健康检查未触发演示风险。继续收集模拟样本，并观察主指标“${experiment.primaryMetric}”与护栏“${experiment.guardrails}”是否保持同向；不把当前描述性差异表述为线上因果结果。`,
    };
  }
  return {
    choice: "pause",
    note: `暂停结果解读，先处理 ${rollup.danger} 项阻断和 ${rollup.warning} 项关注。优先核对分流主键、实验触发、跨组污染、事件链以及策略版本；修复后重新开始一个可识别的新批次。`,
  };
}

function decisionKey(experiment) {
  return `flowlens-livelab:decision:${experiment.id}`;
}

function loadDecision(experiment) {
  const fallback = defaultDecision(experiment);
  try {
    const saved = JSON.parse(localStorage.getItem(decisionKey(experiment)) || "null");
    if (saved && ["continue", "pause", "iterate"].includes(saved.choice) && typeof saved.note === "string") {
      return saved;
    }
  } catch (_error) {
    // Corrupt local drafts fall back to the deterministic template.
  }
  return fallback;
}

function renderDecision(experiment) {
  const decision = loadDecision(experiment);
  const options = [
    ["continue", "继续收集", "健康检查通过，扩大模拟样本观察稳定性"],
    ["pause", "暂停排查", "实验质量不足，先修复再解释指标"],
    ["iterate", "迭代重开", "策略或口径需要调整，创建新版本批次"],
  ];
  return `
    <div class="section-stack">
      <section class="panel" aria-labelledby="decision-title">
        <div class="panel-heading"><div><h3 id="decision-title">实验决策卡</h3><p>记录决策、证据边界与下一步，而不是只保存一个结果数字</p></div><span class="badge badge-info">本地草稿</span></div>
        <form id="decision-form">
          <div class="decision-layout">
            <fieldset class="decision-options">
              <legend class="field-label">当前建议</legend>
              ${options
                .map(
                  ([value, label, help]) => `
                    <label class="decision-option">
                      <input type="radio" name="decision" value="${value}" ${decision.choice === value ? "checked" : ""} />
                      <span><strong>${label}</strong><small>${help}</small></span>
                    </label>`,
                )
                .join("")}
            </fieldset>
            <div>
              <label class="field-label" for="decision-note">判断依据与下一步</label>
              <textarea class="decision-textarea" id="decision-note" name="note" required>${escapeHtml(decision.note)}</textarea>
              <div class="form-actions">
                <button class="button button-primary" type="submit">${icon("save")}保存决策草稿</button>
                <button class="button button-secondary" type="button" id="reset-decision">${icon("reset")}恢复建议模板</button>
                <span class="save-state" id="save-state">保存在当前浏览器</span>
              </div>
            </div>
          </div>
        </form>
      </section>

      <section class="narrative-box">
        <h3>面试讲述提示</h3>
        <p>可以按“业务问题 → 唯一变量 → 事件合同 → 健康检查 → 指标与护栏 → 决策边界”讲述。明确说明这是个人项目的模拟实验台，FlowLens 的真实证据来自公开数据离线回放。</p>
      </section>
    </div>
  `;
}

function renderActiveView(experiment) {
  const renderers = {
    overview: renderOverview,
    strategy: renderStrategy,
    health: renderHealth,
    metrics: renderMetrics,
    decision: renderDecision,
  };
  els.viewRoot.style.animation = "none";
  void els.viewRoot.offsetWidth;
  els.viewRoot.innerHTML = renderers[state.activeView](experiment);
  els.viewRoot.style.animation = "view-enter 180ms ease-out both";
}

function renderInspector(experiment) {
  const rollup = healthRollup(experiment);
  els.healthSummary.textContent = `${rollup.healthy}/${rollup.checks.length}`;
  els.healthSummary.className = `health-summary ${levelBadge(rollup.level)}`;
  els.healthChecks.innerHTML = rollup.checks
    .map(
      (check) => `
        <button class="health-check health-check-button" type="button" data-level="${check.level}" data-check-id="${check.id}" aria-label="查看${check.name}详情：${levelLabel(check.level)}">
          <span class="check-icon">${icon(levelIcon(check.level))}</span>
          <div>
            <h3>${check.name} · ${levelLabel(check.level)}</h3>
            <p>${check.detail}</p>
            <span class="check-reading">${check.reading}</span>
            <span class="check-action">查看详情 ${icon("arrow")}</span>
          </div>
        </button>`,
    )
    .join("");
  if (rollup.level !== "healthy") {
    els.healthChecks.insertAdjacentHTML(
      "beforeend",
      `<button class="button button-secondary inspector-action" type="button" data-focus-first-issue>${icon("alert")}定位首个异常</button>`,
    );
  }
}

function renderAll() {
  const experiment = getExperiment();
  renderOfflineRun();
  renderExperimentList();
  renderContext(experiment);
  renderRunControls(experiment);
  renderTabs();
  renderActiveView(experiment);
  renderInspector(experiment);
}

function seededRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 4294967296;
  };
}

function simulateBatch(experiment) {
  const random = seededRandom(experiment.seed + experiment.batch * 977);
  const eligible = 900 + Math.floor(random() * 700);
  const noise = (random() - 0.5) * 0.012;
  const allocationA = Math.min(0.88, Math.max(0.12, experiment.allocation[0] + experiment.behavior.srmBias + noise));
  const assignedA = Math.round(eligible * allocationA);
  const assignedB = eligible - assignedA;
  const triggerA = 0.79 + random() * 0.08 - Math.abs(experiment.behavior.srmBias) * 1.4;
  const triggerB = 0.78 + random() * 0.09 - Math.abs(experiment.behavior.srmBias) * 1.4;
  const exposedA = Math.max(0, Math.round(assignedA * triggerA));
  const exposedB = Math.max(0, Math.round(assignedB * triggerB));
  const clickA = Math.round(exposedA * (0.083 + random() * 0.012));
  const clickB = Math.round(exposedB * (0.088 + random() * 0.014));
  const startedA = Math.round(clickA * (0.82 + random() * 0.07));
  const startedB = Math.round(clickB * (0.84 + random() * 0.07));
  const longA = Math.round(exposedA * (0.035 + random() * 0.007));
  const longB = Math.round(exposedB * (0.038 + random() * 0.008));
  const negativeA = Math.round(exposedA * (0.0054 + random() * 0.0014));
  const negativeB = Math.round(exposedB * (0.0049 + random() * 0.0015));
  const assigned = assignedA + assignedB;
  const started = startedA + startedB;
  const contamination = Math.round(assigned * experiment.behavior.contamRate * (0.8 + random() * 0.4));
  const violations = Math.round(started * experiment.behavior.violationRate * (0.8 + random() * 0.4));
  const versionMismatch = Math.round((exposedA + exposedB) * experiment.behavior.mismatchRate * (0.8 + random() * 0.4));

  const increments = {
    eligible,
    assignedA,
    assignedB,
    exposedA,
    exposedB,
    clickedA: clickA,
    clickedB: clickB,
    startedA,
    startedB,
    longA,
    longB,
    negativeA,
    negativeB,
    contamination,
    violations,
    versionMismatch,
  };

  Object.entries(increments).forEach(([key, value]) => {
    experiment.counts[key] += value;
  });
  experiment.batch += 1;
  experiment.stage = `模拟第 ${experiment.batch} 批次`;
  const rollup = healthRollup(experiment);
  const log =
    rollup.level === "healthy"
      ? `第 ${experiment.batch} 批：新增 ${formatInteger.format(eligible)} 名 eligible 用户，健康检查通过`
      : `第 ${experiment.batch} 批：新增 ${formatInteger.format(eligible)} 名 eligible 用户，仍有 ${rollup.danger} 项阻断`;
  experiment.recent.unshift(log);
  experiment.recent = experiment.recent.slice(0, 3);
  return { eligible, rollup };
}

function focusHealthCheck(checkId) {
  const experiment = getExperiment();
  const rollup = healthRollup(experiment);
  const resolvedId =
    checkId || rollup.checks.find((check) => check.level === "danger")?.id || rollup.checks.find((check) => check.level === "warning")?.id || rollup.checks[0]?.id;
  if (!resolvedId) return;
  state.activeView = "health";
  state.focusedCheckId = resolvedId;
  renderTabs();
  renderActiveView(experiment);
  window.requestAnimationFrame(() => {
    const detail = document.querySelector(`[data-check-detail="${resolvedId}"]`);
    detail?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    detail?.focus({ preventScroll: true });
  });
}

function updateSimulationPhase(phase) {
  state.simulationPhase = phase;
  els.simulateBatch.setAttribute("aria-busy", "true");
  els.simulateBatch.disabled = true;
  els.toggleRun.disabled = true;
  els.simulateBatch.innerHTML = `${icon("activity")}<span>${escapeHtml(phase)}</span>`;
}

document.addEventListener("click", (event) => {
  const experimentButton = event.target.closest("[data-experiment-id]");
  if (experimentButton) {
    state.activeExperimentId = experimentButton.dataset.experimentId;
    state.focusedCheckId = null;
    state.selectedMetricIndex = 2;
    renderAll();
    return;
  }

  const filterButton = event.target.closest("[data-filter]");
  if (filterButton) {
    state.filter = filterButton.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.filter === state.filter);
    });
    renderExperimentList();
    return;
  }

  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    state.activeView = viewButton.dataset.view;
    renderTabs();
    renderActiveView(getExperiment());
    els.viewRoot.focus({ preventScroll: true });
    return;
  }

  const healthCheckButton = event.target.closest("[data-check-id]");
  if (healthCheckButton) {
    focusHealthCheck(healthCheckButton.dataset.checkId);
    return;
  }

  if (event.target.closest("[data-focus-first-issue]")) {
    focusHealthCheck();
    return;
  }

  const metricButton = event.target.closest("[data-metric-index]");
  if (metricButton) {
    state.selectedMetricIndex = Number(metricButton.dataset.metricIndex);
    renderActiveView(getExperiment());
    window.requestAnimationFrame(() => document.querySelector(".metric-inspector")?.focus({ preventScroll: true }));
    return;
  }

  if (event.target.closest("[data-dismiss-receipt]")) {
    state.lastBatchReceipt = null;
    renderActiveView(getExperiment());
    return;
  }

  if (event.target.closest("#reset-decision")) {
    const experiment = getExperiment();
    localStorage.removeItem(decisionKey(experiment));
    renderActiveView(experiment);
    showToast("已恢复当前实验的建议模板");
  }
});

els.toggleRun.addEventListener("click", () => {
  const experiment = getExperiment();
  if (experiment.status === "ended") return;
  experiment.status = experiment.status === "paused" ? "running" : "paused";
  experiment.stage = experiment.status === "paused" ? `模拟第 ${experiment.batch} 批 · 已暂停` : `模拟第 ${experiment.batch} 批次`;
  experiment.recent.unshift(
    experiment.status === "paused"
      ? `第 ${experiment.batch} 批：手动暂停本地模拟，不影响任何外部系统`
      : `第 ${experiment.batch} 批：恢复本地模拟`,
  );
  experiment.recent = experiment.recent.slice(0, 3);
  renderAll();
  showToast(experiment.status === "paused" ? "本地模拟已暂停" : "本地模拟已恢复");
});

els.simulateBatch.addEventListener("click", () => {
  const experiment = getExperiment();
  if (experiment.status !== "running" || state.isSimulating) return;
  state.isSimulating = true;
  const assignedBefore = total(experiment, "assignedA", "assignedB");
  const exposedBefore = total(experiment, "exposedA", "exposedB");
  const triggerBefore = safeRate(exposedBefore, assignedBefore);
  updateSimulationPhase("生成资格与分流…");
  window.setTimeout(() => {
    updateSimulationPhase("回放曝光与播放…");
    window.setTimeout(() => {
      updateSimulationPhase("重新计算健康检查…");
      window.setTimeout(() => {
        const result = simulateBatch(experiment);
        const assignedAfter = total(experiment, "assignedA", "assignedB");
        const exposedAfter = total(experiment, "exposedA", "exposedB");
        state.lastBatchReceipt = {
          experimentId: experiment.id,
          batch: experiment.batch,
          eligibleAdded: result.eligible,
          triggerBefore,
          triggerAfter: safeRate(exposedAfter, assignedAfter),
          healthy: result.rollup.healthy,
          total: result.rollup.checks.length,
          level: result.rollup.level,
        };
        state.isSimulating = false;
        state.simulationPhase = "";
        renderAll();
        showToast(`第 ${experiment.batch} 批模拟事件已生成，诊断已重新计算`);
      }, 150);
    }, 150);
  }, 150);
});

document.addEventListener("input", (event) => {
  if (!event.target.closest("#decision-form")) return;
  const saveState = document.querySelector("#save-state");
  if (!saveState) return;
  saveState.textContent = "有未保存修改";
  saveState.classList.add("is-dirty");
  saveState.classList.remove("is-saved");
});

document.addEventListener("submit", (event) => {
  if (event.target.id !== "decision-form") return;
  event.preventDefault();
  const experiment = getExperiment();
  const formData = new FormData(event.target);
  const payload = {
    choice: formData.get("decision"),
    note: String(formData.get("note") || "").trim(),
    savedAt: new Date().toISOString(),
  };
  localStorage.setItem(decisionKey(experiment), JSON.stringify(payload));
  const saveState = document.querySelector("#save-state");
  if (saveState) {
    saveState.textContent = "刚刚保存到当前浏览器";
    saveState.classList.remove("is-dirty");
    saveState.classList.add("is-saved");
  }
  showToast("决策草稿已保存；它不会上传到任何服务");
});

renderAll();
