import { addAgentMessage } from "./chat_panel.js";
import { ui } from "./dom.js";
import {
  cashLabel,
  escapeHtml,
  formatCurrency,
  formatNumber,
  formatPercent,
} from "./format.js";

const PIE_COLORS = [
  "#2563eb",
  "#0f766e",
  "#f59e0b",
  "#dc2626",
  "#7c3aed",
  "#16a34a",
  "#0891b2",
  "#db2777",
  "#4b5563",
  "#ca8a04",
  "#9333ea",
  "#15803d",
];

let currentReport = null;
let allocationView = "bars";

export function resetReportView() {
  currentReport = null;
  ui.traceOutput.textContent = "";
  ui.portfolioMeta.textContent = "";
  ui.portfolioPositions.replaceChildren();
  ui.allocationChart.replaceChildren();
  ui.portfolioEvaluation.replaceChildren();
  ui.recommendationsList.replaceChildren();
  ui.missingDataList.replaceChildren();
  ui.sentimentList.replaceChildren();
  ui.citationList.replaceChildren();
}

export function setAllocationView(nextView) {
  allocationView = nextView;
  renderCurrentAllocation();
}

export function renderState(state) {
  const report = state.final_report;
  if (!report) return;

  ui.reportTitle.textContent = report.title;
  ui.reportMode.textContent = state.mode || report.mode;
  ui.reportSummary.textContent = report.summary || "No summary returned.";
  const guardrailsPassed = state.guardrail_result?.passed ?? false;
  ui.guardrailBadge.textContent = guardrailsPassed ? "Guardrails Passed" : "Guardrails Blocked";
  ui.guardrailBadge.className = guardrailsPassed ? "badge good" : "badge bad";
  renderPortfolioSnapshot(report);
  renderAllocation(report);
  renderPortfolioEvaluation(report);
  renderRecommendations(report.recommendations ?? []);
  renderMissingData(report.missing_data ?? []);
  renderSentiment(report.sentiment_analysis ?? {});
  renderCitations(report.citations ?? []);
  addReasoningSummary(state, report);
  renderTrace(state, report);
}

function renderTrace(state, report) {
  const analysis = report.portfolio_analysis ?? {};
  ui.traceOutput.textContent = JSON.stringify(
    {
      run_id: state.run_id,
      agent_type: state.agent_type,
      mode: state.mode,
      status_events: state.status_events,
      query_plan: state.query_plan ?? null,
      portfolio_packet: state.portfolio_packet ?? null,
      sentiment_packet: state.sentiment_packet ?? report.sentiment_analysis ?? null,
      synthesis: state.synthesis ?? null,
      guardrail_result: state.guardrail_result,
      final_report: {
        title: report.title,
        mode: report.mode,
        summary: report.summary,
        assumptions: report.assumptions ?? [],
        missing_data: report.missing_data ?? [],
        recommendations: report.recommendations ?? [],
      },
      effective_cash: analysis.effective_cash ?? null,
      portfolio_storage: analysis.storage_result ?? null,
      history_context: analysis.history_context ?? null,
      tool_calls: analysis.tool_calls ?? [],
    },
    null,
    2,
  );
}

function addReasoningSummary(state, report) {
  const analysis = report.portfolio_analysis ?? {};
  const plan = state.query_plan;
  const parts = [];
  if (plan?.route_reason) {
    parts.push(plan.route_reason);
  } else {
    parts.push(`Completed ${state.agent_type} run in ${state.mode || report.mode} mode.`);
  }

  if (plan) {
    parts.push(`Portfolio Agent ${plan.needs_portfolio_agent ? "called" : "not needed"}.`);
    const sentimentStatus = state.sentiment_packet?.retrieval_status;
    parts.push(
      plan.needs_sentiment_agent
        ? `Sentiment Agent requested${sentimentStatus ? ` (${sentimentStatus})` : ""}.`
        : "Sentiment Agent not needed.",
    );
  }

  const evaluation = analysis.evaluation;
  if (evaluation?.summary) {
    parts.push(`Portfolio evaluator: ${evaluation.summary}`);
  }

  const history = analysis.history_context;
  const snapshotCount = history?.history_status?.snapshot_count;
  if (typeof snapshotCount === "number" && Number.isFinite(snapshotCount)) {
    parts.push(`SQL history snapshots reviewed: ${snapshotCount}.`);
  }

  const guardrailChecks = state.guardrail_result?.checks ?? [];
  if (guardrailChecks.length > 0) {
    const guardrailSummary = guardrailChecks
      .map((check) => `${check.check} ${check.passed ? "passed" : "failed"}`)
      .join(", ");
    parts.push(`Guardrails: ${guardrailSummary}.`);
  } else if (state.guardrail_result) {
    parts.push(`Guardrails ${state.guardrail_result.passed ? "passed" : "blocked"}.`);
  }

  if (report.assumptions?.length) {
    parts.push(`Assumptions: ${report.assumptions.slice(0, 2).join(" ")}`);
  }

  addAgentMessage(`Reasoning summary: ${parts.join(" ")}`, "reasoning");
}

