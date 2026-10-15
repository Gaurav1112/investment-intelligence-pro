// API contract types. Every material number is an `Explained` value (ux-design §5.1, ADR-0003).

// Mirrors backend/src/iip/services/explain.py FRESHNESS exactly (a backend test enforces this).
export type Freshness =
  | "LIVE"
  | "DELAYED"
  | "END_OF_DAY"
  | "STALE"
  | "FIXTURE"
  | "MANUAL"
  | "DERIVED"
  | "USER_INPUT"
  | "ILLUSTRATIVE"
  | "UNAVAILABLE"
  | "UNKNOWN";

export interface SourceRef {
  source_id: string;
  source_name: string;
  url: string;
  retrieved_at: string | null; // ISO UTC
  observation_date: string | null; // ISO date (IST calendar)
  quality_status: string;
  official: boolean;
}

export interface Sensitivity {
  label: string;
  display: string;
}

export interface Explained {
  id: string;
  label: string;
  display: string; // exact display string — the UI never re-computes it
  value: string | null; // decimal string
  unit: string | null;
  what: string;
  formula_id: string;
  formula: string;
  substituted: string | null;
  inputs: string[];
  sources: SourceRef[];
  observed: string | null;
  freshness: Freshness;
  assumptions: string[];
  sensitivity: Sensitivity[];
  limitations: string[];
  engine_version: string;
  hash: string;
}

export type ObjectiveCode =
  | "A_capital_preservation"
  | "B_income"
  | "C_liquidity"
  | "D_growth"
  | "E_aggressive_growth";

export interface Profile {
  amount: string | null;
  withdrawal_date: string | null;
  objective: ObjectiveCode | null;
  loss_acceptable: boolean | null;
  max_loss_fraction: string | null;
  early_need: "unlikely" | "possible" | "likely" | null;
  max_days_to_cash: number | null;
  credit_floor: string | null;
  excluded_kinds: string[];
  tax_regime: "new" | "old" | null;
  slab_rate: string | null;
  return_aspiration: string | null;
}

export interface ProfileStatus {
  profile: Profile;
  mode: "PERSONALISED" | "EXPLORATION";
  missing: string[];
  horizon_days: number | null;
  conflicts: string[];
}

export interface Disclosures {
  footer: string;
  items: string[];
}

export interface MoneyDelta {
  value: string;
  display: string;
  pct: string;
}

export interface DiscoveryRow {
  instrument_id: string;
  name: string;
  kind: string | null;
  tier: "T1" | "T2" | "T3" | "T4";
  rank: number | null;
  flags: string[];
  reasons: string[];
  exclusion_codes: string[];
  days_to_cash: number;
  contractual: boolean;
  loss_frequency: { value: string; display: string } | null;
  fixture: boolean;
  observed: string | null;
  outcome: { q05: Explained; q50: Explained; q95: Explained; gain_q50: MoneyDelta; gain_q05: MoneyDelta } | null;
}

export interface DiscoveryResult {
  status: "RANKED" | "NO_SUITABLE_CANDIDATE" | "ABSTAIN" | "EXPLORATION";
  mode: "PERSONALISED" | "EXPLORATION";
  as_of: string;
  context: {
    amount: string;
    amount_value: string;
    horizon_days: number;
    withdrawal_date: string;
    objective: string;
    illustrative: boolean;
    tax_basis: string;
  };
  message: string | null;
  abstain_reasons: string[];
  policy: Record<string, string> | null;
  criteria: string[];
  ranked: DiscoveryRow[];
  excluded: DiscoveryRow[];
  skipped_no_history: number;
  contains_fixtures: boolean;
  report: {
    narrative: string;
    writer: string;
    sections: { worker: string; subject: string; topic: string; stance: string; text: string }[];
    disclosures: string[];
  } | null;
  conflicts: { subject: string; topic: string; supporting: string[]; challenging: string[]; material: boolean }[];
  run: { input_hash: string; output_hash: string; result_hash: string; run_id?: string; versions: Record<string, string> };
}

// ---------------------------------------------------------------- instruments, ingestion, data health, methodology
// Shapes mirror backend/src/iip/api/routes_core.py and services/instruments.py. Decimals are strings throughout.

