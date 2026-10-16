import type {
  ConditionDirection,
  GateResultJson,
  GateStatus,
  RuleState,
  SignalRuleSummary,
  Vocabulary,
} from "../lib/types-signals";

// Evidence gates G1–G14 (research-backtest-method.md §10, plus G13/G14 from design-risk-first.md §6.2). A gate that the
// backend did not report is shown as "Not evaluated" and counts as not passed: the panel fails closed, like the engine.
export const GATE_ORDER = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12", "G13", "G14"] as const;

export const GATE_NAMES: Record<string, string> = {
  G1: "Data provenance",
  G2: "Survivorship",
  G3: "Corporate actions",
  G4: "Leakage",
  G5: "Sample size",
  G6: "Costs and tax",
  G7: "Cost stress",
  G8: "Trial registry",
  G9: "Multiple testing",
  G10: "Robustness",
  G11: "Vault",
  G12: "Live decay monitor",
  G13: "Risk-budget compatibility",
  G14: "Drawdown non-inferiority",
};

/** Plain-English gloss for the reason codes the engine emits. Unknown codes are shown verbatim, never guessed. */
export const REASON_TEXT: Record<string, string> = {
  data_unverified: "an input series lacks a verified source or licence",
  survivorship_unverified: "the universe is not known to be free of survivorship bias",
  unadjusted_prices_suspected: "unexplained price gaps suggest unadjusted corporate actions",
  leakage: "a look-ahead check or the shuffle canary failed",
  insufficient_evidence: "not enough out-of-sample data yet",
  tax_rules_missing: "verified tax rules do not cover the whole test window",
  edge_not_positive_after_costs_tax: "no edge left after costs and tax",
  fragile_to_costs: "the edge disappears when costs are stressed",
  trials_unknown: "the number of trials in the family is not known",
  not_significant_after_multiple_testing: "not significant once every trial is counted",
  hac_t_below_threshold: "HAC t-statistic below 3",
  not_robust: "the edge does not hold across regimes or neighbouring parameters",
  vault_fail: "failed the single evaluation of the sealed final period",
  decay: "the live edge decayed below its lower bound",
  exceeds_loss_budget: "the strategy's worst drawdown would breach your loss limit",
  drawdown_worse_than_benchmark: "its worst drawdown is deeper than buy-and-hold",
  gate_not_implemented: "this gate is not built yet, so it fails closed",
  no_backtest_run: "no backtest has been run for this rule yet",
};

export function gateName(id: string): string {
  return GATE_NAMES[id] ?? id;
}

export function reasonText(code: string | null): string {
  if (!code) return "no reason code reported";
  const gloss = REASON_TEXT[code];
  return gloss ? `${code}: ${gloss}` : code;
}

/** A gate passes only when BOTH flags agree. An inconsistent row is treated as not passed. */
export function gatePassed(g: GateResultJson): boolean {
  return g.status === "pass" && g.passed === true;
}

/** ISO date → "YYYY-MM" (the earliest-review display unit). */
export function monthOf(iso: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(iso);
  if (!m) throw new Error(`not an ISO date: ${iso}`);
  return `${m[1]}-${m[2]}`;
}

export function earliestReviewText(iso: string | null): string {
  return iso ? `Earliest possible review: ${monthOf(iso)}` : "Earliest possible review: not computed (no backtest run yet)";
}

/**
 * What the Signal column shows. Only an ACCEPTED rule whose every gate passed may show a condition; everything else
 * is ABSTAIN. A rule marked ACCEPTED that still reports a failing gate also shows ABSTAIN (fail closed).
 */
export function isActionable(rule: Pick<SignalRuleSummary, "state" | "failing_gate">, gates?: GateResultJson[]): boolean {
  if (rule.state !== "ACCEPTED" || rule.failing_gate !== null) return false;
  if (gates === undefined) return true;
  const byId = new Map(gates.map((g) => [g.gate_id, g]));
  return GATE_ORDER.every((id) => {
    const g = byId.get(id);
    return g !== undefined && gatePassed(g);
  }) && gates.every(gatePassed);
}

/**
 * Neutral wording by default (U-11): "Entry condition met" / "Exit condition met". A BUY/SELL badge is returned only
 * when the owner opted in to the "badges" vocabulary (the Settings wire value) AND the rule is actionable. Never used for the shadow record.
 */
