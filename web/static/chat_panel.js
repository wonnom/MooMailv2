import { ui } from "./dom.js";

const progressItems = new Map();
const PROGRESS_STAGE_ORDER = [
  "reviewing_request",
  "loading_saved_portfolio",
  "checking_evidence_coverage",
  "retrieving_portfolio_details",
  "analyzing_evidence",
  "checking_safety",
  "complete",
  "failed",
];

const PROGRESS_LABELS = {
  reviewing_request: "Reviewing request",
  loading_saved_portfolio: "Loading saved portfolio",
  checking_evidence_coverage: "Checking available evidence",
  retrieving_portfolio_details: "Retrieving portfolio details",
  analyzing_evidence: "Analyzing evidence",
  checking_safety: "Checking safety",
  complete: "Complete",
  failed: "Needs attention",
};

export function addUserMessage(query) {
  const item = document.createElement("li");
  item.className = "user-message";
  item.textContent = query;
  ui.statusList.appendChild(item);
  scrollChatToBottom();
}

export function addAgentMessage(message, variant = "normal") {
  const item = document.createElement("li");
  item.className =
    variant === "error"
      ? "agent-message error"
      : variant === "reasoning"
        ? "agent-message reasoning"
        : "agent-message";
  item.textContent = message;
  ui.statusList.appendChild(item);
  scrollChatToBottom();
}

export function addStatus(event, variant = "normal", progress) {
  if (progress) {
    addProgress(progress, variant);
    return;
  }
  if (event.status === "refresh_failed" || variant === "error") {
    addAgentMessage(event.message, variant);
  }
}

export function addProgress(event, variant = "normal") {
  const key = event.group_key || event.stage;
  let item = progressItems.get(key);
  if (!item) {
    item = document.createElement("li");
    item.className = "agent-message progress-message";
    const label = document.createElement("strong");
    label.className = "progress-label";
    const message = document.createElement("span");
    message.className = "progress-copy";
    item.append(label, message);
    ui.statusList.appendChild(item);
    progressItems.set(key, item);
  }
  item.className =
    event.status === "failed" || variant === "error"
      ? "agent-message progress-message error"
      : `agent-message progress-message ${event.status}`;
  item.dataset.progressStage = event.stage;
  item.querySelector(".progress-label").textContent = PROGRESS_LABELS[event.stage];
  item.querySelector(".progress-copy").textContent = event.message;
  reorderProgressItems();
  scrollChatToBottom();
}

export function mergeProgress(events) {
  events.forEach((event) => addProgress(event, event.status === "failed" ? "error" : "normal"));
}

export function resetProgress() {
  progressItems.clear();
}

function reorderProgressItems() {
  const ordered = [...progressItems.values()].sort((left, right) =>
    PROGRESS_STAGE_ORDER.indexOf(left.dataset.progressStage) -
    PROGRESS_STAGE_ORDER.indexOf(right.dataset.progressStage),
  );
  ordered.forEach((item) => ui.statusList.appendChild(item));
}

export function renderStreamError(error) {
  addProgress(
    {
      run_id: "stream",
      stage: "failed",
      status: "failed",
      message:
        "The analysis connection ended before completion. Try again; your saved dashboard is unchanged.",
      timestamp: error.timestamp ?? new Date().toISOString(),
      group_key: "progress.failed",
    },
    "error",
  );
  appendErrorDetail(error, "Stream error");
}

export function renderAgentError(error) {
  addProgress(
    {
      run_id: "agent",
      stage: "failed",
      status: "failed",
      message:
        "The analysis could not be completed. Review Run details and try again; your saved dashboard is unchanged.",
      timestamp: error.timestamp ?? new Date().toISOString(),
      group_key: "progress.failed",
    },
    "error",
  );
  appendErrorDetail(error, "Agent error");
}

function appendErrorDetail(error, label) {
  const details = document.createElement("details");
  details.className = "trace-section trace-error";
  const summary = document.createElement("summary");
  summary.textContent = label;
  const body = document.createElement("pre");
  body.textContent = JSON.stringify(
    {
      error_type: error.error_type || "Error",
      message: error.message,
      timestamp: error.timestamp ?? new Date().toISOString(),
      traceback: error.traceback ?? [],
    },
    null,
    2,
  );
  details.append(summary, body);
  ui.traceOutput.appendChild(details);
}

export function scrollChatToBottom() {
  ui.chatLog.scrollTop = ui.chatLog.scrollHeight;
}
