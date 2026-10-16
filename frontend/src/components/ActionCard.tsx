import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { dateLabel, utcStamp } from "../lib/format";
import type { Explained } from "../lib/types";
import {
  DECISIONS_PATH,
  type CardKind,
  type CardNumberView,
  type CardView,
  type DecisionLogged,
  type DecisionRequest,
  type DecisionView,
  type ImpactBasis,
  type Layer,
  type ParameterView,
  type Verb,
} from "../lib/types-actions";
import { useMutation } from "../lib/useApi";
import { ExplainedNumber } from "./ExplainDrawer";

// Neutral wording only (U-11; design-risk-first.md §7.3): no BUY/SELL, no forecast words. Card advice text is the
// engine's template text; these labels only name things.

export const KIND_TITLE: Record<CardKind, string> = {
  EMERGENCY_SHORTFALL: "Emergency reserve short",
  GOAL_DATE_BREACH: "Goal date closer than your mix allows",
  LOSS_BUDGET_BREACH: "Over your loss limit in the worst historical fall",
  LIMIT_BREACH: "A limit you set is exceeded",
  REBALANCE_DUE: "Rebalance due",
  NEXT_RUPEE: "Where the next rupee goes",
  LTCG_HARVEST: "Long-term gains allowance unused",
  LT_DATE: "Lots turning long-term soon",
  REG_TO_DIRECT: "Regular plan to Direct plan",
  LOWER_COST_SAME_EXPOSURE: "Lower cost, same exposure",
  REVIEW_FLAG: "Worth a review",
  SIGNAL_TILT: "Signal rule condition met",
  ABSTAIN: "Abstained",
  NO_ACTION_NEEDED: "No action needed",
  DATA_ATTENTION: "Data needs attention",
};

export const LAYER_LABEL: Record<Layer, string> = {
  L0: "Data",
  L1: "Emergency reserve",
  L2: "Goal date",
  L3: "Loss limit",
  L4: "Limits",
  L5: "Target mix",
  L6: "Tax and cost",
  L7: "Signal rules",
  L8: "Information",
};

const VERB_LABEL: Record<Verb, string> = {
  REDIRECT_SIP: "Redirect SIP",
  INVEST: "Invest",
  REDEEM: "Redeem",
  SWITCH: "Switch",
  WAIT_UNTIL: "Wait until",
  REVIEW: "Review",
};

export const BASIS_LABEL: Record<ImpactBasis, string> = {
  SHORTFALL: "shortfall",
  TAX_DEFERRED: "tax deferred",
  TAX_AVOIDED: "tax avoided",
  ANNUAL_COST_SAVED: "annual cost saved",
  AMOUNT_TO_MOVE: "amount to move",
  AMOUNT_AT_RISK: "amount at risk",
};

/** "loss_limit" → "Loss limit". */
export function humanise(key: string): string {
  const s = key.replace(/[_.]+/g, " ").trim();
  return s ? s[0]!.toUpperCase() + s.slice(1) : key;
}

/** The card's number as an Explained whose display is the card's own display string (the UI never re-formats it). */
export function asExplained(n: CardNumberView): Explained {
  return { ...n.explain, display: n.display };
}

/** Split template text at every occurrence of a number's display string, so each number in the sentence becomes its
 * own explain button. At each position the earliest match wins, and the longest display on a tie ("₹22,222" before
 * "₹2"). A number may appear more than once. */