export type InstrumentKind = "mf_scheme" | "tbill" | "gsec" | "sdl" | "corp_bond" | "fd" | "small_savings" | "cash";
export type Origin = "source" | "manual" | "fixture";
export type QualityStatus = "ok" | "stale" | "suspect" | "rejected" | "fixture" | "manual";

/** Stored exit load (mf_schemes.exit_load_json): rate is a fraction string, as_of an ISO date. */
export interface ExitLoad {
  days: number;
  rate: string;
  citation: string;
  as_of: string;
}

/** One row of GET /api/instruments. The mf_* columns are null for non-MF kinds. */
export interface InstrumentListItem {
  instrument_id: string;
  kind: InstrumentKind;
  name: string;
  origin: Origin;
  amfi_code: string | null;
  category_raw: string | null;
  plan: "direct" | "regular" | null;
  last_nav_date: string | null;
  last_nav: string | null;
  nav_points: number;
  exit_load: ExitLoad | null;
  fixture: boolean;
}

export interface InstrumentList {
  items: InstrumentListItem[];
  truncated: boolean;
}

export interface InstrumentRow {
  instrument_id: string;
  kind: InstrumentKind;
  name: string;
  issuer_id: string | null;
  isin: string | null;
  amfi_code: string | null;
  currency: string;
  origin: Origin;
  created_at: string;
}

export interface MfSchemeTerms {
  instrument_id: string;
  amc: string;
  category_raw: string;
  sebi_category: string | null;
  plan: "direct" | "regular" | null;
  option_type: string | null;
  benchmark: string | null;
  riskometer: string | null;
  prc: string | null;
  exit_load_json: string | null; // raw JSON text of ExitLoad
  expense_ratio: string | null;
  expense_ratio_kind: "TER" | "BER" | null;
  expense_as_of: string | null;
}

export interface BondTerms {
  instrument_id: string;
  face_value: string;
  coupon_rate: string;
  coupon_freq: 0 | 1 | 2 | 4 | 12;
  issue_date: string | null;
  maturity_date: string;
  daycount: string;
  listed: number;
  call_schedule_json: string | null;
  credit_rating: string | null;
  rating_agency: string | null;
  rating_date: string | null;
}

export interface DepositTerms {
  instrument_id: string;
  institution: string;
  rate: string; // fraction
  compounding: string;
  tenure_days: number;
  premature_penalty: string | null; // fraction
  dicgc_eligible: 0 | 1;
  rate_as_of: string;
  citation_url: string | null;
}

export interface SeriesPoint {
  observation_date: string;
  value: string;
  source_id: string;
  source_url: string;
  retrieved_at: string;
  quality_status: QualityStatus;
}

/** GET /api/instruments/{id}. Points are in ascending date order. */
export interface InstrumentDetailResponse {
  instrument: InstrumentRow;
  mf_schemes?: MfSchemeTerms;
  bond_terms?: BondTerms;
  deposit_terms?: DepositTerms;
  series: { series_id: string; points: SeriesPoint[] };
  freshness?: { badge: "END_OF_DAY" | "STALE" | "FIXTURE" | "UNKNOWN"; observed: string | null };
}

export interface CitationIn {
  url: string; // https only
  as_of: string; // ISO date
  note?: string;
}

export interface TBillIn {
  name: string;
  tenor: "91" | "182" | "364";
  maturity: string;
  yield_fraction: string;
  citation: CitationIn;
}

export type InstitutionType = "bank" | "small_finance_bank" | "nbfc" | "hfc" | "post_office";

export interface FDIn {
  institution: string;
  institution_type: InstitutionType;
  rate: string;
  tenure_days: number;
  premature_penalty: string | null;
  existing_deposits_at_institution: string;
  citation: CitationIn;
}

export interface ExitLoadIn {
  days: number;
  rate: string;
  citation: CitationIn;
}

/** services/ingestion.py RunSummary */
export interface RunSummary {
  run_id: string;
  source_id: string;
  status: "ok" | "partial" | "failed" | "held" | "running";
  rows_ok: number;
  rows_rejected: number;
  stored: number;
  detail: string;
}

export interface IngestionRun {
  run_id: string;
  source_id: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "partial" | "failed" | "held";
  rows_ok: number;
  rows_rejected: number;
  raw_sha256: string | null;
  error: string | null;
}

