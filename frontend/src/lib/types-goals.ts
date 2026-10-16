// Goals, loss limits and the six-answer setup — typed stubs for the B01 API (backend/src/iip/services/goals.py and
// backend/src/iip/api/routes_goals.py, PLAN.md wave 2, package B01). Written by C02 against the frozen contracts in
// docs/research/wave1/design-risk-first.md §5.1–5.4 and the stores in backend/src/iip/store/goals_repo.py (A10).
//
// Conventions shared with the rest of the API: money and fractions are decimal STRINGS (never JS numbers), dates are
// ISO 'YYYY-MM-DD', and a value the user has not set is null (the engine abstains on it; nothing is filled in here).
//
// Endpoints this file describes (B01 owns them; C02 only calls them; reconciled at wave-2 integration):
//   GET    /api/goals/setup          → SetupState   (stress_history comes FIRST: crash history before any return figure)
//   PUT    /api/goals/setup          SetupAnswersIn → SetupState (goals merge; profile answers: null keeps, `clear` clears)
//   GET    /api/goals                → GoalsView (B01 GoalsOverview: also answers, mapping, risk_profile, tax_context, policy)
//   PUT    /api/goals/{goal_id}      GoalUpdate (a PATCH: only the fields sent change; the id is in the path) → GoalView
//   DELETE /api/goals/{goal_id}      → { status: "deleted", goal_id }
// The return-target feasibility view uses the existing POST /api/feasibility (FeasibilityIn/FeasibilityResponse in
// lib/types.ts); it is the only place an aspired return appears, as a historical frequency.

import { dateLabel, roundHalfUp, shiftPoint } from "./format";

/** Status labels used across the app (design-risk-first.md "Status labels"). */
export type StatusLabel = "VERIFIED" | "NOT VERIFIED" | "REQUIRES CONFIGURATION" | "BLOCKED";

/** engine/risk Outcome for one stress row: PASS = a value is available, ABSTAIN = it is not (fails closed). */
export type StressOutcome = "PASS" | "ABSTAIN";

/** Risk classes of the L3 stress table (engine/risk/__init__.py RiskClass, table classes only). */
export type StressClass =
  | "EQ_LARGE"
  | "EQ_BROAD"
  | "EQ_MID"
  | "EQ_SMALL"
  | "EQ_FACTOR"
  | "EQ_SECTOR_THEMATIC"
  | "HYBRID"
  | "GOLD"
  | "DEBT_MTM"
  | "CASH_LIKE";

/** One row of the worst-observed-fall table (engine/risk/stress.py ClassStress, serialised). It is history, not a
 * forecast: "the worst fall in the available history of X was Y". Values per U-08 come from the user's local config
 * and/or the AMFI-recomputed drawdown, s = max(cited, recomputed); both are returned with the series dates. */
export interface StressHistoryRow {
  risk_class: StressClass;
  /** Plain-English name, e.g. "Broad Indian equity (flexi-cap, multi-cap, ELSS, Nifty 500 index funds)". */
  label: string;
  outcome: StressOutcome;
  /** Fraction of value lost, peak to trough, e.g. "0.5"; null when the row abstains. */
  stress: string | null;
  chosen: "CITED" | "RECOMPUTED" | "DERIVED" | "FIXED" | "NONE" | null;
  cited_value: string | null;
  recomputed_value: string | null;
  /** Start / end of the AMFI series the recomputed drawdown was measured on. */
  series_start: string | null;
  series_end: string | null;
  /** Peak → recovery in years; null when not recovered or NOT VERIFIED. */
  recovery_years: string | null;
  /** The episode the cited value refers to, e.g. "2008". */
  episode: string | null;
  back_calculated: boolean;
  citation: string | null;
  fact_id: string | null;
  formula_id: string | null;
  status: StatusLabel;
  flags: string[];
  /** Why the row abstains (e.g. "stress value for EQ_MID"), when it does. */
  abstain_reason: string | null;
}

export interface StressHistory {
  /** rules/risk/stress_drawdowns.yaml table_version. */
  table_version: string;
  /** "The worst observed fall is not the worst possible fall …" — shown verbatim on every view that uses the table. */
  caveat: string;
  rows: StressHistoryRow[];
}

// ------------------------------------------------------------------ setup (one CAS upload + about six answers)

export type TaxRegime = "new" | "old";

