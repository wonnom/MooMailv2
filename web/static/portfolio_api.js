export async function getPortfolioStatus() {
  return fetchJson("/api/portfolio/status");
}

export async function getPortfolioDashboard() {
  return fetchJson("/api/portfolio/dashboard");
}

export async function refreshPortfolioDashboard() {
  return fetchJson("/api/portfolio/refresh", { method: "POST" });
}

export function dashboardToChatState(dashboard) {
  const snapshot = dashboard.portfolio_snapshot ?? null;
  const allocationRows = snapshot ? allocationRowsFromSnapshot(snapshot) : [];
  const effectiveCash = snapshot ? effectiveCashFromMetrics(snapshot, dashboard.metrics) : null;
  const missingData = [...dashboard.warnings, ...dashboard.errors];
  return {
    agent_type: "deterministic_portfolio_data_lane",
    run_id: `dashboard-${dashboard.last_updated_at}`,
    mode: "dashboard",
    status_events: [
      {
        status: "dashboard",
        message: dashboardSummary(dashboard),
        timestamp: dashboard.last_updated_at,
      },
    ],
    final_report: {
      title: "Portfolio Dashboard",
      mode: "dashboard",
      as_of: dashboard.as_of ?? snapshot?.as_of,
      summary: dashboardSummary(dashboard),
      portfolio_snapshot: snapshot ?? undefined,
      portfolio_analysis: {
        allocation: { by_asset: allocationRows },
        effective_cash: effectiveCash,
        metrics: dashboard.metrics,
        storage_result: dashboard.storage_result,
        history_status: dashboard.history_status,
        latest_state: dashboard.latest_state,
        source_summary: dashboard.source_summary,
      },
      sentiment_analysis: {},
      recommendations: [],
      missing_data: missingData,
      citations: [],
    },
    guardrail_result: {
      passed: dashboard.errors.length === 0,
      checks: [
        {
          check: "deterministic_backend_lane",
          passed: true,
          message: "Dashboard loaded through backend portfolio APIs without an agent run.",
        },
      ],
    },
  };
}

export function streamErrorFromException(error) {
  if (error instanceof Error) {
    return {
      error_type: error.name || "Error",
      message: error.message,
      timestamp: new Date().toISOString(),
      traceback: [],
    };
  }
  return {
    error_type: "Error",
    message: String(error),
    timestamp: new Date().toISOString(),
    traceback: [],
  };
}

function allocationRowsFromSnapshot(snapshot) {
  return [
    ...snapshot.cash.map((cash) => ({
      name: cash.account_id,
      value: cash.amount,
      weight: cash.weight,
      currency: cash.currency,
    })),
    ...snapshot.holdings.map((holding) => ({
      name: holding.ticker,
      value: holding.market_value,
      weight: holding.portfolio_weight,
      currency: holding.currency,
    })),
  ];
}

function effectiveCashFromMetrics(snapshot, metrics) {
  const cashWeight = metrics.find((metric) => metric.metric_name === "cash_weight");
  const sourceInputs = cashWeight?.source_inputs ?? {};
  const fallbackCashValue = snapshot.cash
    .filter((cash) => cash.account_id !== "opend_fund_assets_cash_sweep")
    .reduce((total, cash) => total + cash.amount, 0);
  const fallbackAutoInvested = snapshot.cash
    .filter((cash) => cash.account_id === "opend_fund_assets_cash_sweep")
    .reduce((total, cash) => total + cash.amount, 0);
  const fallbackCashEquivalent = snapshot.holdings
    .filter((holding) => holding.asset_type === "cash_equivalent")
    .reduce((total, holding) => total + holding.market_value, 0);
  const currency = snapshot.base_currency;
  const cashValue = numberValue(sourceInputs.cash_value, fallbackCashValue);
  const autoInvested = numberValue(
    sourceInputs.auto_invested_fund_assets_value,
    fallbackAutoInvested,
  );
  const cashEquivalent = numberValue(
    sourceInputs.cash_equivalent_value,
    fallbackCashEquivalent,
  );
  const effectiveCashValue =
    numberValue(sourceInputs.effective_cash_value) || cashValue + autoInvested + cashEquivalent;
  return {
    currency,
    cash_value: cashValue,
    auto_invested_fund_assets_value: autoInvested,
    cash_equivalent_value: cashEquivalent,
    effective_cash_value: effectiveCashValue,
    effective_cash_weight:
      typeof cashWeight?.value === "number"
        ? cashWeight.value
        : weight(effectiveCashValue, snapshot.total_value.amount),
  };
}

function dashboardSummary(dashboard) {
  const snapshot = dashboard.portfolio_snapshot;
  const status = dashboard.connection?.status ?? "stored";
  if (!snapshot) {
    return dashboard.errors[0] || "No stored portfolio snapshot is available yet.";
  }
  const total = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: snapshot.total_value.currency,
  }).format(snapshot.total_value.amount);
  return `${total} across ${snapshot.holdings.length} holdings and ${snapshot.cash.length} cash lines. Connection: ${status}. Freshness: ${dashboard.freshness_status}.`;
}

function weight(value, total) {
  if (!Number.isFinite(total) || total === 0) return 0;
  return value / total;
}

function numberValue(value, fallback = 0) {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : 0;
}

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      payload &&
      typeof payload === "object" &&
      "error" in payload &&
      typeof payload.error === "object" &&
      payload.error &&
      "message" in payload.error
        ? String(payload.error.message)
        : `Request failed with HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}
