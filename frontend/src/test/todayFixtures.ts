// SYNTHETIC Today fixtures (C01). Every value is fictional: no real NAVs, scheme codes, ISINs or market data.
import type { Explained } from "../lib/types";
import type { CardNumberView, CardView, NeedView, TodayResponse } from "../lib/types-actions";

export function explained(label: string, display: string, formula_id: string, sources = 0): Explained {
  return {
    id: `x.${label.replace(/\W+/g, "_").toLowerCase()}`,
    label,
    display,
    value: null,
    unit: null,
    what: `What ${label} means`,
    formula_id,
    formula: `formula for ${label}`,
    substituted: null,
    inputs: ["synthetic input"],
    sources: Array.from({ length: sources }, (_, i) => ({
      source_id: `synthetic.source.${i}`,
      source_name: `Synthetic source ${i}`,
      url: "https://example.invalid/synthetic",
      retrieved_at: "2026-10-15T06:00:00+00:00",
      observation_date: "2026-10-14",
      quality_status: "OK",
      official: true,
    })),
    observed: "2026-10-14",
    freshness: "END_OF_DAY",
    assumptions: [],
    sensitivity: [],
    limitations: [],
    engine_version: "synthetic-engine",
    hash: "a".repeat(64),
  };
}

export function num(slot: string, display: string, formula_id: string, fact_ids: string[] = []): CardNumberView {
  return {
    slot,
    value: "1",
    unit: "inr",
    as_of: "2026-10-14",
    fact_ids,
    formula_id,
    display,
    explain: explained(slot.replace(/_/g, " "), display, formula_id, fact_ids.length),
  };
}

const base = {
  goal_id: null,
  goal_name: null,
  as_of: "2026-10-14",
  deadline: null,
  status: "VERIFIED" as const,
  impact: null,
  steps: [],
  numbers: [],
  abstentions: [],
  decision: null,
};

export const shortfallCard: CardView = {
  ...base,
  card_id: "c".repeat(64),
  kind: "EMERGENCY_SHORTFALL",
  layer: "L1",
  card_class: "POLICY",
  is_action: true,
  template_id: "emergency_shortfall@1",
  text: "Your emergency reserve is ₹1,11,111 short of the months you chose. Your rule risk.emergency_gate@1 says: put the next ₹1,11,111 into your reserve fund first.",
  impact: { amount_inr: "111111", basis: "SHORTFALL", slot: "shortfall" },
  numbers: [num("shortfall", "₹1,11,111", "risk.emergency_gate@1", ["101"])],
  steps: [
    {
      verb: "INVEST",
      instrument_id: "mf:synthetic-reserve",
      instrument_name: "Synthetic Reserve Fund",
      formula_id: "risk.emergency_gate@1",
      folio: null,
      lots_consumed: [],
      wait_until: null,
      numbers: [num("amount", "₹1,11,111", "risk.emergency_gate@1")],
    },
  ],
  why: {
    rule_id: "risk.emergency_gate",
    rule_version: 1,
    rule_ref: "risk.emergency_gate@1",
    parameters: [{ name: "emergency_months", value: "6", set_by: "user", set_on: "2026-10-01" }],
  },
};

export const harvestCard: CardView = {
  ...base,
  card_id: "d".repeat(64),
  kind: "LTCG_HARVEST",
  layer: "L6",
  card_class: "POLICY",
  is_action: true,
  status: "NOT VERIFIED",
  deadline: "2027-03-31",
  template_id: "ltcg_harvest@1",
  text: "₹22,222 of your long-term gains allowance is unused. Your rule tax.ltcg_harvest@1 says: redeem and reinvest to use it.",
  impact: { amount_inr: "2777", basis: "TAX_DEFERRED", slot: "tax_deferred" },
  numbers: [num("unused_allowance", "₹22,222", "tax.ltcg_harvest@1"), num("tax_deferred", "₹2,777", "tax.ltcg_harvest@1")],
  steps: [
    {
      verb: "REDEEM",
      instrument_id: "mf:synthetic-equity",
      instrument_name: null,
      formula_id: "tax.ltcg_harvest@1",
      folio: "SYN/1",
      lots_consumed: ["lot-1"],
      wait_until: null,
      numbers: [num("units", "12.345 units", "tax.ltcg_harvest@1")],
    },
  ],
  why: { rule_id: "tax.ltcg_harvest", rule_version: 1, rule_ref: "tax.ltcg_harvest@1", parameters: [] },
};

export const abstainCard: CardView = {
  ...base,
  card_id: "e".repeat(64),
  kind: "ABSTAIN",
  layer: "L3",
  card_class: "STATUS",
  is_action: false,
  status: "REQUIRES CONFIGURATION",
  template_id: "abstain@1",
  text: "The loss budget rule abstained: your loss limit for this goal is not set. This is the expected result, not an error.",
  goal_id: "g1",
  goal_name: "Synthetic goal",
  abstentions: [{ code: "LOSS_LIMIT_MISSING", missing_input: "loss_limit", how_to_fix: "Set a loss limit in ₹ on the Goals page." }],
  why: { rule_id: "risk.loss_budget", rule_version: 1, rule_ref: "risk.loss_budget@1", parameters: [] },
};

export const noActionCard: CardView = {
  ...base,
  card_id: "f".repeat(64),
  kind: "NO_ACTION_NEEDED",
  layer: "L8",
  card_class: "STATUS",
  is_action: false,
  template_id: "no_action_needed@1",
  text: "All your rules are within limits today (data as of 14-Oct-2026).",
  numbers: [],
  why: { rule_id: "actions.ranking", rule_version: 1, rule_ref: "actions.ranking@1", parameters: [] },
};

export const lossLimitNeed: NeedView = {
  missing_input: "loss_limit",
  codes: ["LOSS_LIMIT_MISSING"],
  how_to_fix: ["Set a loss limit in ₹ on the Goals page."],
  card_ids: [abstainCard.card_id],
  unlocks: [{ card_id: abstainCard.card_id, basis: "AMOUNT_AT_RISK", number: num("unlock", "₹33,333", "actions.needs@1") }],
};

export const taxSlabNeed: NeedView = {
  missing_input: "tax_slab",
  codes: ["TAX_SLAB_MISSING"],
  how_to_fix: ["Choose your tax slab, or use the conservative assumption."],
  card_ids: [],
  unlocks: [],
};

const head = {
  snapshot_id: "s".repeat(64),
  as_of: "2026-10-14",
  computed_at: "2026-10-15T01:30:00+00:00",
  engine_version: "synthetic-engine",
  rules_version: "synthetic-rules",
  input_manifest_hash: "m".repeat(64),
  top_n: 5,
  suppressed: [],
};

export const todayActions: TodayResponse = {
  ...head,
  state: "ACTIONS",
  cards: [shortfallCard, harvestCard, abstainCard],
  suppressed: [{ card_id: "9".repeat(64), kind: "REBALANCE_DUE", layer: "L5", goal_id: null, suppressed_by: shortfallCard.card_id }],
  needs: [lossLimitNeed, taxSlabNeed],
};

export const todayNothing: TodayResponse = { ...head, state: "NOTHING_NEEDED", cards: [noActionCard], needs: [] };

export const todayAbstained: TodayResponse = { ...head, state: "ABSTAINED_ONLY", cards: [abstainCard], needs: [lossLimitNeed] };

export const todayNoSnapshot: TodayResponse = {
  ...head,
  state: "NO_SNAPSHOT",
  snapshot_id: null,
  as_of: null,
  computed_at: null,
  engine_version: null,
  rules_version: null,
  input_manifest_hash: null,
  cards: [],
  needs: [],
};
