// Signals registry and rule detail (PLAN.md wave 2, package C03).
//
// Typed stubs for the read API that wave B serves over the frozen tables of migration 0004 (`signal_rules`,
// `backtest_trials`, `backtest_runs`, `rule_evaluations`, `outcomes`) and the gate results of
// `engine/backtest/stats_gates.py` (GateResult). design-risk-first.md §6.1–6.4, grafted by design-judgement.md §2.1 #1
// (shadow ledger) and §2.2 #12 (power and status display).
//
// Every number arrives as a decimal STRING computed by the backend (stats.mintrl@1, stats.power_length@1,
// stats.earliest_review@1 …). The frontend never computes a statistic; it only formats and fails closed when a value
// is missing.

/** `signal_rules.state` (migration 0004 CHECK constraint). */
export type RuleState = "PRE_REGISTERED" | "ABSTAIN" | "NO_SIGNAL" | "ACCEPTED" | "SUSPENDED" | "RETIRED";

/** `signal_rules.class`: P = policy, D = disclosed-risk sleeve, S = signal (research track). */
export type RuleClass = "P" | "D" | "S";

/** `GateStatus` in engine/backtest/stats_gates.py. Only "pass" passes. */
export type GateStatus = "pass" | "fail" | "abstain";

/** One gate outcome — the JSON form of stats_gates.GateResult. value/threshold are decimal strings. */
export interface GateResultJson {
  gate_id: string; // "G1" … "G14"
  status: GateStatus;
  passed: boolean;
  reason_code: string | null; // always set when status !== "pass"
  value: string | null;
  threshold: string | null;
  detail: string;
}

/** Private-view wording (U-11). "neutral" is the default and the only value until the owner opts in (C04 / B04). */
export type Vocabulary = "neutral" | "buy_sell";

/** Direction of a rule's condition: S-E style rules switch between an entry (into the risky asset) and an exit. */
export type ConditionDirection = "entry" | "exit";

/** Aggregate of the shadow forward ledger (`rule_evaluations` + `outcomes`) for one rule version. */
export interface ShadowSummary {
  evaluations: number; // rule_evaluations rows
  first_as_of: string | null; // ISO date
  last_as_of: string | null; // ISO date
  condition_met: number; // rows with condition_met = 1
  outcomes_scored: number; // outcomes.status = 'scored'
  outcomes_unscorable: number; // outcomes.status = 'unscorable'
}

/** Post-publication out-of-sample tag (design-judgement.md §2.2 #12). */
export type PublicationTag = "POST_PUBLICATION" | "PRE_PUBLICATION" | "MIXED" | "UNKNOWN";

export interface PublicationInfo {
  tag: PublicationTag;
  published_on: string | null; // ISO date of the source paper or of registration
  source: string | null; // citation text (plain text, no link rendering)
}

/** Power and review timing: MinTRL next to the 80 %-power length (stats_gates.min_track_record_length / power_length). */
export interface PowerInfo {
  n_oos_periods: number | null; // non-overlapping OOS months available now
  min_oos_periods: number; // G5 floor (30)
  min_trl_months: string | null; // decimal string; null = not computed (no backtest run)
  power80_months: string | null; // decimal string; null = not computed
  earliest_review: string | null; // ISO date = registration + max(30, ⌈MinTRL⌉) months; null = not computed
  formula_ids: string[]; // e.g. ["stats.mintrl@1", "stats.power_length@1", "stats.earliest_review@1"]
}

/** Expected excess with the ×0.5 live-decay haircut. Shown only as the after-haircut figure. */
export interface ExpectedExcess {
  raw: string | null; // decimal fraction per year, OOS median
  haircut_factor: string; // "0.5"
  after_haircut: string | null; // raw × haircut_factor, computed by the backend
  formula_id: string;
}

/** One row of the registry list (GET /api/signals). */
export interface SignalRuleSummary {
  rule_id: string; // e.g. "S-E"
  version: number;
  class: RuleClass;
  family: string;
  title: string; // plain-English rule name from the committed spec
  state: RuleState;
  state_reason: string | null;
  state_changed_at: string; // ISO timestamp
  registered_at: string; // ISO timestamp
  /** First gate (G1 → G14 order) that did not pass; null only when every gate passed. */
  failing_gate: GateResultJson | null;
  trial_count: number; // backtest_trials rows in this family (gate G8)
  shadow: ShadowSummary;
  earliest_review: string | null; // ISO date; null = not computed
}

export interface SignalsResponse {
  as_of: string | null; // newest rule_evaluations.as_of_date across rules
  vocabulary: Vocabulary;
  rules: SignalRuleSummary[];
}

/** One shadow-ledger row (rule_evaluations LEFT JOIN outcomes). Recorded only; never an action. */
export interface ShadowRow {
  as_of_date: string;
  scope_id: string; // a goal id or a role name — never a scheme code
  state: RuleState;
  condition_met: boolean | null;
  direction: ConditionDirection | null;
  outcome_status: "scored" | "unscorable" | null; // null = not yet due or not yet scored
  edge_after_cost_tax: string | null; // decimal string, only when scored
  unscorable_reason: string | null;
  snapshot_id: string;
}

/** GET /api/signals/{rule_id}/{version}. */
export interface RuleDetailResponse {
  rule: SignalRuleSummary;
  vocabulary: Vocabulary;
  rule_text: string; // the committed formula, e.g. "S_m = 1 if C_m > mean(C_{m-9..m}) else 0"
  roles: string[]; // universe as role names only (design-judgement.md §2.1 #6)
  spec_hash: string;
  gates: GateResultJson[];
  power: PowerInfo;
  publication: PublicationInfo;
  expected_excess: ExpectedExcess | null;
  /** Latest live condition — only meaningful (and only shown) when the rule is ACCEPTED and every gate passed. */
  latest: { as_of_date: string; condition_met: boolean | null; direction: ConditionDirection | null } | null;
  shadow: ShadowRow[]; // newest first
}

export const signalsPath = "/api/signals";
export const ruleDetailPath = (ruleId: string, version: number | string) =>
  `/api/signals/${encodeURIComponent(ruleId)}/${encodeURIComponent(String(version))}`;
export const ruleDetailRoute = (ruleId: string, version: number | string) =>
  `/signals/${encodeURIComponent(ruleId)}/${encodeURIComponent(String(version))}`;
