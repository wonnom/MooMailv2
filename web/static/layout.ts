import { ui } from "./dom.js";

const CHAT_WIDTH_KEY = "finance_ai_chat_width";
const CHAT_HIDDEN_KEY = "finance_ai_chat_hidden";

export function restoreChatLayout(): void {
  const savedWidth = Number(localStorage.getItem(CHAT_WIDTH_KEY));
  if (Number.isFinite(savedWidth) && savedWidth > 0) setChatWidth(savedWidth);
  setChatHidden(localStorage.getItem(CHAT_HIDDEN_KEY) === "true");
}

export function setChatHidden(hidden: boolean): void {
  ui.appShell.classList.toggle("chat-hidden", hidden);
  ui.showChatButton.hidden = !hidden;
  localStorage.setItem(CHAT_HIDDEN_KEY, String(hidden));
}

export function resizeChatTo(clientX: number): void {
  setChatWidth(clientX);
}

export function setChatWidth(width: number): void {
  const maxWidth = Math.max(300, window.innerWidth - 420);
  const nextWidth = Math.max(300, Math.min(width, maxWidth));
  ui.appShell.style.setProperty("--chat-column-width", `${nextWidth}px`);
  localStorage.setItem(CHAT_WIDTH_KEY, String(Math.round(nextWidth)));
}
