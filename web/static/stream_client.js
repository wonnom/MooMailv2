export async function runChatStream(query, agent, callbacks) {
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
        if (!handleStreamLine(line, callbacks)) {
          await reader.cancel();
          return;
        }
      }
    }
    if (buffer.trim()) handleStreamLine(buffer, callbacks);
  } catch (error) {
    callbacks.onError(errorPayloadFromCaughtError(error));
  }
}

function handleStreamLine(line, callbacks) {
  if (!line.trim()) return true;
  const payload = JSON.parse(line);
  if (payload.type === "status") {
    callbacks.onStatus(payload.event);
  }
  if (payload.type === "final") {
    callbacks.onFinal(payload.state);
  }
  if (payload.type === "error") {
    callbacks.onError(payload.error);
    return false;
  }
  return true;
}

function errorPayloadFromCaughtError(error) {
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
