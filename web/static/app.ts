import { addStatus, addUserMessage, renderStreamError } from "./chat_panel.js";
import { ui } from "./dom.js";
import { resizeChatTo, restoreChatLayout, setChatHidden, setChatWidth } from "./layout.js";
import {
  renderCurrentAllocation,
  renderState,
  resetReportView,
  setAllocationView,
} from "./report_components.js";
import { runChatStream } from "./stream_client.js";
import type { ChatState } from "./types.js";

restoreChatLayout();

ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = ui.input.value.trim();
  if (!query) return;
  clearRun();
  addUserMessage(query);
  void runChat(query, ui.agentSelect.value);
});

ui.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ui.form.requestSubmit();
  }
});

ui.hideChatButton.addEventListener("click", () => setChatHidden(true));
ui.showChatButton.addEventListener("click", () => setChatHidden(false));
ui.allocationSort.addEventListener("change", renderCurrentAllocation);
ui.allocationViewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const nextView = button.dataset.allocationView;
    if (nextView !== "bars" && nextView !== "pie") return;
    setAllocationView(nextView);
  });
});

ui.chatResizeHandle.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  ui.chatResizeHandle.setPointerCapture(event.pointerId);
  resizeChatTo(event.clientX);
});

ui.chatResizeHandle.addEventListener("pointermove", (event) => {
  if (!ui.chatResizeHandle.hasPointerCapture(event.pointerId)) return;
  resizeChatTo(event.clientX);
});

ui.chatResizeHandle.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  const currentWidth = ui.chatColumn.getBoundingClientRect().width;
  const delta = event.key === "ArrowLeft" ? -24 : 24;
  setChatWidth(currentWidth + delta);
});

async function runChat(query: string, agent: string): Promise<void> {
  setRunning(true);
  try {
    await runChatStream(query, agent, {
      onStatus: addStatus,
      onFinal: renderFinalState,
      onError: renderStreamError,
    });
  } finally {
    setRunning(false);
  }
}

function renderFinalState(state: ChatState): void {
  if (!state.final_report) {
    renderStreamError({
      error_type: "MissingFinalReport",
      message: "The backend returned a final event without a final report.",
      timestamp: new Date().toISOString(),
      traceback: [],
    });
    return;
  }
  renderState(state);
}

function clearRun(): void {
  ui.statusList.replaceChildren();
  resetReportView();
  ui.guardrailBadge.textContent = "Running";
  ui.guardrailBadge.className = "badge";
}

function setRunning(running: boolean): void {
  ui.sendButton.disabled = running;
}
