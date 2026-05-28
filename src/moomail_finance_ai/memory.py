from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from moomail_finance_ai.schemas import MemoryRecord


class FileMemoryStore:
    """Local stand-in for the planned Pinecone-backed memory MCP.

    The store keeps durable investment context in a JSON file. It is intentionally simple:
    current portfolio values stay in SQL; this store holds summaries and preferences.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def retrieve(
        self,
        query: str,
        *,
        tickers: Iterable[str] = (),
        limit: int = 8,
    ) -> list[MemoryRecord]:
        memories = [memory for memory in self._read_all() if memory.status == "active"]
        query_terms = _terms(query)
        ticker_terms = {ticker.lower() for ticker in tickers}

        scored = []
        for memory in memories:
            content_terms = _terms(memory.content)
            scope_tickers = {
                str(ticker).lower()
                for ticker in memory.scope.get("tickers", [])
                if isinstance(memory.scope, dict)
            }
            score = len(query_terms & content_terms) + (2 * len(ticker_terms & scope_tickers))
            if score > 0 or memory.memory_type in {"user_preference", "risk_concern"}:
                scored.append((score, memory.created_at, memory))

        return [
            memory
            for _, _, memory in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)[
                :limit
            ]
        ]

    def write(self, memory: MemoryRecord) -> MemoryRecord:
        memories = self._read_all()
        if not memory.memory_id:
            memory = memory.model_copy(update={"memory_id": f"mem_{uuid4().hex}"})
        memories.append(memory)
        self._write_all(memories)
        return memory

    def write_review_summary(
        self,
        *,
        portfolio_id: str,
        run_id: str,
        summary: str,
        tickers: list[str],
    ) -> MemoryRecord:
        return self.write(
            MemoryRecord(
                memory_id=f"mem_{uuid4().hex}",
                memory_type="portfolio_review_summary",
                scope={"portfolio_id": portfolio_id, "tickers": tickers},
                content=summary,
                created_at=datetime.now(UTC),
                source_run_id=run_id,
                requires_user_approval=False,
            )
        )

    def _read_all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [MemoryRecord.model_validate(item) for item in payload]

    def _write_all(self, memories: list[MemoryRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [memory.model_dump(mode="json") for memory in memories]
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_default_memories(store: FileMemoryStore) -> None:
    if store.retrieve("long term risk concentration"):
        return
    now = datetime.now(UTC)
    store.write(
        MemoryRecord(
            memory_id=f"mem_{uuid4().hex}",
            memory_type="user_preference",
            scope={"portfolio_id": "portfolio_default"},
            content="The user prefers long-term US-equity portfolio analysis over short-term trading.",
            created_at=now,
            requires_user_approval=True,
        )
    )
    store.write(
        MemoryRecord(
            memory_id=f"mem_{uuid4().hex}",
            memory_type="risk_concern",
            scope={"portfolio_id": "portfolio_default"},
            content="Pay attention to concentration, margin/cash mechanics, and missing research coverage.",
            created_at=now,
        )
    )


def _terms(text: str) -> set[str]:
    return {
        token.strip(".,:;!?()[]{}\"'").lower()
        for token in text.split()
        if token.strip(".,:;!?()[]{}\"'")
    }

