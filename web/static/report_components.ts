import { addAgentMessage } from "./chat_panel.js";
import { ui } from "./dom.js";
import {
  cashLabel,
  escapeHtml,
  formatCurrency,
  formatNumber,
  formatPercent,
} from "./format.js";
import type {
  AllocationRow,
  AllocationView,
  CashBalance,
  ChatState,
  Citation,
  EffectiveCashSummary,
  FinalReport,
  Money,
  PortfolioSnapshot,
  Recommendation,
} from "./types.js";

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

let currentReport: FinalReport | null = null;
let allocationView: AllocationView = "bars";

export function resetReportView(): void {
  currentReport = null;
  ui.traceOutput.textContent = "";
  ui.portfolioDashboardMeta.textContent = "";
  ui.portfolioMeta.textContent = "";
  ui.portfolioPositions.replaceChildren();
  ui.allocationChart.replaceChildren();
  ui.portfolioEvaluation.replaceChildren();
  ui.recommendationsList.replaceChildren();
  ui.missingDataList.replaceChildren();
  ui.sentimentList.replaceChildren();
  ui.citationList.replaceChildren();
}

export function setAllocationView(nextView: AllocationView): void {
  allocationView = nextView;
  renderCurrentAllocation();
}

export function renderState(state: ChatState): void {
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

export function renderTrace(state: ChatState, report: FinalReport): void {
  const analysis = report.portfolio_analysis ?? {};
  const trace = state.trace_summary ?? {
    run_id: state.run_id,
    route: {
      decision: state.validated_turn_decision?.route ?? state.turn_decision?.route ?? null,
      reasons:
        state.validated_turn_decision?.route_reasons ?? state.turn_decision?.route_reasons ?? [],
      coverage: state.evidence_coverage ?? {},
    },
    graph: { nodes: [], subagents: [] },
    llm: {
      total_calls: state.total_llm_calls ?? state.llm_calls?.length ?? 0,
      calls: state.llm_calls ?? [],
    },
    tools: {},
    warnings: [],
    errors: [],
    source_events: state.status_events,
  };
  ui.traceOutput.replaceChildren();
  appendTraceOverview(trace);
  appendTraceSection("Route and coverage", trace.route ?? {});
  appendTraceSection("Data context", trace.data_context ?? {});
  appendTraceSection("Graph nodes and subagents", trace.graph ?? {});
  appendTraceSection("Model calls", trace.llm ?? {});
  appendToolGroups(trace.tools ?? {});
  appendTraceSection("Warnings and errors", {
    warnings: trace.warnings ?? [],
    errors: trace.errors ?? [],
  });
  appendTraceSection("Guardrails", trace.guardrails ?? state.guardrail_result ?? {});
  appendTraceSection("Full sanitized source events", trace.source_events ?? state.status_events);
  appendTraceSection("Report provenance", {
    effective_cash: analysis.effective_cash ?? null,
    portfolio_storage: analysis.storage_result ?? null,
    history_context: analysis.history_context ?? null,
    assumptions: report.assumptions ?? [],
    missing_data: report.missing_data ?? [],
  });
}

function appendTraceOverview(trace: NonNullable<ChatState["trace_summary"]>): void {
  const overview = document.createElement("dl");
  overview.className = "trace-overview";
  const route = String(trace.route?.decision ?? "not available").replaceAll("_", " ");
  const totalCalls = String(trace.llm?.total_calls ?? 0);
  appendDefinition(overview, "Run", trace.run_id);
  appendDefinition(overview, "Route", route);
  appendDefinition(overview, "Model calls", totalCalls);
  ui.traceOutput.appendChild(overview);
}

function appendDefinition(list: HTMLDListElement, label: string, value: string): void {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  list.append(term, detail);
}

function appendTraceSection(label: string, value: unknown): void {
  const details = document.createElement("details");
  details.className = "trace-section";
  const summary = document.createElement("summary");
  summary.textContent = label;
  const body = document.createElement("pre");
  body.textContent = JSON.stringify(value, null, 2);
  details.append(summary, body);
  ui.traceOutput.appendChild(details);
}

function appendToolGroups(
  tools: NonNullable<NonNullable<ChatState["trace_summary"]>["tools"]>,
): void {
  const section = document.createElement("section");
  section.className = "trace-tool-groups";
  const heading = document.createElement("h3");
  heading.textContent = "Portfolio tool activity";
  section.appendChild(heading);
  for (const [label, group] of Object.entries(tools)) {
    const details = document.createElement("details");
    details.className = "trace-section";
    const summary = document.createElement("summary");
    summary.textContent = `${group.count} ${label}`;
    const body = document.createElement("pre");
    body.textContent = JSON.stringify(group.items, null, 2);
    details.append(summary, body);
    section.appendChild(details);
  }
  ui.traceOutput.appendChild(section);
}

function addReasoningSummary(state: ChatState, report: FinalReport): void {
  if (state.agent_type === "deterministic_portfolio_data_lane") return;
  const analysis = report.portfolio_analysis ?? {};
  const plan = state.query_plan;
  const parts: string[] = [];
  const route = state.validated_turn_decision?.route ?? state.turn_decision?.route;
  if (route === "direct_context") {
    parts.push("Answered from saved portfolio data; no Portfolio Agent lookup was needed.");
  } else if (route?.startsWith("delegate_")) {
    const reasons = state.validated_turn_decision?.route_reasons ?? [];
    const reasonText = reasons.map((reason) => reason.replaceAll("_", " ")).join(" and ");
    parts.push(
      `Requested bounded supporting detail${reasonText ? ` for ${reasonText}` : ""}.`,
    );
  } else if (plan?.route_reason) {
    parts.push(plan.route_reason.replaceAll("_", " "));
  } else {
    parts.push(`Completed ${state.agent_type} run in ${state.mode || report.mode} mode.`);
  }

  if (plan?.needs_sentiment_agent) {
    const sentimentStatus = state.sentiment_packet?.retrieval_status;
    parts.push(`Sentiment evidence requested${sentimentStatus ? ` (${sentimentStatus.replaceAll("_", " ")})` : ""}.`);
  }

  parts.push(`${state.total_llm_calls ?? state.llm_calls?.length ?? 0} model call(s) recorded.`);

  const history = analysis.history_context as
    | { history_status?: { snapshot_count?: number } }
    | undefined;
  const snapshotCount = history?.history_status?.snapshot_count;
  if (typeof snapshotCount === "number" && Number.isFinite(snapshotCount)) {
    parts.push(`SQL history snapshots reviewed: ${snapshotCount}.`);
  }

  if (state.guardrail_result) {
    parts.push(`Guardrails ${state.guardrail_result.passed ? "passed" : "blocked"}.`);
  }

  addAgentMessage(`Run summary: ${parts.join(" ")}`, "reasoning");
}

export function isPortfolioSnapshot(value: unknown): value is PortfolioSnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Partial<PortfolioSnapshot>;
  return (
    typeof snapshot.as_of === "string" &&
    typeof snapshot.base_currency === "string" &&
    isMoney(snapshot.total_value) &&
    Array.isArray(snapshot.cash) &&
    Array.isArray(snapshot.holdings)
  );
}

