import {
  addStatus,
  addUserMessage,
  renderAgentError,
  renderStreamError,
} from "./chat_panel.js";
import { ui } from "./dom.js";
import { resizeChatTo, restoreChatLayout, setChatHidden, setChatWidth } from "./layout.js";
import {
  dashboardToChatState,
  getPortfolioDashboard,
  getPortfolioStatus,
  refreshPortfolioDashboard,
  streamErrorFromException,
} from "./portfolio_api.js";
import {
  renderCurrentAllocation,
  renderState,
  setAllocationView,
} from "./report_components.js";
import { runChatStream } from "./stream_client.js";
import type { ChatState, PortfolioDashboardSnapshot } from "./types.js";

restoreChatLayout();
void loadStoredDashboard();
void loadPortfolioStatus();

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
ui.portfolioRefreshButton.addEventListener("click", () => {
  void refreshDashboard();
});
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
      onError: renderAgentError,
    });
  } finally {
    setRunning(false);
  }
}

function renderFinalState(state: ChatState): void {
  if (!state.final_report) {
    renderAgentError({
      error_type: "MissingFinalReport",
      message: "The backend returned a final event without a final report.",
      timestamp: new Date().toISOString(),
      traceback: [],
    });
    return;
  }
  const planningFailure = state.status_events.find(
    (event) =>
      event.status === "investment_planner_unavailable" ||
      event.status === "complete_with_planning_failure",
  );
  if (planningFailure) {
    renderAgentError({
      error_type: "InvestmentPlanningUnavailable",
      message: state.final_report.summary || planningFailure.message,
      timestamp: planningFailure.timestamp,
      traceback: [],
    });
    return;
  }
  renderState(state);
  ui.portfolioDashboardMeta.textContent = "";
}

function clearRun(): void {
  ui.statusList.replaceChildren();
}

function setRunning(running: boolean): void {
  ui.sendButton.disabled = running;
}

async function loadStoredDashboard(): Promise<void> {
  setDashboardBusy(true, "Loading stored dashboard");
  try {
    const dashboard = await getPortfolioDashboard();
    renderDashboard(dashboard);
  } catch (error) {
    renderStreamError(streamErrorFromException(error));
  } finally {
    setDashboardBusy(false);
  }
}

async function loadPortfolioStatus(): Promise<void> {
  try {
    const status = await getPortfolioStatus();
    setConnectionBadge(status.status, status.message);
  } catch (error) {
    const streamError = streamErrorFromException(error);
    setConnectionBadge("disconnected", streamError.message);
  }
}

async function refreshDashboard(): Promise<void> {
  setDashboardBusy(true, "Refreshing portfolio");
  try {
    const result = await refreshPortfolioDashboard();
    setConnectionBadge(result.connection.status, result.connection.message);
    renderDashboard(result.dashboard);
    if (result.status === "failed") {
      addStatus(
        {
          status: "refresh_failed",
          message: result.errors[0] ?? "Portfolio refresh failed; showing last-known data.",
          timestamp: new Date().toISOString(),
        },
        "error",
      );
    }
  } catch (error) {
    const streamError = streamErrorFromException(error);
    addStatus(
      {
        status: "refresh_failed",
        message: streamError.message,
        timestamp: streamError.timestamp ?? new Date().toISOString(),
      },
      "error",
    );
  } finally {
    setDashboardBusy(false);
  }
}

function renderDashboard(dashboard: PortfolioDashboardSnapshot): void {
  renderState(dashboardToChatState(dashboard));
  ui.portfolioDashboardMeta.textContent = dashboardMeta(dashboard);
  ui.guardrailBadge.textContent = dashboard.errors.length > 0 ? "Dashboard Warning" : "Dashboard Loaded";
  ui.guardrailBadge.className = dashboard.errors.length > 0 ? "badge bad" : "badge good";
  if (dashboard.connection) {
    setConnectionBadge(dashboard.connection.status, dashboard.connection.message);
  }
}

function setDashboardBusy(running: boolean, label?: string): void {
  ui.portfolioRefreshButton.disabled = running;
  if (label) {
    ui.portfolioConnectionBadge.textContent = label;
    ui.portfolioConnectionBadge.className = "badge";
  }
}

function setConnectionBadge(status: string, message: string): void {
  ui.portfolioConnectionBadge.textContent = status;
  ui.portfolioConnectionBadge.title = message;
  ui.portfolioConnectionBadge.className =
    status === "connected" ? "badge good" : status === "degraded" ? "badge" : "badge bad";
}

function dashboardMeta(dashboard: PortfolioDashboardSnapshot): string {
  const asOf = dashboard.as_of ? `As of ${new Date(dashboard.as_of).toLocaleString()}` : "No snapshot";
  const updated = `Updated ${new Date(dashboard.last_updated_at).toLocaleString()}`;
  return `${asOf} | ${updated} | ${dashboard.source_summary.source ?? "portfolio backend"}`;
}
