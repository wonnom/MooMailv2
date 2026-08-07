export type StatusEvent = {
  event_type?: string;
  status: string;
  message: string;
  timestamp: string;
  phase?: string | null;
  node?: string | null;
  subagent?: string | null;
  server_name?: string | null;
  tool_name?: string | null;
  group_key?: string | null;
  child_run_id?: string | null;
  metadata?: Record<string, unknown>;
  error_type?: string | null;
  error_message?: string | null;
};

export type UserProgressEvent = {
  run_id: string;
  stage:
    | "reviewing_request"
    | "loading_saved_portfolio"
    | "checking_evidence_coverage"
    | "retrieving_portfolio_details"
    | "analyzing_evidence"
    | "checking_safety"
    | "complete"
    | "failed";
  status: "started" | "completed" | "failed";
  message: string;
  timestamp: string;
  group_key?: string | null;
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
  output_status?: "approved" | "revised" | "blocked";
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
  portfolio_id?: string;
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

export type InvestmentPlanTrace = {
  mode?: string;
  needs_portfolio_agent?: boolean;
  needs_sentiment_agent?: boolean;
  freshness_requirement?: string;
  portfolio_request?: Record<string, unknown> | null;
  sentiment_task?: Record<string, unknown> | null;
  logical_asset_hints?: unknown[];
  answer_constraints?: string[];
  warnings?: string[];
};

export type InvestmentTurnDecisionTrace = {
  route: string;
  route_reasons: string[];
  required_evidence?: string[];
  cited_evidence_refs?: string[];
  missing_evidence?: string[];
  direct_answer?: string | null;
};

export type LLMCallTrace = {
  purpose: string;
  provider: string;
  model: string;
  status: string;
  duration_ms?: number | null;
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
  progress_events?: UserProgressEvent[];
  trace_summary?: TraceSummary | null;
  investment_plan?: InvestmentPlanTrace | null;
  portfolio_baseline?: Record<string, unknown> | null;
  turn_decision?: InvestmentTurnDecisionTrace | null;
  validated_turn_decision?: InvestmentTurnDecisionTrace | null;
  evidence_coverage?: Record<string, unknown>;
  llm_calls?: LLMCallTrace[];
  total_llm_calls?: number;
  query_plan?: QueryPlanTrace | null;
  portfolio_packet?: Record<string, unknown> | null;
  sentiment_packet?: SentimentTrace | null;
  synthesis?: SynthesisTrace | null;
};

export type TraceToolGroup = {
  count: number;
  items: Record<string, unknown>[];
};

export type TraceSummary = {
  run_id: string;
  thread_id?: string;
  route?: Record<string, unknown>;
  data_context?: Record<string, unknown>;
  graph?: {
    nodes?: Record<string, unknown>[];
    subagents?: Record<string, unknown>[];
  };
  llm?: {
    total_calls?: number;
    calls_by_purpose?: Record<string, number>;
    calls?: Record<string, unknown>[];
  };
  tools?: Record<string, TraceToolGroup>;
  warnings?: Record<string, unknown>[];
  errors?: Record<string, unknown>[];
  guardrails?: Record<string, unknown> | null;
  source_events?: StatusEvent[];
};

export type StreamError = {
  error_type: string;
  message: string;
  timestamp?: string;
  traceback?: string[];
};

export type MetricResult = {
  metric_name: string;
  value: unknown;
  source_inputs?: Record<string, unknown>;
  warnings?: string[];
};

export type PortfolioConnectionStatus = {
  ok: boolean;
  status: "connected" | "disconnected" | "degraded";
  checked_at: string;
  message: string;
  source: string;
  warnings: string[];
  error?: string | null;
};

export type PortfolioDashboardSnapshot = {
  portfolio_id: string;
  as_of?: string | null;
  last_updated_at: string;
  freshness_status: string;
  connection?: PortfolioConnectionStatus | null;
  portfolio_snapshot?: PortfolioSnapshot | null;
  metrics: MetricResult[];
  history_status: Record<string, unknown>;
  latest_state?: Record<string, unknown> | null;
  storage_result?: Record<string, unknown> | null;
  source_summary: Record<string, unknown>;
  warnings: string[];
  errors: string[];
};

export type PortfolioRefreshResult = {
  status: "refreshed" | "failed";
  dashboard: PortfolioDashboardSnapshot;
  connection: PortfolioConnectionStatus;
  storage_result?: Record<string, unknown> | null;
  warnings: string[];
  errors: string[];
};

export type AllocationView = "bars" | "pie";
export type MessageVariant = "normal" | "error" | "reasoning";