export interface TaxAnswer {
  /** true = "use the conservative assumption" (highest slab, exemption already used), labelled on every card. */
  use_conservative: boolean;
  regime: TaxRegime | null;
  /** Marginal slab as a fraction, e.g. "0.2". */
  slab_rate: string | null;
}

export interface EmergencyAnswer {
  essential_monthly_expenses: string | null; // ₹ per month
  months: number | null; // 1–60 (engine/risk/emergency.py rejects 0); 3–6 is US-regulator guidance, SEBI attribution NOT VERIFIED
}

/** services/goals.py GoalIn.objective (engine/ranking.py Objective values). */
export type GoalObjective = "A_capital_preservation" | "B_income" | "C_liquidity" | "D_growth" | "E_aggressive_growth";

/** A goal as setup returns it (services/goals.py SetupGoalOut): every stored field, objective and h_safe_years too. */
export interface SetupGoal {
  goal_id: string;
  name: string;
  priority: number; // 1 = first
  target_amount: string | null; // ₹
  target_date: string | null; // YYYY-MM-DD
  /** Set outside these pages (POST /api/goals); setup and the Goals editor never send it, so the server keeps it. */
  objective: GoalObjective | null;
  /** B_g: the ₹ fall the user would sit through without selling. null → that goal gets no equity recommendation. */
  loss_budget_inr: string | null;
  /** T_g: the longest the user would wait for a recovery, in months. */
  recovery_months: number | null;
  /** The goal's safe horizon in years (decimal string); drives the L2 goal-date check. Same rule as objective. */
  h_safe_years: string | null;
}

/** The fields of a goal a write may carry (services/goals.py GoalPatchIn). */
type GoalFields = Omit<SetupGoal, "goal_id">;

/** PUT /api/goals/{goal_id} body (GoalPatchIn, GOAL-1): a merge, not a replacement. An omitted field keeps its stored
 * value; an explicit null clears it; the name cannot be cleared. Unknown fields are rejected; the id is in the path. */
export type GoalUpdate = Partial<Omit<GoalFields, "name">> & { name?: string };

/** A goal in the PUT /api/goals/setup body (SetupGoalIn): with goal_id it merges into that goal like GoalUpdate; with
 * goal_id null it creates one, which needs a name. */
export type SetupGoalIn = GoalUpdate & { goal_id: string | null };

export interface ExtrasAnswer {
  /** Equity LTCG already realised elsewhere this FY; null keeps the conservative "exemption already used". */
  ltcg_used_inr: string | null;
  savings_balance: string | null;
  sweep_fd_balance: string | null;
}

/** GET/PUT /api/goals/setup answers as the server returns them. */
export interface SetupAnswers {
  tax: TaxAnswer;
  emergency: EmergencyAnswer;
  goals: SetupGoal[];
  extras: ExtrasAnswer;
}

/** The setup answers that can be cleared (services/goals.py WireClearable, GOAL-2). In the PUT body a null answer KEEPS
 * its stored value; naming it in `clear` clears it instead. An answer is either given or cleared, never both. */
export type SetupClearable =
  | "emergency.essential_monthly_expenses"
  | "emergency.months"
  | "extras.savings_balance"
  | "extras.sweep_fd_balance";

/** PUT /api/goals/setup body (SetupAnswersIn). Tax answers and the LTCG figure cannot be cleared through it. */
export interface SetupAnswersIn {
  tax: TaxAnswer;
  emergency: EmergencyAnswer;
  goals: SetupGoalIn[];
  extras: ExtrasAnswer;
  clear: SetupClearable[];
}

/** Each clearable answer, as read from a set of answers. */
const CLEARABLE: readonly [SetupClearable, (a: Pick<SetupAnswers, "emergency" | "extras">) => unknown][] = [
  ["emergency.essential_monthly_expenses", (a) => a.emergency.essential_monthly_expenses],
  ["emergency.months", (a) => a.emergency.months],
  ["extras.savings_balance", (a) => a.extras.savings_balance],
  ["extras.sweep_fd_balance", (a) => a.extras.sweep_fd_balance],
];

/** The `clear` list for a setup save: each clearable answer that is stored (non-null in `stored`, the server's last
 * answers) and that the user emptied (null in `sent`). An answer never stored is not named, so nothing is written for it. */
