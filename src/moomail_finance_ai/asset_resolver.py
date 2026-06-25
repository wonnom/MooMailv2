from __future__ import annotations

import re
from typing import Any, Iterable, Literal

from pydantic import Field, field_validator, model_validator

from moomail_finance_ai.agent_schemas import (
    AssetHint,
    AssetResolution,
    AssetResolutionStatus,
    PortfolioRequest,
    TraceEvent,
)
from moomail_finance_ai.schemas import Holding, PortfolioSnapshot, StrictModel


CandidateSource = Literal["sql_latest", "current_snapshot", "fixture"]
IssueSeverity = Literal["warning", "blocking"]

SUPPORTED_MARKETS = {"US"}
KNOWN_MARKET_PREFIXES = {
    "US",
    "HK",
    "CN",
    "SG",
    "JP",
    "UK",
    "EU",
    "AU",
    "CA",
    "CRYPTO",
}
UNSUPPORTED_MARKET_HINTS = KNOWN_MARKET_PREFIXES - SUPPORTED_MARKETS


class PortfolioAssetCandidate(StrictModel):
    canonical_symbol: str
    ticker: str
    display_name: str
    sql_asset_id: str | None = None
    market: str | None = "US"
    asset_type: str = "equity"
    exchange: str | None = None
    currency: str | None = None
    source: CandidateSource = "fixture"
    warnings: list[str] = Field(default_factory=list)

    @field_validator("canonical_symbol", "ticker")
    @classmethod
    def _normalize_symbol_fields(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("asset candidate symbol fields cannot be blank.")
        return normalized

    @field_validator("market", "exchange")
    @classmethod
    def _normalize_optional_upper(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @model_validator(mode="after")
    def _derive_market_from_canonical_symbol(self) -> PortfolioAssetCandidate:
        if self.market is None:
            market = _market_from_symbol(self.canonical_symbol)
            if market:
                self.market = market
        return self


class PortfolioPlanValidationIssue(StrictModel):
    code: str
    message: str
    severity: IssueSeverity
    hint_input: str | None = None
    resolution_status: AssetResolutionStatus | None = None


class PortfolioPlanValidationResult(StrictModel):
    is_valid: bool
    blocking_issues: list[PortfolioPlanValidationIssue] = Field(default_factory=list)
    warnings: list[PortfolioPlanValidationIssue] = Field(default_factory=list)
    trace_events: list[TraceEvent] = Field(default_factory=list)


def build_portfolio_asset_candidates(
    *,
    sql_assets: Iterable[dict[str, Any] | PortfolioAssetCandidate] | None = None,
    current_snapshot: PortfolioSnapshot | None = None,
    fixture_candidates: Iterable[dict[str, Any] | PortfolioAssetCandidate] | None = None,
) -> list[PortfolioAssetCandidate]:
    candidates: list[PortfolioAssetCandidate] = []
    seen: set[str] = set()

    for candidate in _coerce_candidates(sql_assets or [], source="sql_latest"):
        _append_candidate(candidates, seen, candidate)

    if current_snapshot is not None:
        for holding in current_snapshot.holdings:
            _append_candidate(
                candidates,
                seen,
                _candidate_from_holding(holding),
            )

    for candidate in _coerce_candidates(fixture_candidates or [], source="fixture"):
        _append_candidate(candidates, seen, candidate)

    return candidates


def normalize_asset_hint_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def resolve_asset_hints(
    hints: Iterable[AssetHint | str],
    candidates: Iterable[PortfolioAssetCandidate | dict[str, Any]],
) -> list[AssetResolution]:
    candidate_models = [coerce_asset_candidate(candidate) for candidate in candidates]
    return [resolve_asset_hint(hint, candidate_models) for hint in hints]


def resolve_asset_hint(
    hint: AssetHint | str,
    candidates: Iterable[PortfolioAssetCandidate | dict[str, Any]],
) -> AssetResolution:
    asset_hint = hint if isinstance(hint, AssetHint) else AssetHint(raw_input=hint)
    candidate_models = [coerce_asset_candidate(candidate) for candidate in candidates]
    raw_input = asset_hint.raw_input
    stripped = raw_input.strip()
    prefixed_market, prefixed_symbol = _split_market_prefixed_symbol(stripped)
    market_hint = asset_hint.market_hint or prefixed_market

    if market_hint and market_hint in UNSUPPORTED_MARKET_HINTS:
        return _unresolved(
            raw_input,
            "unsupported_market",
            source="asset_resolver",
            warning=f"Market '{market_hint}' is outside the V1.4 US-equity resolver scope.",
        )

    if prefixed_market and prefixed_symbol:
        matches = [
            candidate
            for candidate in candidate_models
            if _matches_prefixed_symbol(candidate, prefixed_market, prefixed_symbol)
        ]
    elif _looks_like_symbol(stripped):
        matches = [
            candidate
            for candidate in candidate_models
            if _matches_symbol(candidate, stripped, market_hint)
        ]
    else:
        labels = [stripped]
        if asset_hint.company_entity_label:
            labels.append(asset_hint.company_entity_label)
        matches = [
            candidate
            for candidate in candidate_models
            if any(_matches_display_name(candidate, label) for label in labels)
        ]

    if len(matches) == 1:
        return _resolved(raw_input, matches[0])
    if len(matches) > 1:
        symbols = ", ".join(candidate.canonical_symbol for candidate in matches[:5])
        return _unresolved(
            raw_input,
            "ambiguous",
            source="asset_resolver",
            warning=f"Multiple portfolio assets matched this hint: {symbols}.",
        )
    if _looks_like_symbol(stripped):
        return _unresolved(
            raw_input,
            "not_in_portfolio",
            source="asset_resolver",
            warning="The symbol looks valid but does not match a held portfolio asset.",
        )
    return _unresolved(
        raw_input,
        "unknown",
        source="asset_resolver",
        warning="The asset hint is too vague to map to a held portfolio asset.",
    )


def coerce_asset_candidate(
    candidate: PortfolioAssetCandidate | dict[str, Any],
) -> PortfolioAssetCandidate:
    if isinstance(candidate, PortfolioAssetCandidate):
        return candidate
    return PortfolioAssetCandidate.model_validate(candidate)


def validate_portfolio_request(
    request: PortfolioRequest,
    resolutions: Iterable[AssetResolution],
    *,
    run_id: str = "portfolio_request_validation",
) -> PortfolioPlanValidationResult:
    blocking_issues: list[PortfolioPlanValidationIssue] = []
    warnings: list[PortfolioPlanValidationIssue] = []
    resolution_list = list(resolutions)

    trade_warning = _trade_execution_issue(request.source_query)
    if trade_warning is not None:
        blocking_issues.append(trade_warning)

    required_assets = _request_requires_resolved_assets(request)
    for resolution in resolution_list:
        if resolution.resolution_status == "resolved":
            warnings.extend(_non_blocking_resolution_warnings(resolution))
            continue
        issue = PortfolioPlanValidationIssue(
            code="asset_resolution_failed",
            message=(
                "Required portfolio asset could not be resolved before tool execution."
                if required_assets
                else "Portfolio asset hint could not be resolved."
            ),
            severity="blocking" if required_assets else "warning",
            hint_input=resolution.input,
            resolution_status=resolution.resolution_status,
        )
        if required_assets:
            blocking_issues.append(issue)
        else:
            warnings.append(issue)

    return PortfolioPlanValidationResult(
        is_valid=not blocking_issues,
        blocking_issues=blocking_issues,
        warnings=warnings,
        trace_events=asset_resolution_trace_events(run_id, resolution_list),
    )


def asset_resolution_trace_events(
    run_id: str,
    resolutions: Iterable[AssetResolution],
) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for resolution in resolutions:
        events.append(
            TraceEvent(
                event_type="status",
                run_id=run_id,
                phase="asset_resolver",
                status=f"asset_resolution_{resolution.resolution_status}",
                message=f"Asset resolver returned {resolution.resolution_status}.",
                metadata={
                    "input": resolution.input,
                    "resolution_status": resolution.resolution_status,
                    "canonical_symbol": resolution.canonical_symbol,
                    "sql_asset_id_present": bool(resolution.sql_asset_id),
                    "source": resolution.source,
                    "warnings": list(resolution.warnings),
                },
            )
        )
    return events


def _coerce_candidates(
    candidates: Iterable[dict[str, Any] | PortfolioAssetCandidate],
    *,
    source: CandidateSource,
) -> list[PortfolioAssetCandidate]:
    coerced: list[PortfolioAssetCandidate] = []
    for candidate in candidates:
        if isinstance(candidate, PortfolioAssetCandidate):
            update = {"source": source} if candidate.source == "fixture" else {}
            coerced.append(candidate.model_copy(update=update))
            continue
        payload = dict(candidate)
        payload["source"] = source
        payload.setdefault(
            "canonical_symbol",
            _canonical_from_identity(
                payload.get("provider_code") or payload.get("canonical_symbol"),
                payload.get("ticker"),
                payload.get("market") or payload.get("exchange"),
            ),
        )
        payload.setdefault("ticker", _ticker_from_symbol(str(payload["canonical_symbol"])))
        payload.setdefault("display_name", payload.get("name") or payload["ticker"])
        payload.setdefault("sql_asset_id", payload.get("asset_id"))
        payload.setdefault("market", _market_from_symbol(str(payload["canonical_symbol"])))
        coerced.append(
            PortfolioAssetCandidate(
                canonical_symbol=str(payload["canonical_symbol"]),
                ticker=str(payload["ticker"]),
                display_name=str(payload["display_name"]),
                sql_asset_id=(
                    str(payload["sql_asset_id"]) if payload.get("sql_asset_id") else None
                ),
                market=str(payload["market"]) if payload.get("market") else None,
                asset_type=str(payload.get("asset_type") or "equity"),
                exchange=str(payload["exchange"]) if payload.get("exchange") else None,
                currency=str(payload["currency"]) if payload.get("currency") else None,
                source=source,
                warnings=list(payload.get("warnings") or []),
            )
        )
    return coerced


def _candidate_from_holding(holding: Holding) -> PortfolioAssetCandidate:
    canonical_symbol = _canonical_from_identity(
        holding.asset_id,
        holding.ticker,
        holding.exchange,
    )
    return PortfolioAssetCandidate(
        canonical_symbol=canonical_symbol,
        ticker=holding.ticker,
        display_name=holding.name,
        sql_asset_id=holding.asset_id,
        market=_market_from_symbol(canonical_symbol) or _market_from_exchange(holding.exchange),
        asset_type=holding.asset_type,
        exchange=holding.exchange,
        currency=holding.currency,
        source="current_snapshot",
    )


def _append_candidate(
    candidates: list[PortfolioAssetCandidate],
    seen: set[str],
    candidate: PortfolioAssetCandidate,
) -> None:
    key = _candidate_identity_key(candidate)
    if key in seen:
        return
    seen.add(key)
    candidates.append(candidate)


def _candidate_identity_key(candidate: PortfolioAssetCandidate) -> str:
    return _normalize_symbol(candidate.canonical_symbol)


def _canonical_from_identity(
    provider_or_asset_id: Any,
    ticker: Any,
    market_or_exchange: Any,
) -> str:
    identity = _strip_asset_prefix(str(provider_or_asset_id or ""))
    if "." in identity and _market_from_symbol(identity):
        return identity.upper()
    ticker_value = str(ticker or _ticker_from_symbol(identity)).strip().upper()
    market = _market_from_exchange(str(market_or_exchange or "")) or "US"
    return f"{market}.{ticker_value}" if ticker_value else identity.upper()


def _strip_asset_prefix(value: str) -> str:
    if value.startswith("opend:"):
        return value.split(":", 1)[1]
    return value


def _market_from_symbol(symbol: str) -> str | None:
    prefix = symbol.strip().split(".", 1)[0].upper()
    return prefix if prefix in KNOWN_MARKET_PREFIXES else None


def _market_from_exchange(exchange: str | None) -> str | None:
    if exchange is None:
        return None
    normalized = exchange.strip().upper()
    if normalized in {"US", "NASDAQ", "NYSE", "NYSEARCA", "AMEX", "ARCA", "OTC", "PINK"}:
        return "US"
    if normalized in KNOWN_MARKET_PREFIXES:
        return normalized
    return None


def _ticker_from_symbol(symbol: str) -> str:
    stripped = _strip_asset_prefix(symbol).strip().upper()
    market = _market_from_symbol(stripped)
    if market and "." in stripped:
        return stripped.split(".", 1)[1]
    return stripped


def _split_market_prefixed_symbol(value: str) -> tuple[str | None, str | None]:
    if "." not in value:
        return None, None
    prefix, symbol = value.split(".", 1)
    market = prefix.strip().upper()
    if market not in KNOWN_MARKET_PREFIXES:
        return None, None
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        return market, None
    return market, normalized_symbol


def _matches_prefixed_symbol(
    candidate: PortfolioAssetCandidate,
    market: str,
    symbol: str,
) -> bool:
    return _normalize_symbol(candidate.canonical_symbol) == _normalize_symbol(f"{market}.{symbol}")


def _matches_symbol(
    candidate: PortfolioAssetCandidate,
    value: str,
    market_hint: str | None,
) -> bool:
    symbol = value.strip().upper()
    if market_hint and candidate.market and candidate.market != market_hint:
        return False
    return candidate.ticker == symbol or _ticker_from_symbol(candidate.canonical_symbol) == symbol


def _matches_display_name(candidate: PortfolioAssetCandidate, value: str) -> bool:
    hint_label = _normalize_label(value)
    candidate_label = _normalize_label(candidate.display_name)
    if not hint_label or not candidate_label:
        return False
    return (
        hint_label == candidate_label
        or candidate_label.startswith(f"{hint_label} ")
        or hint_label in candidate_label.split()
    )


def _looks_like_symbol(value: str) -> bool:
    stripped = value.strip().upper()
    if _split_market_prefixed_symbol(stripped)[0]:
        return True
    return re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", stripped) is not None


def _normalize_symbol(value: str) -> str:
    return _strip_asset_prefix(value).strip().upper()


def _normalize_label(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    suffixes = {"inc", "corp", "corporation", "company", "co", "plc", "ltd", "limited", "com"}
    tokens = [token for token in cleaned.split() if token not in suffixes]
    return " ".join(tokens)


def _resolved(raw_input: str, candidate: PortfolioAssetCandidate) -> AssetResolution:
    return AssetResolution(
        input=raw_input,
        canonical_symbol=candidate.canonical_symbol,
        sql_asset_id=candidate.sql_asset_id,
        display_name=candidate.display_name,
        resolution_status="resolved",
        warnings=_resolution_warnings(candidate),
        source=candidate.source,
    )


def _unresolved(
    raw_input: str,
    status: AssetResolutionStatus,
    *,
    source: str,
    warning: str,
) -> AssetResolution:
    return AssetResolution(
        input=raw_input,
        resolution_status=status,
        warnings=[warning],
        source=source,
    )


def _resolution_warnings(candidate: PortfolioAssetCandidate) -> list[str]:
    warnings = list(candidate.warnings)
    if candidate.exchange in {"OTC", "PINK"}:
        warnings.append("OTC market data may be limited or unsupported by OpenD.")
    if candidate.asset_type in {"cash", "cash_equivalent"}:
        warnings.append("Cash or cash-equivalent assets may not support equity-specific metrics.")
    if candidate.asset_type == "crypto":
        warnings.append("Crypto assets are outside the current securities-account workflow.")
    if candidate.market and candidate.market not in SUPPORTED_MARKETS:
        warnings.append(
            f"Market '{candidate.market}' is outside the V1.4 US-equity resolver scope."
        )
    return _dedupe(warnings)


def _non_blocking_resolution_warnings(
    resolution: AssetResolution,
) -> list[PortfolioPlanValidationIssue]:
    return [
        PortfolioPlanValidationIssue(
            code="asset_resolution_warning",
            message=warning,
            severity="warning",
            hint_input=resolution.input,
            resolution_status=resolution.resolution_status,
        )
        for warning in resolution.warnings
    ]


def _request_requires_resolved_assets(request: PortfolioRequest) -> bool:
    if not request.asset_hints:
        return False
    return request.task_intent in {"portfolio_fact", "what_changed", "deep_dive", "compare"} or (
        "position_changes" in request.output_goals
    )


def _trade_execution_issue(source_query: str) -> PortfolioPlanValidationIssue | None:
    if not _contains_trade_execution_intent(source_query):
        return None
    return PortfolioPlanValidationIssue(
        code="trade_execution_intent_blocked",
        message="Portfolio requests cannot include trade execution or order-preparation intent.",
        severity="blocking",
    )


def _contains_trade_execution_intent(value: str) -> bool:
    lowered = value.casefold()
    patterns = (
        r"\b(place|submit|execute)\s+(?:an?\s+)?(?:trade|order)\b",
        r"\b(?:trade|order)\s+preparation\b",
        r"\b(?:market|limit)\s+order\b",
        r"\b(?:buy|sell)\s+\d+(?:\.\d+)?\s+(?:shares?|contracts?)\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _dedupe(values: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
