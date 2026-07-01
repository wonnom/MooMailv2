from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from moomail_finance_ai.chat_api import (
    ChatService,
    chat_response,
    error_event_payload,
    normalize_chat_agent,
    status_event_payload,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class _ClientDisconnected(Exception):
    """Internal signal used when a streaming client closes its socket."""


class ChatHandler(SimpleHTTPRequestHandler):
    service: ChatService

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json({"ok": True})
            return
        if parsed.path == "/api/portfolio/status":
            try:
                payload = self.service.portfolio_connection_status().model_dump(mode="json")
            except Exception as exc:
                self._json(error_event_payload(exc), status=500)
                return
            self._json(payload)
            return
        if parsed.path == "/api/portfolio/dashboard":
            try:
                payload = self.service.portfolio_dashboard().model_dump(mode="json")
            except Exception as exc:
                self._json(error_event_payload(exc), status=500)
                return
            self._json(payload)
            return
        path = "/" if parsed.path == "/" else unquote(parsed.path)
        file_path = WEB / ("index.html" if path == "/" else path.lstrip("/"))
        if not file_path.resolve().is_relative_to(WEB.resolve()) or not file_path.exists():
            self.send_error(404)
            return
        self._send_file(file_path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/portfolio/refresh":
            try:
                payload = self.service.portfolio_refresh().model_dump(mode="json")
            except Exception as exc:
                self._json(error_event_payload(exc), status=500)
                return
            self._json(payload)
            return
        if parsed.path not in {"/api/chat", "/api/chat/stream"}:
            self.send_error(404)
            return
        payload = self._read_json()
        query = str(payload.get("query") or "Review my portfolio")
        agent = str(payload.get("agent") or self.service.default_agent)
        if parsed.path == "/api/chat":
            try:
                state = self.service.run(query, agent=agent)
            except Exception as exc:
                self._json(error_event_payload(exc), status=500)
                return
            self._json(chat_response(state))
            return
        self._stream_chat(query, agent=agent)

    def _stream_chat(self, query: str, *, agent: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event):
            self._write_line(status_event_payload(event))

        try:
            state = self.service.run(query, agent=agent, status_callback=emit)
        except _ClientDisconnected:
            return
        except Exception as exc:
            try:
                self._write_line(error_event_payload(exc))
            except _ClientDisconnected:
                return
            return
        try:
            self._write_line({"type": "final", "state": chat_response(state)})
        except _ClientDisconnected:
            return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_line(self, payload: dict) -> None:
        try:
            self.wfile.write(json.dumps(payload).encode("utf-8") + b"\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
            raise _ClientDisconnected from exc

    def _send_file(self, file_path: Path) -> None:
        content_type = "text/html"
        if file_path.suffix == ".css":
            content_type = "text/css"
        elif file_path.suffix == ".js":
            content_type = "application/javascript"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local Finance AI chat frontend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--from-report", default=None)
    parser.add_argument(
        "--db",
        default="data/portfolio-history.sqlite",
        help="Portfolio-history SQLite DB path; defaults to the canonical local store.",
    )
    parser.add_argument("--env-file", default="config/local.env")
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "openai"])
    parser.add_argument(
        "--default-agent",
        default="investment_agent",
        choices=["portfolio", "portfolio_agent", "investment", "investment_agent"],
    )
    args = parser.parse_args()

    ChatHandler.service = ChatService(
        from_report=args.from_report,
        db_path=args.db,
        env_file=args.env_file,
        llm_provider=args.llm_provider,
        default_agent=normalize_chat_agent(args.default_agent),
    )
    server = ThreadingHTTPServer((args.host, args.port), ChatHandler)
    print(f"Serving Finance AI chat at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    finally:
        ChatHandler.service.close()


if __name__ == "__main__":
    main()
