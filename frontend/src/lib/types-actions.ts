// Today page contract (wave-2 package C01). Typed stub of the B02 `routes_today.py` response, mirroring the frozen
// engine dataclasses in backend/src/iip/engine/actions/contracts.py (design-risk-first.md §7.1, amended by
// design-judgement.md §2 grafts 7, 8, 9 and 11), ranking.py and needs.py.
//
// Wire rules the page relies on (B02 must keep them):
//   * Money and every other Decimal travels as a decimal STRING; dates as ISO "YYYY-MM-DD".
//   * Every number the page shows is a `CardNumberView` that carries its own `Explained` (formula, sources, as-of), so
//     the ExplainDrawer opens without a second request. Today is ONE request: GET /api/today (cards + needs together).
//   * There is no `expected_return`, probability or projection anywhere in this contract (ADR-0010; graft 11).
//   * Wording is neutral (U-11): no BUY/SELL. Card text is the engine's template text, rendered server-side; the UI never
//     composes advice text itself.
import type { Explained } from "./types";

export const TODAY_PATH = "/api/today";
/** POST {card_id, snapshot_id} → DecisionLogged. Appends to `decisions_log` ("I did this"; graft 9). */
export const DECISIONS_PATH = "/api/today/decisions";

export type Layer = "L0" | "L1" | "L2" | "L3" | "L4" | "L5" | "L6" | "L7" | "L8";

export type CardKind =
  | "EMERGENCY_SHORTFALL"
  | "GOAL_DATE_BREACH"
  | "LOSS_BUDGET_BREACH"
  | "LIMIT_BREACH"
  | "REBALANCE_DUE"
  | "NEXT_RUPEE"
  | "LTCG_HARVEST"
  | "LT_DATE"
  | "REG_TO_DIRECT"
  | "LOWER_COST_SAME_EXPOSURE"
  | "REVIEW_FLAG"
  | "SIGNAL_TILT"
  | "ABSTAIN"
  | "NO_ACTION_NEEDED"
  | "DATA_ATTENTION";

export type CardClass = "POLICY" | "DESCRIPTIVE" | "SIGNAL" | "STATUS";
export type CardStatus = "VERIFIED" | "NOT VERIFIED" | "REQUIRES CONFIGURATION" | "BLOCKED";
export type Verb = "REDIRECT_SIP" | "INVEST" | "REDEEM" | "SWITCH" | "WAIT_UNTIL" | "REVIEW";
export type ImpactBasis =
  | "SHORTFALL"
  | "TAX_DEFERRED"
  | "TAX_AVOIDED"
  | "ANNUAL_COST_SAVED"
  | "AMOUNT_TO_MOVE"
  | "AMOUNT_AT_RISK";
export type NumberUnit = "inr" | "pct" | "pp" | "units" | "months" | "years" | "days" | "count" | "date";

/** ranking.TodayState, plus NO_SNAPSHOT: the daily job has not produced a snapshot yet (the engine never runs on page
 * load, so the page cannot compute one itself). */
export type TodayState = "ACTIONS" | "NOTHING_NEEDED" | "ABSTAINED_ONLY" | "NO_SNAPSHOT";

/** contracts.CardNumber plus its display string and full explanation. */
export interface CardNumberView {
  slot: string;
  value: string; // decimal string, or ISO date when unit = "date"
  unit: NumberUnit;
  as_of: string;
  fact_ids: string[];
  formula_id: string | null;
  display: string; // exact display string from cards.format_number — the UI never re-formats it
  explain: Explained;
}

export interface ImpactView {
  amount_inr: string;
  basis: ImpactBasis;
  slot: string; // names one of the card's own INR numbers
}

export interface StepView {
  verb: Verb;
  instrument_id: string | null;
  instrument_name: string | null; // the user's own data (holding or watch list); null when unknown
  formula_id: string;
  folio: string | null;
  lots_consumed: string[];
  wait_until: string | null;
  /** Every amount on the step (amount, units, exit load, stamp, STT, tax, net effect) as traceable numbers. */
  numbers: CardNumberView[];
}

export interface ParameterView {
  name: string;
  value: string;
  set_by: "user" | "default" | "rule_table";
  set_on: string | null;
}

export interface WhyView {
  rule_id: string;
  rule_version: number;
  rule_ref: string; // "rule_id@version"
  parameters: ParameterView[];
}

export interface AbstentionView {
  code: string;
  missing_input: string;
  how_to_fix: string;
}

/** decisions_log row for this card, if the user said "I did this". `cas_confirmed` is set by a later CAS import (B06):
 * null = not checked yet, true = the CAS shows it, false = the CAS contradicts it. */
export interface DecisionView {
  decision_id: string;
  decided_at: string; // ISO UTC
  cas_confirmed: boolean | null;
}

export interface CardView {
  card_id: string;
  kind: CardKind;
  layer: Layer;
  card_class: CardClass;
  is_action: boolean;
  goal_id: string | null;
  goal_name: string | null;
  as_of: string;
  deadline: string | null;
  status: CardStatus;
  template_id: string;
  text: string; // rendered template text; every number in it is one of `numbers[].display`
  impact: ImpactView | null;
  steps: StepView[];
  why: WhyView;
  numbers: CardNumberView[];
  abstentions: AbstentionView[];
  decision: DecisionView | null;
}

export interface SuppressedView {
  card_id: string;
  kind: CardKind;
  layer: Layer;
  goal_id: string | null;
  suppressed_by: string;
}

export interface NeedUnlockView {
  card_id: string;
  basis: ImpactBasis;
  number: CardNumberView; // the bound and the formula that computed it
}

/** needs.Need. Bounds are never added: the need ranks by its largest single bound (`unlocks[0]`). */
export interface NeedView {
  missing_input: string;
  codes: string[];
  how_to_fix: string[];
  card_ids: string[];
  unlocks: NeedUnlockView[]; // largest first; empty = the engine could not bound it
}

export interface TodayResponse {
  state: TodayState;
  snapshot_id: string | null;
  as_of: string | null; // data date of the snapshot
  computed_at: string | null; // ISO UTC, when the daily job computed it
  engine_version: string | null;
  rules_version: string | null;
  input_manifest_hash: string | null;
  top_n: number;
  cards: CardView[]; // every visible card, in rank order (layer, deadline, ₹ impact, card_id)
  suppressed: SuppressedView[];
  needs: NeedView[];
}

export interface DecisionRequest {
  card_id: string;
  snapshot_id: string;
}

export interface DecisionLogged {
  card_id: string;
  decision: DecisionView;
}
