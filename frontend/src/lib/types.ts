// API contract types. Every material number is an `Explained` value (ux-design §5.1, ADR-0003).

export type Freshness = "LIVE" | "DELAYED" | "END_OF_DAY" | "STALE" | "FIXTURE" | "MANUAL" | "UNKNOWN";

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
