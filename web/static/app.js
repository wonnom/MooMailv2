const appShell = document.querySelector("#appShell");
const form = document.querySelector("#chatForm");
const agentSelect = document.querySelector("#agentSelect");
const input = document.querySelector("#queryInput");
const sendButton = document.querySelector("#sendButton");
const hideChatButton = document.querySelector("#hideChatButton");
const showChatButton = document.querySelector("#showChatButton");
const chatColumn = document.querySelector(".chat-column");
const chatLog = document.querySelector("#chatLog");
const chatResizeHandle = document.querySelector("#chatResizeHandle");
const statusList = document.querySelector("#statusList");
const guardrailBadge = document.querySelector("#guardrailBadge");
const reportTitle = document.querySelector("#reportTitle");
const reportMode = document.querySelector("#reportMode");
const reportSummary = document.querySelector("#reportSummary");
const allocationBars = document.querySelector("#allocationBars");
const portfolioEvaluation = document.querySelector("#portfolioEvaluation");
const recommendationsList = document.querySelector("#recommendationsList");
const missingDataList = document.querySelector("#missingDataList");
const sentimentList = document.querySelector("#sentimentList");
const citationList = document.querySelector("#citationList");
const traceOutput = document.querySelector("#traceOutput");

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

async function runChat(query, agent) {
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

function handleStreamLine(line) {
  if (!line.trim()) return;
  const payload = JSON.parse(line);
  if (payload.type === "status") addStatus(payload.event);
  if (payload.type === "final") renderState(payload.state);
}

function clearRun() {
  statusList.replaceChildren();
  traceOutput.textContent = "";
  portfolioEvaluation.replaceChildren();
  guardrailBadge.textContent = "Running";
  guardrailBadge.className = "badge";
}

function setRunning(running) {
  sendButton.disabled = running;
}

function addUserMessage(query) {
  const item = document.createElement("li");
  item.className = "user-message";
  item.textContent = query;
  statusList.appendChild(item);
  scrollChatToBottom();
}

function addStatus(event) {
  const item = document.createElement("li");
  item.className = "agent-message";
  item.textContent = `${event.status}: ${event.message}`;
  statusList.appendChild(item);
  scrollChatToBottom();
}

function renderState(state) {
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
  traceOutput.textContent = JSON.stringify({
    run_id: state.run_id,
    agent_type: state.agent_type,
    status_events: state.status_events,
    guardrail_result: state.guardrail_result,
    portfolio_storage: report.portfolio_analysis?.storage_result ?? null,
    tool_calls: report.portfolio_analysis?.tool_calls ?? [],
  }, null, 2);
}

function renderAllocation(report) {
  const allocation = report.portfolio_analysis?.allocation;
  const rows = allocation?.by_asset ?? [];
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

function renderPortfolioEvaluation(report) {
  const evaluation = report.portfolio_analysis?.evaluation;
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
    portfolioEvaluation.appendChild(section);
  });
  if (evaluation.llm_model) {
    const model = document.createElement("p");
    model.className = "muted";
    model.textContent = `Evaluator model: ${evaluation.llm_model}`;
    portfolioEvaluation.appendChild(model);
  }
}

function renderRecommendations(items) {
  recommendationsList.replaceChildren();
  items.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${escapeHtml(item.title)}</strong><br>${escapeHtml(item.rationale)}`;
    recommendationsList.appendChild(li);
  });
}

function renderMissingData(items) {
  missingDataList.replaceChildren();
  items.slice(0, 14).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    missingDataList.appendChild(li);
  });
}

function renderSentiment(sentiment) {
  const holdings = sentiment?.holdings ?? [];
  sentimentList.replaceChildren();
  holdings.forEach((holding) => {
    const card = document.createElement("article");
    card.className = "holding-card";
    card.innerHTML = `<strong>${escapeHtml(holding.ticker)} · ${escapeHtml(holding.stance)}</strong><br>${escapeHtml(holding.thesis_summary)}`;
    sentimentList.appendChild(card);
  });
}

function renderCitations(citations) {
  citationList.replaceChildren();
  citations.forEach((citation) => {
    const details = document.createElement("details");
    details.className = "citation-card";
    const rank = citation.location?.source_quality_rank ?? "n/a";
    details.innerHTML = `<summary>${escapeHtml(citation.title)} · ${escapeHtml(citation.source_quality)} · rank ${rank}</summary><p>${escapeHtml(citation.snippet)}</p><p class="muted">${escapeHtml(citation.document_id)}</p>`;
    citationList.appendChild(details);
  });
}

function restoreChatLayout() {
  const savedWidth = Number(localStorage.getItem(CHAT_WIDTH_KEY));
  if (Number.isFinite(savedWidth) && savedWidth > 0) setChatWidth(savedWidth);
  setChatHidden(localStorage.getItem(CHAT_HIDDEN_KEY) === "true");
}

function setChatHidden(hidden) {
  appShell.classList.toggle("chat-hidden", hidden);
  showChatButton.hidden = !hidden;
  localStorage.setItem(CHAT_HIDDEN_KEY, String(hidden));
}

function resizeChatTo(clientX) {
  setChatWidth(clientX);
}

function setChatWidth(width) {
  const maxWidth = Math.max(300, window.innerWidth - 420);
  const nextWidth = Math.max(300, Math.min(width, maxWidth));
  appShell.style.setProperty("--chat-column-width", `${nextWidth}px`);
  localStorage.setItem(CHAT_WIDTH_KEY, String(Math.round(nextWidth)));
}

function scrollChatToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