export interface SourceHealth {
  source_id: string;
  name: string;
  owner: string;
  official: boolean;
  mode: "live" | "manual" | "disabled";
  licence: "PERSONAL_USE_ONLY" | "PUBLIC_GOVT" | "LICENSED" | "UNKNOWN";
  licence_note: string;
  terms_url: string | null;
  freshness: string;
  requires_configuration: boolean;
  last_run: Pick<IngestionRun, "status" | "finished_at" | "rows_ok" | "rows_rejected" | "error"> | null;
}

export interface DataHealthResponse {
  sources: SourceHealth[];
  runs: IngestionRun[];
  observation_counts: Record<string, number>;
  tax_rules_loaded: boolean;
  tax_rules_coverage_to: string | null;
}

export interface TaxRuleRow {
  rule_id: string;
  instrument_class: string;
  effective_from: string;
  effective_to: string | null;
  verification: "P" | "S" | "NV";
  source_url: string;
}

export interface MethodologyResponse {
  versions: Record<string, string>;
  tax: { snapshot_date: string; coverage_to: string; rules: TaxRuleRow[] } | null;
  disclosures: Record<string, string>;
}

/** FastAPI request-validation error body (HTTP 422). */
export interface ValidationErrorBody {
  detail: { loc: (string | number)[]; msg: string; type: string }[];
}

// ---------------------------------------------------------------- portfolios, import, watchlist, alerts, evidence, privacy
// Shapes mirror backend/src/iip/api/routes_portfolio.py, services/portfolio.py and services/alerts.py.

export type PortfolioNature = "actual" | "hypothetical";

export interface PortfolioListItem {
  portfolio_id: string;
  name: string;
  nature: PortfolioNature;
  created_at: string;
  transactions: number;
}

export interface PortfolioCreated {
  portfolio_id: string;
  name: string;
  nature: PortfolioNature;
  created_at: string;
}

/** services/portfolio.py TransactionIn — units (≤ 6 dp) and amount (≤ 2 dp) are plain positive decimal strings. */
export interface TransactionIn {
  instrument_id: string;
  txn_date: string;
  txn_type: "buy" | "sell";
  units: string;
  amount: string;
}

export interface TransactionRow {
  txn_id: string;
  instrument_id: string;
  instrument_name: string;
  txn_date: string;
  txn_type: string;
  units: string | null;
  amount: string;
  price: string | null;
  source: "manual" | "csv_import";
  import_batch: string | null;
  created_at: string;
}

export interface TransactionList {
  portfolio_id: string;
  nature: PortfolioNature;
  items: TransactionRow[];
}

/** A source entry as the portfolio service emits it: partial (often only `source_id`). */
export interface LooseSource {
  source_id: string;
  source_name?: string;
  url?: string;
  retrieved_at?: string | null;
  observation_date?: string | null;
  quality_status?: string;
  official?: boolean;
  obs_id?: number;
  evidence?: string;
}

/** `Explained` from services/portfolio.py `_explained`: partial sources and derived freshness labels. */
export interface PortfolioExplained extends Omit<Explained, "sources" | "freshness"> {
  sources: LooseSource[];
  freshness: Freshness | "DERIVED" | "USER_DATA" | "UNAVAILABLE";
}

export interface NavRef {
  source_id: string;
  url: string;
  retrieved_at: string;
  observation_date: string;
  quality_status: string;
  obs_id: number;
  evidence: string;
  value: string;
}

export type HoldingBadge = Freshness | "NOT_VALUED";

export interface SummaryHolding {
  instrument_id: string;
  name: string;
  kind: string;
  category: string;
  units: string;
  lots: number;
  badge: HoldingBadge;
  included_in_totals: boolean;
  exclusion: { code: string; text: string } | null;
  nav: NavRef | null;
  invested: PortfolioExplained;
  market_value: PortfolioExplained | null;
  unrealised_pl: PortfolioExplained | null;
}

export interface AllocationItem {
  key: string;
  market_value: string;
  display: string;
  weight: string;
  share: string; // "12.34%" — largest-remainder, sums to 100.00%
}

export interface Allocation {
  by: string;
  items: AllocationItem[];
  total: string;
  sum_of_items: string;
}

export interface LadderBucket {
  bucket: string;
  market_value: string;
  display: string;
  share: string;
  at_cost_not_valued: string;
  at_cost_display: string;
}

