type StatusEvent = {
  status: string;
  message: string;
  timestamp: string;
};

type Citation = {
  citation_id: string;
  title: string;
  document_id: string;
  snippet: string;
  source_quality: string;
  location: Record<string, unknown>;
};

type Recommendation = {
  title: string;
  rationale: string;
};

type Money = {
  amount: number;
  currency: string;
};

type CashBalance = {
  account_id: string;
  amount: number;
  currency: string;
  weight: number;
};

type Holding = {
  ticker: string;
  name: string;
  asset_type: string;
  currency: string;
  quantity: number;
  market_price: number;
  market_value: number;
  portfolio_weight: number;
  unrealized_pnl?: number | null;
};

type PortfolioSnapshot = {
  as_of: string;
  base_currency: string;
  total_value: Money;
  cash: CashBalance[];
  holdings: Holding[];
};

type AllocationRow = {
  name: string;
  value: number;
  weight: number;
  currency: string;
};

type EffectiveCashSummary = {
  currency: string;
  cash_value: number;
  auto_invested_fund_assets_value: number;
  cash_equivalent_value: number;
  effective_cash_value: number;
  effective_cash_weight: number;
};

type FinalReport = {
  title: string;
  mode: string;
  as_of?: string;
  summary: string;
  portfolio_snapshot?: PortfolioSnapshot;
  portfolio_analysis: Record<string, unknown>;
  sentiment_analysis: Record<string, unknown>;
  recommendations: Recommendation[];
  missing_data: string[];
  citations: Citation[];
};

type ChatState = {
  agent_type: string;
  run_id: string;
  mode: string;
  final_report: FinalReport;
  guardrail_result: { passed: boolean };
  status_events: StatusEvent[];
};

type StreamError = {
  error_type: string;
  message: string;
  timestamp?: string;
  traceback?: string[];
};

const appShell = document.querySelector<HTMLElement>("#appShell")!;
const form = document.querySelector<HTMLFormElement>("#chatForm")!;
const agentSelect = document.querySelector<HTMLSelectElement>("#agentSelect")!;
const input = document.querySelector<HTMLTextAreaElement>("#queryInput")!;
const sendButton = document.querySelector<HTMLButtonElement>("#sendButton")!;
const hideChatButton = document.querySelector<HTMLButtonElement>("#hideChatButton")!;
const showChatButton = document.querySelector<HTMLButtonElement>("#showChatButton")!;
const chatColumn = document.querySelector<HTMLElement>(".chat-column")!;
const chatLog = document.querySelector<HTMLDivElement>("#chatLog")!;
const chatResizeHandle = document.querySelector<HTMLDivElement>("#chatResizeHandle")!;
const statusList = document.querySelector<HTMLOListElement>("#statusList")!;
const guardrailBadge = document.querySelector<HTMLSpanElement>("#guardrailBadge")!;
const reportTitle = document.querySelector<HTMLHeadingElement>("#reportTitle")!;
const reportMode = document.querySelector<HTMLSpanElement>("#reportMode")!;
const reportSummary = document.querySelector<HTMLParagraphElement>("#reportSummary")!;
const portfolioMeta = document.querySelector<HTMLSpanElement>("#portfolioMeta")!;
const portfolioPositions = document.querySelector<HTMLDivElement>("#portfolioPositions")!;
const allocationSort = document.querySelector<HTMLSelectElement>("#allocationSort")!;
const allocationChart = document.querySelector<HTMLDivElement>("#allocationChart")!;
const allocationViewButtons = Array.from(
  document.querySelectorAll<HTMLButtonElement>("[data-allocation-view]"),
);
const portfolioEvaluation = document.querySelector<HTMLDivElement>("#portfolioEvaluation")!;
const recommendationsList = document.querySelector<HTMLUListElement>("#recommendationsList")!;
const missingDataList = document.querySelector<HTMLUListElement>("#missingDataList")!;
const sentimentList = document.querySelector<HTMLDivElement>("#sentimentList")!;
const citationList = document.querySelector<HTMLDivElement>("#citationList")!;
const traceOutput = document.querySelector<HTMLPreElement>("#traceOutput")!;

const CHAT_WIDTH_KEY = "finance_ai_chat_width";
const CHAT_HIDDEN_KEY = "finance_ai_chat_hidden";
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
let allocationView: "bars" | "pie" = "bars";

restoreChatLayout();

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = input.value.trim();
  if (!query) return;
  clearRun();
  addUserMessage(query);
  void runChat(query, agentSelect.value);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

hideChatButton.addEventListener("click", () => setChatHidden(true));
showChatButton.addEventListener("click", () => setChatHidden(false));
allocationSort.addEventListener("change", renderCurrentAllocation);
allocationViewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const nextView = button.dataset.allocationView;
    if (nextView !== "bars" && nextView !== "pie") return;
    allocationView = nextView;
    renderCurrentAllocation();
  });
});

