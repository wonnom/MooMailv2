import { ui } from "./dom.js";
import type { MessageVariant, StatusEvent, StreamError } from "./types.js";

export function addUserMessage(query: string): void {
  const item = document.createElement("li");
  item.className = "user-message";
  item.textContent = query;
  ui.statusList.appendChild(item);
  scrollChatToBottom();
}

export function addAgentMessage(
  message: string,
  variant: MessageVariant = "normal",
): void {
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

export function addStatus(
  event: StatusEvent,
  variant: "normal" | "error" = "normal",
): void {
  addAgentMessage(`${event.status}: ${event.message}`, variant);
}

export function renderStreamError(error: StreamError): void {
  const message = error.message || "The backend stream failed before returning a report.";
  addStatus(
    {
      status: "failed",
      message,
      timestamp: error.timestamp ?? new Date().toISOString(),
    },
    "error",
  );
  ui.reportTitle.textContent = "Run failed";
  ui.reportMode.textContent = "error";
  ui.reportSummary.textContent = message;
  ui.guardrailBadge.textContent = "Failed";
  ui.guardrailBadge.className = "badge bad";
  ui.traceOutput.textContent = JSON.stringify(
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

export function renderAgentError(error: StreamError): void {
  const message = error.message || "The agent failed before returning a report.";
  addStatus(
    {
      status: "agent_failed",
      message,
      timestamp: error.timestamp ?? new Date().toISOString(),
    },
    "error",
  );
  ui.traceOutput.textContent = JSON.stringify(
    {
      status: "agent_failed",
      error_type: error.error_type || "Error",
      message,
      timestamp: error.timestamp ?? new Date().toISOString(),
      traceback: error.traceback ?? [],
    },
    null,
    2,
  );
}

export function scrollChatToBottom(): void {
  ui.chatLog.scrollTop = ui.chatLog.scrollHeight;
}
