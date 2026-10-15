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
}

export interface Disclosures {
  footer: string;
  items: string[];
}