export function isPortfolioSnapshot(value) {
  if (!value || typeof value !== "object") return false;
  const snapshot = value;
  return (
    typeof snapshot.as_of === "string" &&
    typeof snapshot.base_currency === "string" &&
    isMoney(snapshot.total_value) &&
    Array.isArray(snapshot.cash) &&
    Array.isArray(snapshot.holdings)
  );
}

function isMoney(value) {
  if (!value || typeof value !== "object") return false;
  const money = value;
  return typeof money.amount === "number" && typeof money.currency === "string";
}

function renderPortfolioSnapshot(report) {
  const snapshot = report.portfolio_snapshot;
  ui.portfolioPositions.replaceChildren();
  if (!isPortfolioSnapshot(snapshot)) {
    ui.portfolioMeta.textContent = "";
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No portfolio snapshot returned for this run.";
    ui.portfolioPositions.appendChild(item);
    return;
  }

  const effectiveCash = report.portfolio_analysis?.effective_cash;
  const meta = [
    formatCurrency(snapshot.total_value.amount, snapshot.total_value.currency),
    `${snapshot.holdings.length} holdings`,
    `${snapshot.cash.length} cash lines`,
  ];
  if (effectiveCash) {
    meta.push(
      `Effective cash ${formatCurrency(
        effectiveCash.effective_cash_value,
        effectiveCash.currency,
      )} (${formatPercent(effectiveCash.effective_cash_weight)})`,
    );
  }
  ui.portfolioMeta.textContent = meta.join(" | ");

  const rows = [
    ...snapshot.cash.map((cash) => ({
      label: cashLabel(cash),
      detail: cash.account_id,
      assetType: "cash",
      quantity: null,
      price: null,
      value: cash.amount,
      weight: cash.weight,
      currency: cash.currency,
      pnl: null,
    })),
    ...snapshot.holdings.map((holding) => ({
      label: holding.ticker,
      detail: holding.name,
      assetType: holding.asset_type,
      quantity: holding.quantity,
      price: holding.market_price,
      value: holding.market_value,
      weight: holding.portfolio_weight,
      currency: holding.currency,
      pnl: holding.unrealized_pnl ?? null,
    })),
  ].sort((left, right) => Math.abs(right.weight) - Math.abs(left.weight));

  const table = document.createElement("div");
  table.className = "position-grid";
  ["Asset", "Type", "Qty", "Price", "Value", "Weight", "Unrealized"].forEach((heading) => {
    const cell = document.createElement("div");
    cell.className = "position-heading";
    cell.textContent = heading;
    table.appendChild(cell);
  });

  rows.forEach((row) => {
    const asset = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = row.label;
    const detail = document.createElement("span");
    detail.className = "muted";
    detail.textContent = row.detail;
    asset.append(name, detail);

    const type = document.createElement("div");
    type.textContent = row.assetType;

    const quantity = document.createElement("div");
    quantity.textContent = row.quantity === null ? "-" : formatNumber(row.quantity);

    const price = document.createElement("div");
    price.textContent = row.price === null ? "-" : formatCurrency(row.price, row.currency);

    const value = document.createElement("div");
    value.textContent = formatCurrency(row.value, row.currency);

    const weight = document.createElement("div");
    weight.textContent = formatPercent(row.weight);

    const pnl = document.createElement("div");
    pnl.textContent = row.pnl === null ? "-" : formatCurrency(row.pnl, row.currency);
    pnl.className = row.pnl === null ? "" : row.pnl >= 0 ? "positive" : "negative";

    table.append(asset, type, quantity, price, value, weight, pnl);
  });

  ui.portfolioPositions.appendChild(table);
}