export interface Maturity {
  instrument_id: string;
  name: string;
  kind: string;
  maturity_date: string;
  days_until: number;
  invested_at_cost: string;
  display: string;
  flags: string[];
  source: string;
}

export interface DicgcBank {
  institution: string;
  principal_at_cost: string;
  insured: string;
  uninsured: string;
  display_uninsured: string;
  flags: string[];
}

export interface PortfolioSummary {
  portfolio: { portfolio_id: string; name: string; nature: PortfolioNature };
  label: string;
  as_of: string;
  flags: string[];
  notes: string[];
  holdings: SummaryHolding[];
  totals: {
    market_value: PortfolioExplained;
    invested: PortfolioExplained;
    invested_all_holdings: string;
    unrealised_pl: PortfolioExplained;
    realised_pl: string;
  };
  xirr: {
    scope: string;
    headline_allowed: boolean;
    annualised_detail: { value: string; display: string; warning: string } | null;
    explain: PortfolioExplained;
  };
  allocation: { by_kind: Allocation; by_category: Allocation };
  concentration: { band: string | null; effective_count: string | null; explain: PortfolioExplained };
  liquidity_ladder: { buckets: LadderBucket[]; explain: PortfolioExplained };
  upcoming_maturities: { within_days: number; items: Maturity[] };
  dicgc: { scope: string; banks: DicgcBank[]; note?: string; explain?: PortfolioExplained };
  engine_version: string;
}

export interface ImportStoreRow {
  row: number;
  instrument_id: string;
  instrument_name: string;
  file_instrument_name: string;
  txn_date: string;
  txn_type: "buy";
  units: string;
  amount: string;
  flags: string[];
}

export interface ImportRejectedRow {
  line?: number; // file line (parse stage)
  row?: number; // index among parsed rows (resolve stage)
  reason: string;
  stage: "parse" | "resolve";
}

export interface ImportPreview {
  batch_id: string;
  status: "previewed";
  applied: false;
  file_sha256: string;
  label: string;
  kind: "csv" | "xlsx";
  header: string[];
  will_store: ImportStoreRow[];
  rejected: ImportRejectedRow[];
  warnings: string[];
  already_applied: boolean;
  confirm_with: { sha256: string };
  note: string;
}

export interface ImportApplied {
  batch_id: string;
  status: string;
  applied: boolean;
  portfolio_id: string;
  transactions_created: number;
  rows_rejected: number;
  applied_at: string;
}

export interface WatchObs {
  obs_id: number;
  value: string;
  unit: string;
  observation_date: string;
  source_id: string;
  url: string;
  retrieved_at: string;
  quality_status: string;
  evidence: string;
}

export interface WatchItem {
  instrument_id: string;
  name: string;
  kind: string;
  note: string | null;
  added_at: string;
  series_id: string | null;
  base: WatchObs | null;
  latest: WatchObs | null;
  change: { value: string; unit: string; from: { date: string; value: string }; to: { date: string; value: string } } | null;
  absolute_return: { value: string; display: string; formula_id: string; note: string } | null;
  badge: Freshness;
  reason: string | null;
}

export interface WatchlistResponse {
  as_of: string;
  items: WatchItem[];
}

export type AlertSeverity = "info" | "warning" | "critical";

export interface AlertRow {
  alert_id: string;
  kind: string;
  severity: AlertSeverity;
  subject_id: string | null;
  message: string;
  source_id: string | null;
  observation_ref: string | null;
  created_at: string;
  dedupe_key: string;
  acknowledged_at: string | null;
}

/** services/alerts.py AlertRules — `null` disables a rule; fractions match ^0\.[0-9]{1,6}$. */
export interface AlertRules {
  stale_data: boolean;
  maturity_within_days: number | null;
  concentration_hhi_above: string | null;
  decline_since_added_beyond: string | null;
  tax_coverage_within_days: number | null;
  ingestion_failed_lookback_days: number | null;
}

export interface AlertEvaluation {
  evaluated_at: string;
  rules: AlertRules;
  triggered: number;
  created: AlertRow[];
  already_present: number;
  skipped_portfolios: string[];
  delivery: string;
}

export interface EvidenceBrief {
  obs_id: number;
  value: string;
  observation_date: string;
  retrieved_at: string;
  quality_status: string;
  sha256: string;
  superseded_by: number | null;
}