function isMoney(value: unknown): value is Money {
  if (!value || typeof value !== "object") return false;
  const money = value as Partial<Money>;
  return typeof money.amount === "number" && typeof money.currency === "string";
}

function renderPortfolioSnapshot(report: FinalReport): void {
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

  const effectiveCash = report.portfolio_analysis?.effective_cash as
    | EffectiveCashSummary
    | undefined;
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
    ...snapshot.cash.map((cash: CashBalance) => ({
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

function renderAllocation(report: FinalReport): void {
  currentReport = report;
  renderCurrentAllocation();
}

export function renderCurrentAllocation(): void {
  ui.allocationViewButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.allocationView === allocationView);
  });
  if (!currentReport) return;

  const allocation = currentReport.portfolio_analysis?.allocation as
    | Record<string, unknown[]>
    | undefined;
  const rows = sortAllocationRows(
    ((allocation?.by_asset ?? []) as AllocationRow[]).filter((row) =>
      Number.isFinite(row.weight),
    ),
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

function renderAllocationBars(rows: AllocationRow[]): void {
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

function renderAllocationPie(rows: AllocationRow[]): void {
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
    path.querySelector("title")!.textContent = `${row.name}: ${formatPercent(row.weight)}`;
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

function sortAllocationRows(rows: AllocationRow[]): AllocationRow[] {
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

function pieSlicePath(
  centerX: number,
  centerY: number,
  radius: number,
  startAngle: number,
  endAngle: number,
): string {
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

function polarToCartesian(
  centerX: number,
  centerY: number,
  radius: number,
  angleInDegrees: number,
): { x: number; y: number } {
  const angleInRadians = (angleInDegrees * Math.PI) / 180;
  return {
    x: centerX + radius * Math.cos(angleInRadians),
    y: centerY + radius * Math.sin(angleInRadians),
  };
}

function renderPortfolioEvaluation(report: FinalReport): void {
  const evaluation = report.portfolio_analysis?.evaluation as
    | {
        strengths?: string[];
        risks?: string[];
        ips_mismatches?: string[];
        history_observations?: string[];
        open_questions?: string[];
        llm_model?: string;
      }
    | undefined;
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
  ] as const;
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

function renderRecommendations(items: Recommendation[]): void {
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

function renderMissingData(items: string[]): void {
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

function renderSentiment(sentiment: Record<string, unknown>): void {
  const holdings = (sentiment?.holdings ?? []) as Array<{
    ticker: string;
    stance: string;
    thesis_summary: string;
  }>;
  const portfolioLevel = sentiment?.portfolio_level_sentiment as
    | { summary?: string }
    | undefined;
  const retrievalStatus = sentiment?.retrieval_status as string | undefined;
  const warnings = (sentiment?.warnings ?? []) as string[];
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

function renderCitations(citations: Citation[]): void {
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