function renderAllocation(report) {
  currentReport = report;
  renderCurrentAllocation();
}

export function renderCurrentAllocation() {
  ui.allocationViewButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.allocationView === allocationView);
  });
  if (!currentReport) return;

  const allocation = currentReport.portfolio_analysis?.allocation;
  const rows = sortAllocationRows(
    (allocation?.by_asset ?? []).filter((row) => Number.isFinite(row.weight)),
  );

  ui.allocationChart.replaceChildren();
  if (rows.length === 0) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No allocation rows returned for this run.";
    ui.allocationChart.appendChild(item);
    return;
  }

  if (allocationView === "pie") {
    renderAllocationPie(rows);
    return;
  }
  renderAllocationBars(rows);
}

function renderAllocationBars(rows) {
  const stack = document.createElement("div");
  stack.className = "bar-stack";
  rows.forEach((row) => {
    const container = document.createElement("div");
    container.className = "bar-row";
    const name = document.createElement("span");
    name.textContent = row.name;
    name.title = row.name;
    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${Math.max(0, Math.min(Math.abs(row.weight) * 100, 100))}%`;
    track.appendChild(fill);
    const value = document.createElement("span");
    value.textContent = `${(row.weight * 100).toFixed(1)}%`;
    container.append(name, track, value);
    stack.appendChild(container);
  });
  ui.allocationChart.appendChild(stack);
}

function renderAllocationPie(rows) {
  const positiveRows = rows.filter((row) => row.weight > 0);
  const totalWeight = positiveRows.reduce((total, row) => total + row.weight, 0);
  if (totalWeight <= 0) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No positive allocation weights available for a pie view.";
    ui.allocationChart.appendChild(item);
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "pie-layout";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 120 120");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Portfolio allocation pie chart");

  let startAngle = -90;
  positiveRows.forEach((row, index) => {
    const span = (row.weight / totalWeight) * 360;
    const endAngle = startAngle + span;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pieSlicePath(60, 60, 52, startAngle, endAngle));
    path.setAttribute("fill", PIE_COLORS[index % PIE_COLORS.length]);
    path.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "title"));
    path.querySelector("title").textContent = `${row.name}: ${formatPercent(row.weight)}`;
    svg.appendChild(path);
    startAngle = endAngle;
  });

  const legend = document.createElement("div");
  legend.className = "pie-legend";
  positiveRows.forEach((row, index) => {
    const item = document.createElement("div");
    item.className = "pie-legend-item";
    const swatch = document.createElement("span");
    swatch.style.background = PIE_COLORS[index % PIE_COLORS.length];
    const label = document.createElement("span");
    label.textContent = `${row.name} | ${formatPercent(row.weight)}`;
    item.append(swatch, label);
    legend.appendChild(item);
  });

  wrapper.append(svg, legend);
  ui.allocationChart.appendChild(wrapper);
}

function sortAllocationRows(rows) {
  const sorted = [...rows];
  const sortMode = ui.allocationSort.value;
  if (sortMode === "weight_asc") {
    return sorted.sort((left, right) => Math.abs(left.weight) - Math.abs(right.weight));
  }
  if (sortMode === "name_asc") {
    return sorted.sort((left, right) => left.name.localeCompare(right.name));
  }
  if (sortMode === "value_desc") {
    return sorted.sort((left, right) => Math.abs(right.value) - Math.abs(left.value));
  }
  return sorted.sort((left, right) => Math.abs(right.weight) - Math.abs(left.weight));
}

function pieSlicePath(centerX, centerY, radius, startAngle, endAngle) {
  const start = polarToCartesian(centerX, centerY, radius, endAngle);
  const end = polarToCartesian(centerX, centerY, radius, startAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
  return [
    `M ${centerX} ${centerY}`,
    `L ${start.x} ${start.y}`,
    `A ${radius} ${radius} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`,
    "Z",
  ].join(" ");
}

function polarToCartesian(centerX, centerY, radius, angleInDegrees) {
  const angleInRadians = (angleInDegrees * Math.PI) / 180;
  return {
    x: centerX + radius * Math.cos(angleInRadians),
    y: centerY + radius * Math.sin(angleInRadians),
  };
}

function renderPortfolioEvaluation(report) {
  const evaluation = report.portfolio_analysis?.evaluation;
  ui.portfolioEvaluation.replaceChildren();
  if (!evaluation) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No portfolio-only evaluator output for this run.";
    ui.portfolioEvaluation.appendChild(item);
    return;
  }
  const groups = [
    ["Strengths", evaluation.strengths ?? []],
    ["Risks", evaluation.risks ?? []],
    ["IPS Mismatches", evaluation.ips_mismatches ?? []],
    ["History", evaluation.history_observations ?? []],
    ["Open Questions", evaluation.open_questions ?? []],
  ];
  groups.forEach(([title, items]) => {
    const section = document.createElement("section");
    section.className = "evaluation-section";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const list = document.createElement("ul");
    list.className = "plain-list";
    if (items.length === 0) {
      const li = document.createElement("li");
      li.textContent = "None noted.";
      list.appendChild(li);
    } else {
      items.slice(0, 6).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        list.appendChild(li);
      });
    }
    section.append(heading, list);
    ui.portfolioEvaluation.appendChild(section);
  });
  if (evaluation.llm_model) {
    const model = document.createElement("p");
    model.className = "muted";
    model.textContent = `Evaluator model: ${evaluation.llm_model}`;
    ui.portfolioEvaluation.appendChild(model);
  }
}

function renderRecommendations(items) {
  ui.recommendationsList.replaceChildren();
  if (items.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No recommendations returned for this run.";
    ui.recommendationsList.appendChild(li);
    return;
  }
  items.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${escapeHtml(item.title)}</strong><br>${escapeHtml(item.rationale)}`;
    ui.recommendationsList.appendChild(li);
  });
}