export interface EvidenceResponse {
  observation: {
    obs_id: number;
    series_id: string;
    kind: string;
    value: string;
    unit: string;
    currency: string | null;
    source_id: string;
    url: string;
    retrieved_at: string;
    observation_date: string;
    publication_time: string | null;
    sha256: string;
    quality: string;
    convention: string | null;
    ingestion_run_id: string | null;
    superseded_by: number | null;
  };
  is_current: boolean;
  fixture: boolean;
  superseded_chain: { newer: EvidenceBrief[]; older: EvidenceBrief[] };
  source: {
    source_id: string;
    owner: string;
    official: number;
    url: string;
    terms_url: string | null;
    licence_note: string;
    mode: string;
    freshness_slo_days: number;
  } | null;
  ingestion_run: {
    run_id: string;
    source_id: string;
    started_at: string;
    finished_at: string | null;
    status: string;
    rows_ok?: number;
    rows_rejected?: number;
    error?: string | null;
  } | null;
}

export interface PrivacyInventory {
  user_data: { tables: Record<string, number>; pending_import_previews: number };
  public_market_data_kept_on_erase: { tables: Record<string, number> };
  backups: { count: number; note: string };
  note: string;
}

export interface BackupResult {
  path: string;
  integrity: string;
  bytes: number;
  sha256: string;
  schema_version: number;
}

export interface EraseResult {
  status: "erased";
  deleted_rows: Record<string, number>;
  backups_deleted: number;
  backups_remaining: number;
  kept: string;
}

// ---------------------------------------------------------------- analysis (compare, scenario, simulate, feasibility, forecast, risk)
// Shapes mirror backend/src/iip/services/analysis.py. Every number is an AnalysisExplained or a typed Refusal (value null).

/** Analysis values use the shared Freshness labels (services/explain.py) and the standard Explained shape. */
export type AnalysisFreshness = Freshness;
export type AnalysisExplained = Explained;

/** analysis.py `refusal`: the metric is gated and NO number is returned. */
export interface Refusal {
  id: string;
  label: string;
  status: "refused";
  code: string;
  reason: string;
  value: null;
}

export type Which = "q05" | "q50" | "q95";
export type Band<T> = Record<Which, T>;

export interface RunBlock {
  input_hash: string;
  result_hash: string;
  versions: Record<string, string>;
}

/** analysis.py Context.describe() */
export interface AnalysisContext {
  amount: string;
  amount_value: string;
  amount_basis: "request" | "profile" | "illustrative";
  withdrawal_date: string;
  date_basis: "request" | "profile" | "illustrative";
  horizon_days: number;
  illustrative: boolean;
  illustrative_label: string | null;
  tax_basis: string;
}

export interface ReturnPair {
  absolute: AnalysisExplained;
  annualised: AnalysisExplained | null;
  annualisation_note: string;
}

export interface CompareRow {
  instrument_id: string;
  name: string;
  kind: string;
  fixture: boolean;
  observed: string | null;
  freshness: AnalysisFreshness;
  evaluable: boolean;
  eligibility_reasons: string[];
  tier: string | null;
  flags: string[];
  // present only when evaluable
  initial_investment?: AnalysisExplained;
  contractual?: boolean;
  gross_proceeds?: Band<AnalysisExplained>;
  costs?: { exit_load: Band<AnalysisExplained>; stamp_duty: AnalysisExplained | null; note: string | null };
  tax?: { basis: string; rule_ids: string[]; unverified: boolean; values: Band<AnalysisExplained> };
  net_proceeds?: Band<AnalysisExplained>;
  net_pnl?: Band<AnalysisExplained>;
  returns?: Band<ReturnPair>;
  liquidity?: { days_to_cash: number; lock_in_days: number | null };
  exit_cost?: AnalysisExplained | Refusal;
  loss_frequency?: { value: string; display: string } | null;
}

export interface CompareIn {
  instrument_ids: string[];
  amount?: string;
  withdrawal_date?: string;
}

export interface CompareResponse {
  status: "OK";
  as_of: string;
  context: AnalysisContext;
  request: { instrument_ids: string[]; amount: string | null; withdrawal_date: string | null; as_of: string };
  rows: CompareRow[];
  order_basis: string;
  order: string[];
  what_would_change_order: { above: string; below: string; text: string; gap: AnalysisExplained }[];
  fixture: boolean;
  disclaimer: string;
  run: RunBlock;
}