chatResizeHandle.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  chatResizeHandle.setPointerCapture(event.pointerId);
  resizeChatTo(event.clientX);
});

chatResizeHandle.addEventListener("pointermove", (event) => {
  if (!chatResizeHandle.hasPointerCapture(event.pointerId)) return;
  resizeChatTo(event.clientX);
});

chatResizeHandle.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  const currentWidth = chatColumn.getBoundingClientRect().width;
  const delta = event.key === "ArrowLeft" ? -24 : 24;
  setChatWidth(currentWidth + delta);
});

async function runChat(query: string, agent: string): Promise<void> {
  setRunning(true);
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, agent }),
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`HTTP ${response.status}: ${body || response.statusText}`);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error("Response stream unavailable");
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!handleStreamLine(line)) {
          await reader.cancel();
          return;
        }
      }
    }
    if (buffer.trim()) handleStreamLine(buffer);
  } catch (error) {
    renderStreamError(errorPayloadFromCaughtError(error));
  } finally {
    setRunning(false);
  }
}

function handleStreamLine(line: string): boolean {
  if (!line.trim()) return true;
  const payload = JSON.parse(line);
  if (payload.type === "status") {
    addStatus(payload.event);
  }
  if (payload.type === "final") {
    renderState(payload.state);
  }
  if (payload.type === "error") {
    renderStreamError(payload.error);
    return false;
  }
  return true;
}

function clearRun(): void {
  currentReport = null;
  statusList.replaceChildren();
  traceOutput.textContent = "";
  portfolioMeta.textContent = "";
  portfolioPositions.replaceChildren();
  allocationChart.replaceChildren();
  portfolioEvaluation.replaceChildren();
  guardrailBadge.textContent = "Running";
  guardrailBadge.className = "badge";
}

function setRunning(running: boolean): void {
  sendButton.disabled = running;
}

function addUserMessage(query: string): void {
  const item = document.createElement("li");
  item.className = "user-message";
  item.textContent = query;
  statusList.appendChild(item);
  scrollChatToBottom();
}

function addStatus(event: StatusEvent, variant: "normal" | "error" = "normal"): void {
  const item = document.createElement("li");
  item.className = variant === "error" ? "agent-message error" : "agent-message";
  item.textContent = `${event.status}: ${event.message}`;
  statusList.appendChild(item);
  scrollChatToBottom();
}

function renderStreamError(error: StreamError): void {
  const message = error.message || "The backend stream failed before returning a report.";
  addStatus(
    {
      status: "failed",
      message,
      timestamp: error.timestamp ?? new Date().toISOString(),
    },
    "error",
  );
  reportTitle.textContent = "Run failed";
  reportMode.textContent = "error";
  reportSummary.textContent = message;
  guardrailBadge.textContent = "Failed";
  guardrailBadge.className = "badge bad";
  traceOutput.textContent = JSON.stringify(
    {
      status: "failed",
      error_type: error.error_type || "Error",
      message,
      timestamp: error.timestamp ?? new Date().toISOString(),
      traceback: error.traceback ?? [],
    },
    null,
    2,
  );
}

function errorPayloadFromCaughtError(error: unknown): StreamError {
  if (error instanceof Error) {
    return {
      error_type: error.name || "Error",
      message: error.message,
      timestamp: new Date().toISOString(),
      traceback: error.stack ? error.stack.split("\n") : [],
    };
  }
  return {
    error_type: "Error",
    message: String(error),
    timestamp: new Date().toISOString(),
    traceback: [],
  };
}

function renderState(state: ChatState): void {
  const report = state.final_report;
  reportTitle.textContent = report.title;
  reportMode.textContent = state.mode;
  reportSummary.textContent = report.summary;
  guardrailBadge.textContent = state.guardrail_result?.passed ? "Guardrails Passed" : "Guardrails Blocked";
  guardrailBadge.className = state.guardrail_result?.passed ? "badge good" : "badge bad";
  renderPortfolioSnapshot(report);
  renderAllocation(report);
  renderPortfolioEvaluation(report);
  renderRecommendations(report.recommendations);
  renderMissingData(report.missing_data);
  renderSentiment(report.sentiment_analysis);
  renderCitations(report.citations);
  traceOutput.textContent = JSON.stringify(
    {
      run_id: state.run_id,
      agent_type: state.agent_type,
      status_events: state.status_events,
      guardrail_result: state.guardrail_result,
      effective_cash: report.portfolio_analysis?.effective_cash ?? null,
      portfolio_storage: report.portfolio_analysis?.storage_result ?? null,
      history_context: report.portfolio_analysis?.history_context ?? null,
      tool_calls: report.portfolio_analysis?.tool_calls ?? [],
    },
    null,
    2,
  );
}

