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