export type ShockKey =
  | "rate_bp"
  | "spread_bp"
  | "equity_pct"
  | "inflation_pct"
  | "exit_before_maturity_days"
  | "reinvestment_rate";

/** Decimal shocks travel as strings; exit_before_maturity_days is a whole number of days. */
export interface ShocksIn {
  rate_bp?: string;
  spread_bp?: string;
  equity_pct?: string;
  inflation_pct?: string;
  exit_before_maturity_days?: number;
  reinvestment_rate?: string;
}

export interface ScenarioIn {
  instrument_id: string;
  amount?: string;
  withdrawal_date?: string;
  shocks: ShocksIn;
}

export interface ScenarioQuantity {
  name: string;
  value: string;
  unit: string;
}

export interface ScenarioValues {
  which: Which | "value";
  before: AnalysisExplained;
  after: AnalysisExplained;
  impact: AnalysisExplained;
  impact_fraction: AnalysisExplained;
}

export type ScenarioResult =
  | { shock: ShockKey; input: string; status: "not_applicable"; reason: string; values: null }
  | {
      shock: ShockKey;
      input: string;
      status: "applied";
      scenario_id: string;
      label: string;
      measure: string;
      approximate: boolean;
      probability_weighted: boolean;
      caveats: string[];
      inputs: ScenarioQuantity[];
      outputs: Record<string, ScenarioQuantity[]>;
      values: ScenarioValues[];
    };

export interface ScenarioResponse {
  status: "OK" | "NOT_EVALUABLE";
  as_of: string;
  context: AnalysisContext;
  request: {
    instrument_id: string;
    amount: string | null;
    withdrawal_date: string | null;
    shocks: Record<ShockKey, string | null>;
    as_of: string;
  };
  instrument: { instrument_id: string; name: string; kind: string; category: string | null };
  fixture: boolean;
  note: string;
  base: { net_proceeds: Band<AnalysisExplained>; proceeds_before_tax: Band<AnalysisExplained> } | null;
  results: ScenarioResult[];
  reasons?: string[];
  disclaimer: string;
  run: RunBlock;
}

export interface SimulateIn {
  allocations: { instrument_id: string; weight: string }[];
  amount?: string;
  withdrawal_date?: string;
}

export interface SimHolding {
  instrument_id: string;
  name: string;
  kind: string;
  fixture: boolean;
  weight: string;
  allocation: AnalysisExplained;
  evaluable: boolean;
  tier: string | null;
  flags: string[];
  eligibility_reasons: string[];
  band: Band<AnalysisExplained> | null;
}

export interface SimLadderRow {
  days_to_cash: number | null;
  label: string;
  holdings: string[];
  amount: AnalysisExplained;
  cumulative: AnalysisExplained | null;
}

export interface SimMaturity {
  instrument_id: string;
  maturity_date: string | null;
  status: "no_maturity" | "matures_before_withdrawal" | "matures_on_withdrawal" | "MATURITY_MISMATCH_after_withdrawal";
  days_between?: number;
  note: string;
}

export interface SimDicgcGroup {
  institution: string;
  institution_type: string;
  flags: string[];
  total: AnalysisExplained;
  insured: AnalysisExplained;
  uninsured: AnalysisExplained;
}

export type SimDicgc =
  | { applicable: false; reason: string }
  | {
      applicable: true;
      formula_id: string;
      conventions: string[];
      warnings: string[];
      notes: string[];
      groups: SimDicgcGroup[];
    };

export interface SimulateResponse {
  status: "OK";
  as_of: string;
  context: AnalysisContext;
  request: SimulateIn & { as_of: string };
  holdings: SimHolding[];
  reconciliation: { sum_of_allocations: string; amount: string; reconciles: boolean };
  portfolio: { status: "OK"; method: string; band: Band<AnalysisExplained> } | Refusal;
  concentration: { hhi: AnalysisExplained; effective_count: AnalysisExplained; band: string };
  liquidity_ladder: SimLadderRow[];
  maturity: SimMaturity[];
  dicgc: SimDicgc;
  fixture: boolean;
  disclaimer: string;
  run: RunBlock;
}