export function conditionWords(
  met: boolean | null,
  direction: ConditionDirection | null,
  vocabulary: Vocabulary,
): { text: string; badge: "BUY" | "SELL" | null } {
  if (met !== true || direction === null) return { text: "No entry or exit condition met", badge: null };
  const text = direction === "entry" ? "Entry condition met" : "Exit condition met";
  const badge = vocabulary === "badges" ? (direction === "entry" ? "BUY" : "SELL") : null;
  return { text, badge };
}

export const STATE_WORD: Record<RuleState, string> = {
  PRE_REGISTERED: "Pre-registered",
  ABSTAIN: "Abstain",
  NO_SIGNAL: "No signal",
  ACCEPTED: "Accepted",
  SUSPENDED: "Suspended",
  RETIRED: "Retired",
};

/** The ABSTAIN badge (word + glyph, never colour alone). */
export function AbstainBadge() {
  return (
    <span className="badge badge--neutral">
      <span aria-hidden="true">⊘</span> ABSTAIN
    </span>
  );
}

/** One-line failing-gate text for the registry row and the rule header. */
export function FailingGate({ gate }: { gate: GateResultJson | null }) {
  if (!gate)
    return <span className="small">Failing gate not reported — treated as not passed (fails closed)</span>;
  return (
    <span className="small">
      <strong>
        {gate.gate_id} {gateName(gate.gate_id)}
      </strong>{" "}
      — {reasonText(gate.reason_code)}
      {gate.detail ? <span className="subtle"> ({gate.detail})</span> : null}
    </span>
  );
}

const STATUS_VIEW: Record<GateStatus | "missing", { glyph: string; word: string }> = {
  pass: { glyph: "✓", word: "Pass" },
  fail: { glyph: "✗", word: "Fail" },
  abstain: { glyph: "⊘", word: "Abstain" },
  missing: { glyph: "–", word: "Not evaluated" },
};

function ValueVsThreshold({ g }: { g: GateResultJson }) {
  if (g.value === null && g.threshold === null) return <span className="subtle">—</span>;
  return (
    <span>
      {g.value ?? "—"}
      {g.threshold !== null ? <span className="subtle"> (needs {g.threshold})</span> : null}
    </span>
  );
}

/**
 * Every evidence gate with its status, value against threshold and reason. Gates G1–G14 are always listed; extra
 * gates the backend reports (e.g. PBO/CSCV, SPA) follow in the order received.
 */
export function GatePanel({ gates }: { gates: GateResultJson[] }) {
  const byId = new Map(gates.map((g) => [g.gate_id, g]));
  const extra = gates.filter((g) => !(GATE_ORDER as readonly string[]).includes(g.gate_id));
  const rows: { id: string; g: GateResultJson | undefined }[] = [
    ...GATE_ORDER.map((id) => ({ id, g: byId.get(id) })),
    ...extra.map((g) => ({ id: g.gate_id, g })),
  ];
  const passed = rows.filter((r) => r.g !== undefined && gatePassed(r.g)).length;
  return (
    <section aria-labelledby="gate-panel-title" className="gate-panel">
      <h2 id="gate-panel-title">Evidence gates</h2>
      <p className="small">
        {passed} of {rows.length} gates passed. A rule stays ABSTAIN until every gate passes; a gate that is missing or
        not built counts as not passed.
      </p>
      <div className="table-wrap">
        <table className="table table--compact">
          <caption className="sr-only">Evidence gates, status, value against threshold, and reason</caption>
          <thead>
            <tr>
              <th scope="col">Gate</th>
              <th scope="col">Status</th>
              <th scope="col">Value</th>
              <th scope="col">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ id, g }) => {
              const key: GateStatus | "missing" = g === undefined ? "missing" : gatePassed(g) ? "pass" : g.status === "pass" ? "fail" : g.status;
              const v = STATUS_VIEW[key];
              return (
                <tr key={id} data-gate={id} data-status={key}>
                  <th scope="row">
                    {id} {gateName(id)}
                  </th>
                  <td>
                    <span aria-hidden="true">{v.glyph}</span> {v.word}
                  </td>
                  <td>{g ? <ValueVsThreshold g={g} /> : <span className="subtle">—</span>}</td>
                  <td className="small">
                    {g === undefined
                      ? "not reported by the engine; fails closed"
                      : gatePassed(g)
                        ? (g.detail || "")
                        : `${reasonText(g.reason_code)}${g.detail ? ` (${g.detail})` : ""}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
