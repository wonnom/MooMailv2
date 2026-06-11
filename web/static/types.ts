export type StatusEvent = {
  status: string;
  message: string;
  timestamp: string;
};

export type Citation = {
  citation_id: string;
  title: string;
  document_id: string;
  snippet: string;
  source_quality: string;
  location: Record<string, unknown>;
};

export type Recommendation = {
  title: string;
  rationale: string;
};

export type GuardrailCheck = {
  check: string;
  passed: boolean;
  message: string;
};

export type GuardrailResult = {
  passed: boolean;
  checks?: GuardrailCheck[];
  blocked_reason?: string | null;
  required_revisions?: string[];
};

export type Money = {
  amount: number;
  currency: string;
};

export type CashBalance = {
  account_id: string;
  amount: number;
  currency: string;
  weight: number;
};

export type Holding = {
  ticker: string;
  name: string;
  asset_type: string;
  currency: string;
  quantity: number;
  market_price: number;
  market_value: number;
  portfolio_weight: number;
  unrealized_pnl?: number | null;
};

export type PortfolioSnapshot = {
  as_of: string;
  base_currency: string;
  total_value: Money;
  cash: CashBalance[];
  holdings: Holding[];
};

export type AllocationRow = {
  name: string;
  value: number;
  weight: number;
  currency: string;
};

export type EffectiveCashSummary = {
  currency: string;
  cash_value: number;
  auto_invested_fund_assets_value: number;
  cash_equivalent_value: number;
  effective_cash_value: number;
  effective_cash_weight: number;
};

export type FinalReport = {
  title: string;
  mode: string;
  as_of?: string;
  summary: string;
  portfolio_snapshot?: PortfolioSnapshot | Record<string, unknown>;
  portfolio_analysis?: Record<string, unknown>;
  sentiment_analysis?: Record<string, unknown>;
  recommendations?: Recommendation[];
  missing_data?: string[];
  assumptions?: string[];
  citations?: Citation[];
};

export type QueryPlanTrace = {
  mode?: string;
  needs_portfolio_agent?: boolean;
  needs_sentiment_agent?: boolean;
  route_reason?: string | null;
  portfolio_task?: {
    task_type?: string;
    requested_tickers?: string[];
    required_outputs?: string[];
  } | null;
  sentiment_task?: {
    tickers?: string[];
    reason?: string;
    retrieval_status?: string;
  } | null;
  missing_data?: string[];
  plan_warnings?: string[];
};

export type SentimentTrace = {
  retrieval_status?: string;
  warnings?: string[];
  missing_documents?: unknown[];
};

export type SynthesisTrace = {
  warnings?: string[];
};

export type ChatState = {
  agent_type: string;
  run_id: string;
  mode: string;
  final_report?: FinalReport | null;
  guardrail_result?: GuardrailResult | null;
  status_events: StatusEvent[];
  query_plan?: QueryPlanTrace | null;
  portfolio_packet?: Record<string, unknown> | null;
  sentiment_packet?: SentimentTrace | null;
  synthesis?: SynthesisTrace | null;
};

export type StreamError = {
  error_type: string;
  message: string;
  timestamp?: string;
  traceback?: string[];
};

export type AllocationView = "bars" | "pie";
export type MessageVariant = "normal" | "error" | "reasoning";