export interface FeasibilityIn {
  instrument_id: string;
  target_annual: string;
  horizon_years: 1 | 3 | 5;
  mode?: "CAGR" | "EVERY_YEAR";
}

export interface FeasibilityCount {
  count: number;
  of: number;
  display: string;
  frequency: AnalysisExplained | null;
}

export interface FeasibilityResponse {
  as_of: string;
  request: { instrument_id: string; target_annual: string; horizon_years: number; mode: string; as_of: string };
  instrument: { instrument_id: string; name: string; category: string };
  fixture: boolean;
  frequency_label: string;
  disclaimer: string;
  status: "SUFFICIENT" | "LOW_EVIDENCE" | "REFUSED";
  evidence_level: string;
  low_evidence: boolean;
  low_evidence_note?: string | null;
  refusal?: Refusal;
  context_amount?: AnalysisContext;
  headline?: string;
  independent_periods?: number;
  grid?: { start: string; end: string; steps: number };
  banners?: string[];
  notes?: string[];
  caveats?: string[];
  flags?: string[];
  windows?: number;
  reached_target?: FeasibilityCount;
  loss?: FeasibilityCount;
  percentiles?: Record<string, AnalysisExplained>;
  drawdown?: {
    in_window_mdd: Record<string, AnalysisExplained>;
    worst_in_window_that_reached_target: AnalysisExplained | null;
    median_mdd_inr: AnalysisExplained | null;
  };
  full_history_drawdown?: {
    depth: AnalysisExplained;
    peak_date: string;
    trough_date: string;
    recovery_date: string | null;
    ongoing: boolean;
  };
  dots?: {
    count: number;
    method: string;
    values: { level: string; value: string; display: string }[];
    reached_target: number;
    reached_target_display: string;
    target: { value: string; display: string };
  };
  run: RunBlock;
}

export interface ForecastQuantile {
  level: string;
  return: AnalysisExplained;
  value_inr: AnalysisExplained;
}

export interface ForecastValidation {
  method_id: string;
  horizon_steps: number;
  embargo: number;
  origins: number;
  nominal_band: string;
  status: string;
  refusal?: Refusal;
  coverage?: AnalysisExplained;
  inside?: number;
  n?: number;
  calibration_status?: string;
  passes_coverage_gate?: boolean;
  kupiec_p?: string;
  mean_pinball?: AnalysisExplained;
  mae_b1_median?: AnalysisExplained;
  mae_b3_zero_drift?: AnalysisExplained;
}

export interface ForecastResponse {
  as_of: string;
  request: { instrument_id: string; horizon_days: number; as_of: string };
  instrument: { instrument_id: string; name: string; category: string };
  fixture: boolean;
  label: string;
  horizon: { days: number; steps: number; steps_rule: string };
  promotion: { status: string; reason: string };
  disclaimer: string;
  status: "OK" | "REFUSED";
  refusal?: Refusal;
  context_amount?: AnalysisContext;
  scenario_range?: {
    label: string;
    model_id: string;
    model_version: string;
    data_cutoff: string;
    interpolation: string;
    n_obs: number;
    n_windows: number;
    n_eff: number;
    warnings: string[];
    quantiles: ForecastQuantile[];
  };
  baseline_comparator?: { model_id: string; point: string; label: string; assumptions: string[] };
  assumptions?: string[];
  limitations?: string[];
  unreliable_when?: string[];
  validation?: ForecastValidation;
  run: RunBlock;
}

export type RiskVar = (AnalysisExplained & { value_inr: AnalysisExplained | null }) | Refusal;
export type RiskDrawdown =
  | (AnalysisExplained & { peak_date: string | null; trough_date: string | null; recovery_date: string | null; recovered: boolean })
  | Refusal;

export interface RiskResponse {
  as_of: string;
  request: { instrument_id: string; as_of: string };
  instrument: { instrument_id: string; name: string; category: string; risk_category: string };
  fixture: boolean;
  context_amount: AnalysisContext;
  disclaimer: string;
  status: "OK" | "REFUSED";
  refusal?: Refusal;
  metrics?: {
    volatility: AnalysisExplained | Refusal;
    max_drawdown: RiskDrawdown;
    var_95: RiskVar;
    cvar_95: RiskVar;
    var_99: RiskVar;
    cvar_99: RiskVar;
    sharpe: AnalysisExplained | Refusal;
  };
  run: RunBlock;
}
