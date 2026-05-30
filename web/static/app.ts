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

type FinalReport = {
  title: string;
  mode: string;
  summary: string;
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
const allocationBars = document.querySelector<HTMLDivElement>("#allocationBars")!;
const portfolioEvaluation = document.querySelector<HTMLDivElement>("#portfolioEvaluation")!;
const recommendationsList = document.querySelector<HTMLUListElement>("#recommendationsList")!;
const missingDataList = document.querySelector<HTMLUListElement>("#missingDataList")!;
const sentimentList = document.querySelector<HTMLDivElement>("#sentimentList")!;
const citationList = document.querySelector<HTMLDivElement>("#citationList")!;
const traceOutput = document.querySelector<HTMLPreElement>("#traceOutput")!;

const CHAT_WIDTH_KEY = "finance_ai_chat_width";
const CHAT_HIDDEN_KEY = "finance_ai_chat_hidden";

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
      for (const line of lines) handleStreamLine(line);
    }
    if (buffer.trim()) handleStreamLine(buffer);
  } catch (error) {
    addStatus({
      status: "failed",
      message: error instanceof Error ? error.message : String(error),
      timestamp: new Date().toISOString(),
    });
    guardrailBadge.textContent = "Failed";
    guardrailBadge.className = "badge bad";
  } finally {
    setRunning(false);
  }
}

function handleStreamLine(line: string): void {
  if (!line.trim()) return;
  const payload = JSON.parse(line);
  if (payload.type === "status") {
    addStatus(payload.event);
  }
  if (payload.type === "final") {
    renderState(payload.state);
  }
}

function clearRun(): void {
  statusList.replaceChildren();
  traceOutput.textContent = "";
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

function addStatus(event: StatusEvent): void {
  const item = document.createElement("li");
  item.className = "agent-message";
  item.textContent = `${event.status}: ${event.message}`;
  statusList.appendChild(item);
  scrollChatToBottom();
}

function renderState(state: ChatState): void {
  const report = state.final_report;
  reportTitle.textContent = report.title;
  reportMode.textContent = state.mode;
  reportSummary.textContent = report.summary;
  guardrailBadge.textContent = state.guardrail_result?.passed ? "Guardrails Passed" : "Guardrails Blocked";
  guardrailBadge.className = state.guardrail_result?.passed ? "badge good" : "badge bad";
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
      portfolio_storage: report.portfolio_analysis?.storage_result ?? null,
      tool_calls: report.portfolio_analysis?.tool_calls ?? [],
    },
    null,
    2,
  );
}

function renderAllocation(report: FinalReport): void {
  const allocation = report.portfolio_analysis?.allocation as Record<string, unknown[]> | undefined;
  const rows = (allocation?.by_asset ?? []) as Array<{ name: string; weight: number }>;
  allocationBars.replaceChildren();
  rows.slice(0, 12).forEach((row) => {
    const container = document.createElement("div");
    container.className = "bar-row";
    const name = document.createElement("span");
    name.textContent = row.name;
    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${Math.max(0, Math.min(Math.abs(row.weight) * 100, 100))}%`;
    track.appendChild(fill);
    const value = document.createElement("span");
    value.textContent = `${(row.weight * 100).toFixed(1)}%`;
    container.append(name, track, value);
    allocationBars.appendChild(container);
  });
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
    card.innerHTML = `<strong>${escapeHtml(holding.ticker)} · ${escapeHtml(holding.stance)}</strong><br>${escapeHtml(holding.thesis_summary)}`;
    sentimentList.appendChild(card);
  });
}

function renderCitations(citations: Citation[]): void {
  citationList.replaceChildren();
  citations.forEach((citation) => {
    const details = document.createElement("details");
    details.className = "citation-card";
    const rank = citation.location?.source_quality_rank ?? "n/a";
    details.innerHTML = `<summary>${escapeHtml(citation.title)} · ${escapeHtml(citation.source_quality)} · rank ${rank}</summary><p>${escapeHtml(citation.snippet)}</p><p class="muted">${escapeHtml(citation.document_id)}</p>`;
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

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
