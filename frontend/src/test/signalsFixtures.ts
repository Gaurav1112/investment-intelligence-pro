// SYNTHETIC fixtures for the Signals registry and Rule detail (C03). Rule ids follow the committed registry names
// (design-risk-first.md §6.1); every date, count, hash and statistic below is invented for tests and is not a result.
import type { GateResultJson, RuleDetailResponse, SignalRuleSummary, SignalsResponse } from "../lib/types-signals";

export const gate = (gate_id: string, status: GateResultJson["status"], reason_code: string | null = null, extra: Partial<GateResultJson> = {}): GateResultJson => ({
  gate_id,
  status,
  passed: status === "pass",
  reason_code,
  value: null,
  threshold: null,
  detail: "",
  ...extra,
});

const shadow0 = { evaluations: 0, first_as_of: null, last_as_of: null, condition_met: 0, outcomes_scored: 0, outcomes_unscorable: 0 };

export const RULE_SE: SignalRuleSummary = {
  rule_id: "S-E",
  version: 1,
  class: "S",
  family: "trend_timing",
  title: "10-month trend filter",
  state: "PRE_REGISTERED",
  state_reason: null,
  state_changed_at: "2026-10-01T00:00:00+00:00",
  registered_at: "2026-10-01T00:00:00+00:00",
  failing_gate: gate("G5", "abstain", "insufficient_evidence", { value: "0", threshold: "30", detail: "has 0, needs 30" }),
  trial_count: 1,
  shadow: { evaluations: 12, first_as_of: "2026-10-02", last_as_of: "2026-10-15", condition_met: 7, outcomes_scored: 0, outcomes_unscorable: 0 },
  earliest_review: "2037-04-01",
};

export const RULE_SD: SignalRuleSummary = {
  ...RULE_SE,
  rule_id: "S-D",
  title: "12-1 absolute momentum against a liquid-fund hurdle",
  family: "absolute_momentum",
  state: "ABSTAIN",
  state_reason: "tax_rules_missing",
  failing_gate: gate("G6", "abstain", "tax_rules_missing"),
  trial_count: 3,
  shadow: shadow0,
  earliest_review: null,
};

export const RULE_SF: SignalRuleSummary = {
  ...RULE_SE,
  rule_id: "S-F",
  title: "Dual momentum across equity, gold and gilt",
  family: "dual_momentum",
  state: "NO_SIGNAL",
  state_reason: "not_significant_after_multiple_testing",
  failing_gate: gate("G9", "fail", "not_significant_after_multiple_testing", { value: "0.41", threshold: "0.95" }),
  trial_count: 2,
};

/** A rule whose stored state says ACCEPTED but which still reports a failing gate: must render ABSTAIN. */
export const RULE_SG_INCONSISTENT: SignalRuleSummary = {
  ...RULE_SE,
  rule_id: "S-G",
  title: "Drawdown top-up with new cash",
  family: "drawdown_topup",
  state: "ACCEPTED",
  failing_gate: gate("G10", "abstain", "gate_not_implemented", { detail: "PBO via CSCV is not implemented; the gate fails closed" }),
};

/** Not accepted, and the backend reported no failing gate: the row must still say ABSTAIN and fail closed. */
export const RULE_SE_NO_GATE: SignalRuleSummary = { ...RULE_SE, rule_id: "S-X", title: "Fixture rule without gate", state: "ABSTAIN", failing_gate: null };

export const SIGNALS: SignalsResponse = {
  as_of: "2026-10-15",
  vocabulary: "neutral",
  rules: [RULE_SE, RULE_SD, RULE_SF, RULE_SG_INCONSISTENT],
};

const ALL_PASS: GateResultJson[] = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12", "G13", "G14"].map((id) =>
  gate(id, "pass"),
);

export const DETAIL_SE: RuleDetailResponse = {
  rule: RULE_SE,
  vocabulary: "neutral",
  rule_text: "S_m = 1 if C_m > mean(C_{m-9..m}) else 0",
  roles: ["index_fund.broad_large.direct", "liquid.direct"],
  spec_hash: "a".repeat(64),
  gates: [
    gate("G1", "pass"),
    gate("G2", "pass", null, { detail: "single-instrument rule" }),
    gate("G5", "abstain", "insufficient_evidence", { value: "0", threshold: "30", detail: "has 0, needs 30" }),
    gate("G9", "abstain", "gate_not_implemented"),
    gate("PBO", "abstain", "gate_not_implemented", { detail: "PBO via CSCV is not implemented; the gate fails closed" }),
  ],
  power: {
    n_oos_periods: 0,
    min_oos_periods: 30,
    min_trl_months: "126.4",
    power80_months: "287.9",
    earliest_review: "2037-04-01",
    formula_ids: ["stats.mintrl@1", "stats.power_length@1", "stats.earliest_review@1"],
  },
  publication: { tag: "POST_PUBLICATION", published_on: "2026-10-01", source: "Fixture citation, 2001" },
  expected_excess: { raw: "0.0200", haircut_factor: "0.5", after_haircut: "0.0100", formula_id: "signals.decay_haircut@1" },
  latest: { as_of_date: "2026-10-15", condition_met: true, direction: "entry" },
  shadow: [
    { as_of_date: "2026-10-15", scope_id: "role:index_fund.broad_large.direct", state: "PRE_REGISTERED", condition_met: true, direction: "entry", outcome_status: null, edge_after_cost_tax: null, unscorable_reason: null, snapshot_id: "snap-2" },
    { as_of_date: "2026-10-14", scope_id: "role:index_fund.broad_large.direct", state: "PRE_REGISTERED", condition_met: false, direction: "exit", outcome_status: "unscorable", edge_after_cost_tax: null, unscorable_reason: "nav_missing", snapshot_id: "snap-1" },
    { as_of_date: "2026-09-30", scope_id: "role:index_fund.broad_large.direct", state: "PRE_REGISTERED", condition_met: true, direction: "exit", outcome_status: "scored", edge_after_cost_tax: "-0.0031", unscorable_reason: null, snapshot_id: "snap-0" },
  ],
};

export const DETAIL_ACCEPTED: RuleDetailResponse = {
  ...DETAIL_SE,
  rule: { ...RULE_SE, state: "ACCEPTED", failing_gate: null },
  gates: ALL_PASS,
};