function renderMissingData(items) {
  ui.missingDataList.replaceChildren();
  if (items.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No missing data reported.";
    ui.missingDataList.appendChild(li);
    return;
  }
  items.slice(0, 14).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    ui.missingDataList.appendChild(li);
  });
}

function renderSentiment(sentiment) {
  const holdings = sentiment?.holdings ?? [];
  const portfolioLevel = sentiment?.portfolio_level_sentiment;
  const retrievalStatus = sentiment?.retrieval_status;
  const warnings = sentiment?.warnings ?? [];
  ui.sentimentList.replaceChildren();
  if (portfolioLevel?.summary) {
    const summary = document.createElement("p");
    summary.className = "muted";
    summary.textContent = portfolioLevel.summary;
    ui.sentimentList.appendChild(summary);
  }
  holdings.forEach((holding) => {
    const card = document.createElement("article");
    card.className = "holding-card";
    card.innerHTML = `<strong>${escapeHtml(holding.ticker)} | ${escapeHtml(holding.stance)}</strong><br>${escapeHtml(holding.thesis_summary)}`;
    ui.sentimentList.appendChild(card);
  });
  if (holdings.length === 0) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = retrievalStatus
      ? `Sentiment retrieval: ${retrievalStatus}.`
      : "No sentiment rows returned for this run.";
    ui.sentimentList.appendChild(item);
  }
  warnings.slice(0, 4).forEach((warning) => {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = warning;
    ui.sentimentList.appendChild(item);
  });
}

function renderCitations(citations) {
  ui.citationList.replaceChildren();
  if (citations.length === 0) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No citations returned for this run.";
    ui.citationList.appendChild(item);
    return;
  }
  citations.forEach((citation) => {
    const details = document.createElement("details");
    details.className = "citation-card";
    const rank = citation.location?.source_quality_rank ?? "n/a";
    details.innerHTML = `<summary>${escapeHtml(citation.title)} | ${escapeHtml(citation.source_quality)} | rank ${rank}</summary><p>${escapeHtml(citation.snippet)}</p><p class="muted">${escapeHtml(citation.document_id)}</p>`;
    ui.citationList.appendChild(details);
  });
}