export function setupClearList(
  stored: Pick<SetupAnswers, "emergency" | "extras">,
  sent: Pick<SetupAnswers, "emergency" | "extras">,
): SetupClearable[] {
  return CLEARABLE.filter(([, read]) => read(stored) !== null && read(stored) !== undefined && read(sent) === null).map(
    ([name]) => name,
  );
}

export interface SetupState {
  /** Listed first on purpose (B01 acceptance): the crash history precedes any return figure. */
  stress_history: StressHistory;
  answers: SetupAnswers;
  /** True once a CAS import has been applied to an actual portfolio. */
  cas_imported: boolean;
  /** Plain-English names of the answers still missing; the engine abstains on each. */
  missing: string[];
  complete: boolean;
}

// ------------------------------------------------------------------ Goals page

export interface GoalHolding {
  instrument_id: string;
  folio: string;
  name: string;
  fraction: string; // share of the holding mapped to this goal, (0, 1]
}

export interface GoalView extends SetupGoal {
  holdings: GoalHolding[];
  /** "ABSTAIN" with reasons when a required input (loss limit, date, …) is missing. */
  outcome: "PASS" | "ABSTAIN";
  abstentions: string[];
}

export interface GoalsView {
  as_of: string;
  stress_history: StressHistory;
  goals: GoalView[];
  setup_complete: boolean;
  missing: string[];
}

export const EMPTY_ANSWERS: SetupAnswers = {
  tax: { use_conservative: false, regime: null, slab_rate: null },
  emergency: { essential_monthly_expenses: null, months: null },
  goals: [],
  extras: { ltcg_used_inr: null, savings_balance: null, sweep_fd_balance: null },
};

// ------------------------------------------------------------------ exact helpers (no floats)

/** ₹ amount × fraction, floored to whole rupees, exactly (BigInt on scaled integers). Used only to show "on ₹X the
 * worst fall would have been about ₹Y" — formula `goal amount × worst observed fall`, both inputs shown beside it. */
export function rupeesTimesFraction(amount: string, fraction: string): string {
  const re = /^\d+(\.\d+)?$/;
  if (!re.test(amount) || !re.test(fraction)) throw new Error("not a non-negative decimal string");
  const split = (v: string) => {
    const [i = "0", f = ""] = v.split(".");
    return { n: BigInt(i + f), scale: f.length };
  };
  const a = split(amount);
  const b = split(fraction);
  const product = a.n * b.n;
  return (product / 10n ** BigInt(a.scale + b.scale)).toString();
}

/** "1.5" years → 18 months (floored), exactly; null passes through. */
export function yearsToMonths(years: string | null): number | null {
  if (years === null || !/^\d+(\.\d+)?$/.test(years)) return null;
  const [i = "0", f = ""] = years.split(".");
  return Number((BigInt(i + f) * 12n) / 10n ** BigInt(f.length));
}

/** A fall shown as "−50.0 %" from a fraction string "0.5" (exact; one decimal, half-up). Uses `shiftPoint` (exact, no sign
 * logic). `format.pct` once mis-shifted fractions with fewer than two decimals; that was fixed at wave-2 integration. */
export function fallLabel(fraction: string): string {
  return `−${roundHalfUp(shiftPoint(fraction, 2), 1)} %`;
}

/** The "Basis" cell of a stress row: both values when both exist (s = max(cited, AMFI-recomputed)), with the series start,
 * or the abstention. Plain text so both pages render the same words. */
export function stressBasis(r: StressHistoryRow): string {
  if (r.outcome === "ABSTAIN") return `ABSTAIN: ${r.abstain_reason ?? "no value"} is not configured`;
  return [
    r.cited_value ? `cited ${fallLabel(r.cited_value)}${r.citation ? ` (${r.citation})` : ""}` : null,
    r.recomputed_value
      ? `AMFI-recomputed ${fallLabel(r.recomputed_value)}${r.series_start ? ` (series from ${dateLabel(r.series_start)})` : ""}`
      : null,
    r.cited_value && r.recomputed_value ? "the larger fall is used" : null,
  ]
    .filter(Boolean)
    .join("; ");
}

/** The "Time to recover" cell. */
export function recoveryText(r: StressHistoryRow): string {
  if (r.recovery_years) return `${r.recovery_years} years`;
  return r.outcome === "PASS" ? "not recovered or NOT VERIFIED" : "—";
}