export function splitByNumbers(text: string, numbers: readonly CardNumberView[]): (string | CardNumberView)[] {
  const out: (string | CardNumberView)[] = [];
  const candidates = numbers.filter((n) => n.display.length > 0);
  let pos = 0;
  while (pos < text.length) {
    let best: { at: number; n: CardNumberView } | null = null;
    for (const n of candidates) {
      const at = text.indexOf(n.display, pos);
      if (at < 0) continue;
      if (!best || at < best.at || (at === best.at && n.display.length > best.n.display.length)) best = { at, n };
    }
    if (!best) break;
    if (best.at > pos) out.push(text.slice(pos, best.at));
    out.push(best.n);
    pos = best.at + best.n.display.length;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

const EVIDENCE_ID = /^\d{1,12}$/;

function NumberSources({ n, onExplain }: { n: CardNumberView; onExplain: (e: Explained) => void }) {
  const stored = n.fact_ids.filter((f) => EVIDENCE_ID.test(f));
  const other = n.fact_ids.filter((f) => !EVIDENCE_ID.test(f));
  return (
    <li>
      {humanise(n.slot)}: <ExplainedNumber item={asExplained(n)} onExplain={onExplain} />{" "}
      <span className="small subtle">
        as of {dateLabel(n.as_of)}
        {n.formula_id ? (
          <>
            {" "}
            · formula <code>{n.formula_id}</code> · <Link to="/methodology">Methodology</Link>
          </>
        ) : null}
        {stored.map((f) => (
          <span key={f}>
            {" "}
            · <Link to={`/evidence/${f}`}>Evidence #{f}</Link>
          </span>
        ))}
        {other.length ? <> · fact {other.join(", ")}</> : null}
      </span>
    </li>
  );
}

function parameterLine(p: ParameterView): string {
  const who =
    p.set_by === "user"
      ? `set by you${p.set_on ? ` on ${dateLabel(p.set_on)}` : ""}`
      : p.set_by === "default"
        ? "cited default, not set by you"
        : `from the rule table${p.set_on ? ` (${dateLabel(p.set_on)})` : ""}`;
  return `${p.name} = ${p.value} · ${who}`;
}

function casLine(d: DecisionView): string {
  if (d.cas_confirmed === true) return "A later CAS confirms it.";
  if (d.cas_confirmed === false) return "A later CAS does not show it. Check the transaction, then upload a newer CAS.";
  return "Not yet checked against a CAS. The next CAS upload confirms or contradicts it.";
}

function Decision({ card, snapshotId }: { card: CardView; snapshotId: string }) {
  const [decision, setDecision] = useState<DecisionView | null>(card.decision);
  const [confirming, setConfirming] = useState(false);
  const { run, pending, error } = useMutation<DecisionRequest, DecisionLogged>("POST", DECISIONS_PATH);
  const doneBtn = useRef<HTMLButtonElement>(null);
  const yesBtn = useRef<HTMLButtonElement>(null);
  const doneMsg = useRef<HTMLDivElement>(null);
  const returnFocus = useRef(false);
  const justLogged = useRef(false);
  useEffect(() => {
    if (confirming) yesBtn.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      doneBtn.current?.focus();
    }
  }, [confirming]);
  // The focused "Yes" button disappears once the entry is logged: move focus to the message that replaces it (WCAG 2.4.3).
  useEffect(() => {
    if (decision && justLogged.current) {
      justLogged.current = false;
      doneMsg.current?.focus();
    }
  }, [decision]);

  const confirm = async () => {
    const res = await run({ card_id: card.card_id, snapshot_id: snapshotId });
    if (res) {
      justLogged.current = true;
      setDecision(res.decision);
    }
  };
  return (
    <div className="action-card__decide">
      {/* Always mounted, so the text written into it on success is announced (a live region inserted together with its
          text often is not). */}
      <div ref={doneMsg} className="action-card__done small" role="status" tabIndex={decision ? -1 : undefined}>
        {decision ? (
          <>
            You marked this done on {utcStamp(decision.decided_at)}. {casLine(decision)}
          </>
        ) : null}
      </div>
      {decision ? null : confirming ? (
        <div role="group" aria-label="Confirm you did this">
          <button ref={yesBtn} type="button" className="btn btn--primary" disabled={pending} onClick={() => void confirm()}>
            Yes, I did the steps on this card
          </button>{" "}
          <button
            type="button"
            className="btn btn--ghost"
            disabled={pending}
            onClick={() => {
              returnFocus.current = true;
              setConfirming(false);
            }}
          >
            Cancel
          </button>
          <p className="small subtle">This is recorded in your decision log. It cannot be edited later.</p>
        </div>
      ) : (
        <button ref={doneBtn} type="button" className="btn" onClick={() => setConfirming(true)}>
          I did this
        </button>
      )}
      {error && !decision ? (
        <p className="field-error" role="alert">
          Could not record it ({error instanceof ApiError ? error.code : "REQUEST_FAILED"}). Try again.
        </p>
      ) : null}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="action-card__section">
      <h4 className="small subtle">{title}</h4>
      {children}
    </div>
  );
}

/** The id of a card's heading (focusable with tabIndex -1, so a page can move focus to a card). */
export function cardTitleId(card: Pick<CardView, "card_id">): string {
  return `card-${card.card_id.slice(0, 16)}-title`;
}

/** One engine card (design-risk-first.md §7.1). Every number it shows is an explain button. */
export function ActionCard({
  card,
  snapshotId,
  onExplain,
}: {
  card: CardView;
  snapshotId: string | null;
  onExplain: (e: Explained) => void;
}) {
  const titleId = cardTitleId(card);
  const title = `${KIND_TITLE[card.kind]}${card.goal_name ? ` · ${card.goal_name}` : ""}`;
  const parts = splitByNumbers(card.text, card.numbers);
  const stepNumbers = card.steps.flatMap((s) => s.numbers);
  const canLog = card.is_action && card.status !== "BLOCKED" && card.steps.length > 0 && snapshotId !== null;
  return (
    <article className={`card action-card action-card--${card.card_class.toLowerCase()}`} aria-labelledby={titleId}>
      <header className="action-card__head">
        <h3 id={titleId} tabIndex={-1}>
          {title}
        </h3>
        <p className="small subtle">
          <span className="badge badge--neutral">
            {card.layer} · {LAYER_LABEL[card.layer]}
          </span>{" "}
          <span className="badge badge--neutral">{card.status}</span>
          {card.deadline ? <> · Deadline {dateLabel(card.deadline)}</> : null}
        </p>
      </header>
      {card.text ? (
        <p className="action-card__text" data-testid="card-text">
          {parts.map((p, i) =>
            typeof p === "string" ? <span key={i}>{p}</span> : <ExplainedNumber key={i} item={asExplained(p)} onExplain={onExplain} />,
          )}
        </p>
      ) : null}
      {card.steps.length ? (
        <Section title="Steps">
          <ol aria-label="Steps">
            {card.steps.map((s, i) => (
              <li key={i}>
                <strong>{VERB_LABEL[s.verb]}</strong>
                {s.wait_until ? <> {dateLabel(s.wait_until)}</> : null}
                {s.instrument_id ? (
                  <>
                    {" "}
                    <Link to={`/i/${encodeURIComponent(s.instrument_id)}`}>{s.instrument_name ?? s.instrument_id}</Link>
                  </>
                ) : null}
                {s.folio ? <span className="small subtle"> · folio {s.folio}</span> : null}
                {s.lots_consumed.length ? <span className="small subtle"> · oldest lots first ({s.lots_consumed.length})</span> : null}
                {s.numbers.map((n) => (
                  <span key={n.slot}>
                    {" "}
                    · {humanise(n.slot)} <ExplainedNumber item={asExplained(n)} onExplain={onExplain} />
                  </span>
                ))}
              </li>
            ))}
          </ol>
        </Section>
      ) : null}
      {card.abstentions.length ? (
        <Section title="Missing inputs">
          <ul aria-label="Missing inputs">
            {card.abstentions.map((a) => (
              <li key={`${a.code}-${a.missing_input}`}>
                <strong>{humanise(a.missing_input)}</strong> <span className="small subtle mono">({a.code})</span>: {a.how_to_fix}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <details className="action-card__why">
        <summary>
          Why: Rule <code>{card.why.rule_ref}</code>
        </summary>
        {card.why.parameters.length ? (
          <ul aria-label="Rule parameters">
            {card.why.parameters.map((p) => (
              <li key={p.name}>{parameterLine(p)}</li>
            ))}
          </ul>
        ) : (
          <p className="small subtle">This rule has no user-set parameters.</p>
        )}
        {card.numbers.length + stepNumbers.length ? (
          <ul aria-label="Numbers and sources">
            {[...card.numbers, ...stepNumbers].map((n, i) => (
              <NumberSources key={`${n.slot}-${i}`} n={n} onExplain={onExplain} />
            ))}
          </ul>
        ) : null}
        <p className="small subtle mono">
          template {card.template_id} · data as of {dateLabel(card.as_of)}
        </p>
      </details>
      {canLog ? <Decision card={card} snapshotId={snapshotId} /> : null}
      {!canLog && card.decision ? (
        <p className="action-card__done small" role="status">
          You marked this done on {utcStamp(card.decision.decided_at)}. {casLine(card.decision)}
        </p>
      ) : null}
    </article>
  );
}