function renderPortfolioSnapshot(report: FinalReport): void {
  const snapshot = report.portfolio_snapshot;
  portfolioPositions.replaceChildren();
  if (!snapshot) {
    portfolioMeta.textContent = "";
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No portfolio snapshot returned for this run.";
    portfolioPositions.appendChild(item);
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
  portfolioMeta.textContent = meta.join(" | ");

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

  portfolioPositions.appendChild(table);
}

function renderAllocation(report: FinalReport): void {
  currentReport = report;
  renderCurrentAllocation();
}

function renderCurrentAllocation(): void {
  allocationViewButtons.forEach((button) => {
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

  allocationChart.replaceChildren();
  if (rows.length === 0) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No allocation rows returned for this run.";
    allocationChart.appendChild(item);
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
  allocationChart.appendChild(stack);
}

function renderAllocationPie(rows: AllocationRow[]): void {
  const positiveRows = rows.filter((row) => row.weight > 0);
  const totalWeight = positiveRows.reduce((total, row) => total + row.weight, 0);
  if (totalWeight <= 0) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No positive allocation weights available for a pie view.";
    allocationChart.appendChild(item);
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
  allocationChart.appendChild(wrapper);
}

function sortAllocationRows(rows: AllocationRow[]): AllocationRow[] {
  const sorted = [...rows];
  const sortMode = allocationSort.value;
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
  portfolioEvaluation.replaceChildren();
  if (!evaluation) {
    const item = document.createElement("p");
    item.className = "muted";
    item.textContent = "No portfolio-only evaluator output for this run.";
    portfolioEvaluation.appendChild(item);
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
    portfolioEvaluation.appendChild(section);
  });
  if (evaluation.llm_model) {
    const model = document.createElement("p");
    model.className = "muted";
    model.textContent = `Evaluator model: ${evaluation.llm_model}`;
    portfolioEvaluation.appendChild(model);
  }
}

function renderRecommendations(items: Recommendation[]): void {
  recommendationsList.replaceChildren();
  items.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${escapeHtml(item.title)}</strong><br>${escapeHtml(item.rationale)}`;
    recommendationsList.appendChild(li);
  });
}

function renderMissingData(items: string[]): void {
  missingDataList.replaceChildren();
  items.slice(0, 14).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    missingDataList.appendChild(li);
  });
}

function renderSentiment(sentiment: Record<string, unknown>): void {
  const holdings = (sentiment?.holdings ?? []) as Array<{
    ticker: string;
    stance: string;
    thesis_summary: string;
  }>;
  sentimentList.replaceChildren();
  holdings.forEach((holding) => {
    const card = document.createElement("article");
    card.className = "holding-card";
    card.innerHTML = `<strong>${escapeHtml(holding.ticker)} | ${escapeHtml(holding.stance)}</strong><br>${escapeHtml(holding.thesis_summary)}`;
    sentimentList.appendChild(card);
  });
}

function renderCitations(citations: Citation[]): void {
  citationList.replaceChildren();
  citations.forEach((citation) => {
    const details = document.createElement("details");
    details.className = "citation-card";
    const rank = citation.location?.source_quality_rank ?? "n/a";
    details.innerHTML = `<summary>${escapeHtml(citation.title)} | ${escapeHtml(citation.source_quality)} | rank ${rank}</summary><p>${escapeHtml(citation.snippet)}</p><p class="muted">${escapeHtml(citation.document_id)}</p>`;
    citationList.appendChild(details);
  });
}

function restoreChatLayout(): void {
  const savedWidth = Number(localStorage.getItem(CHAT_WIDTH_KEY));
  if (Number.isFinite(savedWidth) && savedWidth > 0) setChatWidth(savedWidth);
  setChatHidden(localStorage.getItem(CHAT_HIDDEN_KEY) === "true");
}

function setChatHidden(hidden: boolean): void {
  appShell.classList.toggle("chat-hidden", hidden);
  showChatButton.hidden = !hidden;
  localStorage.setItem(CHAT_HIDDEN_KEY, String(hidden));
}

function resizeChatTo(clientX: number): void {
  setChatWidth(clientX);
}

function setChatWidth(width: number): void {
  const maxWidth = Math.max(300, window.innerWidth - 420);
  const nextWidth = Math.max(300, Math.min(width, maxWidth));
  appShell.style.setProperty("--chat-column-width", `${nextWidth}px`);
  localStorage.setItem(CHAT_WIDTH_KEY, String(Math.round(nextWidth)));
}

function scrollChatToBottom(): void {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function cashLabel(cash: CashBalance): string {
  if (cash.account_id === "opend_fund_assets_cash_sweep") return "Fund Assets";
  return "Cash";
}

function formatCurrency(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2,
    }).format(value);
  } catch {
    return `${currency} ${formatNumber(value)}`;
  }
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 4,
  }).format(value);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
