// Goals (C02, PLAN.md wave 2): each goal with its amount, date, loss limit in ₹ and recovery time, shown under the
// worst-falls history so the limit is set against crashes, never against returns. The second view, "Return-target
// feasibility", is the ONLY place a return aim appears, and only as a historical frequency from POST /api/feasibility
// (engine/feasibility.py). The aim never raises equity: the loss limit sets equity (PLAN §2.2, design-risk-first §11).
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { compareDecimals, dateLabel, inr, percentToFraction, shiftPoint } from "../lib/format";
import type { FeasibilityIn, FeasibilityResponse } from "../lib/types";
import {
  fallLabel,
  recoveryText,
  stressBasis,
  type GoalUpdate,
  type GoalView,
  type GoalsView,
  type StressHistory,
} from "../lib/types-goals";
import { useApi } from "../lib/useApi";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorState, Loading } from "../components/States";

const DECIMAL = /^\d+(\.\d+)?$/;
const INT = /^\d+$/;
const HORIZONS = [1, 3, 5] as const;
type Horizon = (typeof HORIZONS)[number];
const money = (t: string) => t.replace(/[,\s₹]/g, "");

function CrashHistory({ history }: { history: StressHistory }) {
  return (
    <section aria-labelledby="goals-history-title">
      <h2 id="goals-history-title">Worst falls in the available history</h2>
      <div className="table-wrap">
        <table className="table table--compact" aria-labelledby="goals-history-title">
          <thead>
            <tr>
              <th scope="col">Kind of holding</th>
              <th scope="col" className="num">Worst fall</th>
              <th scope="col">Episode</th>
              <th scope="col">Time to recover</th>
              <th scope="col">Basis</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {history.rows.map((r) => (
              <tr key={r.risk_class}>
                <th scope="row">{r.label}</th>
                <td className="num">{r.outcome === "PASS" && r.stress ? fallLabel(r.stress) : "—"}</td>
                <td>{r.episode ?? "—"}{r.back_calculated ? " (back-calculated index history)" : ""}</td>
                <td>{recoveryText(r)}</td>
                <td className="small">{stressBasis(r)}</td>
                <td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">{history.caveat}</p>
    </section>
  );
}

const shown = (v: string | null) => (v ? inr(v, { paise: false }) : "not set");

function GoalEditor({ goal, onSaved, onCancel }: { goal: GoalView; onSaved: () => void; onCancel: () => void }) {
  const [name, setName] = useState(goal.name);
  const [amount, setAmount] = useState(goal.target_amount ?? "");
  const [date, setDate] = useState(goal.target_date ?? "");
  const [loss, setLoss] = useState(goal.loss_budget_inr ?? "");
  const [recovery, setRecovery] = useState(goal.recovery_months === null ? "" : String(goal.recovery_months));
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const id = `goal-${goal.goal_id}`;
  const nameRef = useRef<HTMLInputElement>(null);
  // The Edit button that opened the editor is gone: start the user at the first field (WCAG 2.4.3).
  useEffect(() => nameRef.current?.focus(), []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const bad = (t: string) => t.trim() !== "" && !DECIMAL.test(money(t));
    const problems = [
      !name.trim() || name.trim().length > 120 ? "Goal name: 1 to 120 characters." : null,
      bad(amount) ? "Goal amount: digits only." : null,
      bad(loss) ? "Loss limit: digits only." : null,
      !bad(loss) && !bad(amount) && loss.trim() && amount.trim() && compareDecimals(money(loss), money(amount)) > 0
        ? "Loss limit cannot be more than the goal amount."
        : null,
      recovery.trim() && !INT.test(recovery.trim()) ? "Recovery time: whole months." : null,
    ].filter((x): x is string => x !== null);
    // The PUT replaces the whole goal. A view without these keys gives no stored value to send back, and sending
    // nothing (or null) would erase them server-side: refuse rather than guess.
    if (goal.objective === undefined || goal.h_safe_years === undefined)
      problems.push("this goal was loaded without its objective or safe-horizon years; reload the page and try again.");
    if (problems.length) {
      setProblem(`Not saved: ${problems.join(" ")}`);
      return;
    }
    const body: GoalUpdate = {
      name: name.trim(),
      priority: goal.priority,
      target_amount: amount.trim() ? money(amount) : null,
      target_date: date || null,
      // Not editable here, but the PUT replaces the whole goal: send the stored values back so they are not erased.
      objective: goal.objective ?? null,
      loss_budget_inr: loss.trim() ? money(loss) : null,
      recovery_months: recovery.trim() ? Number.parseInt(recovery, 10) : null,
      h_safe_years: goal.h_safe_years ?? null,
    };
    setPending(true);
    setProblem(null);
    try {
      await api<GoalView>(`/api/goals/${encodeURIComponent(goal.goal_id)}`, { method: "PUT", body });
      onSaved();
    } catch (ex) {
      setProblem(`Not saved (${ex instanceof ApiError ? ex.code : "REQUEST_FAILED"}).`);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <div className="field">
        <label htmlFor={`${id}-name`}>Goal name</label>
        <input ref={nameRef} id={`${id}-name`} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-amount`}>Goal amount (₹)</label>
        <span className="money">
          <input id={`${id}-amount`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </span>
      </div>
      <div className="field">
        <label htmlFor={`${id}-date`}>Goal date</label>
        <input id={`${id}-date`} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-loss`}>Largest fall in ₹ you would sit through without selling</label>
        <span className="money">
          <input id={`${id}-loss`} inputMode="decimal" value={loss} onChange={(e) => setLoss(e.target.value)} />
        </span>
        <div className="hint">Set it against the worst falls listed above. It is the one input that sets this goal&apos;s equity.</div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-recovery`}>Longest you would wait for a recovery (months)</label>
        <input id={`${id}-recovery`} inputMode="numeric" value={recovery} onChange={(e) => setRecovery(e.target.value)} />
      </div>
      {problem ? (
        <p role="alert" className="callout callout--stale">
          {problem}
        </p>
      ) : null}
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={pending}>
          {pending ? "Saving…" : "Save goal"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** The id of a goal card's heading (focusable with tabIndex -1). */
const goalTitleId = (goalId: string) => `goal-${goalId}-title`;

type FocusTarget = "edit" | "delete" | "yes" | null;

function GoalCard({ goal, onChanged, onRemoved }: { goal: GoalView; onChanged: () => void; onRemoved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const titleId = goalTitleId(goal.goal_id);
  const editBtn = useRef<HTMLButtonElement>(null);
  const deleteBtn = useRef<HTMLButtonElement>(null);
  const yesBtn = useRef<HTMLButtonElement>(null);
  // Each of these controls removes the focused one (Edit, Delete, Keep, Cancel, Save): say where focus goes next, and
  // move it there once the new controls are on screen, so it never falls back to <body> (WCAG 2.4.3).
  const focusNext = useRef<FocusTarget>(null);
  useEffect(() => {
    const target = focusNext.current;
    focusNext.current = null;
    if (target === "edit") editBtn.current?.focus();
    else if (target === "delete") deleteBtn.current?.focus();
    else if (target === "yes") yesBtn.current?.focus();
  }, [editing, confirming]);

  async function remove() {
    setProblem(null);
    try {
      await api(`/api/goals/${encodeURIComponent(goal.goal_id)}`, { method: "DELETE" });
      onRemoved();
      onChanged();
    } catch (ex) {
      setProblem(`Not deleted (${ex instanceof ApiError ? ex.code : "REQUEST_FAILED"}).`);
    }
  }

  return (
    <section className="card" aria-labelledby={titleId}>
      <h3 id={titleId} tabIndex={-1}>
        {goal.name}
      </h3>
      {goal.outcome === "ABSTAIN" ? (
        <div className="callout callout--warn">
          <strong>ABSTAIN</strong>
          <ul>
            {goal.abstentions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {editing ? (
        <GoalEditor
          goal={goal}
          onCancel={() => {
            focusNext.current = "edit";
            setEditing(false);
          }}
          onSaved={() => {
            focusNext.current = "edit";
            setEditing(false);
            onChanged();
          }}
        />
      ) : (
        <>
          <dl className="kv">
            <dt>Amount</dt>
            <dd>{shown(goal.target_amount)}</dd>
            <dt>Date</dt>
            <dd>{goal.target_date ? dateLabel(goal.target_date) : "not set"}</dd>
            <dt>Loss limit</dt>
            <dd>{shown(goal.loss_budget_inr)}</dd>
            <dt>Recovery time</dt>
            <dd>{goal.recovery_months === null ? "not set" : `${goal.recovery_months} months`}</dd>
            <dt>Holdings mapped</dt>
            <dd>{goal.holdings.length ? goal.holdings.map((h) => h.name).join(", ") : "none"}</dd>
          </dl>
          <div className="row">
            <button ref={editBtn} type="button" className="btn" onClick={() => setEditing(true)}>
              Edit
            </button>
            {confirming ? (
              <>
                <button ref={yesBtn} type="button" className="btn btn--danger" onClick={remove}>
                  Yes, delete “{goal.name}”
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    focusNext.current = "delete";
                    setConfirming(false);
                  }}
                >
                  Keep it
                </button>
                <span className="hint">Its holdings become Unassigned; the decision log keeps its rows.</span>
              </>
            ) : (
              <button
                ref={deleteBtn}
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  focusNext.current = "yes";
                  setConfirming(true);
                }}
              >
                Delete
              </button>
            )}
          </div>
        </>
      )}
      {problem ? <p role="alert">{problem}</p> : null}
    </section>
  );
}

/** Whole years from `asOf` to `date` (ISO strings, no clock). */
function wholeYears(asOf: string, date: string): number {
  const [y1, m1, d1] = asOf.split("-").map(Number) as [number, number, number];
  const [y2, m2, d2] = date.split("-").map(Number) as [number, number, number];
  return y2 - y1 - (m2 < m1 || (m2 === m1 && d2 < d1) ? 1 : 0);
}

function defaultHorizon(asOf: string, goal: GoalView | undefined): Horizon {
  if (!goal?.target_date) return 5;
  const years = wholeYears(asOf, goal.target_date);
  return [...HORIZONS].reverse().find((h) => h <= years) ?? 1;
}

function FrequencyResult({ aim, horizon, res }: { aim: string; horizon: number; res: FeasibilityResponse }) {
  return (
    <div className="card">
      <h3>
        {aim} % a year over {horizon}-year windows
      </h3>
      {res.status === "REFUSED" || !res.reached_target ? (
        <p>REFUSED: {res.refusal?.reason ?? "the history is not sufficient for this check."}</p>
      ) : (
        <>
          <p>
            Reached in <strong>{res.reached_target.display}</strong> ({res.frequency_label}) of {res.instrument.name}&apos;s history to {dateLabel(res.as_of)}.
          </p>
          {res.low_evidence ? <p className="callout callout--warn">LOW EVIDENCE: {res.low_evidence_note ?? "few independent periods."}</p> : null}
        </>
      )}
      {res.caveats?.length ? (
        <ul className="small">
          {res.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      ) : null}
      <p className="hint">{res.disclaimer}</p>
    </div>
  );
}

function Feasibility({ view }: { view: GoalsView }) {
  const [goalId, setGoalId] = useState(view.goals[0]?.goal_id ?? "");
  const goal = view.goals.find((g) => g.goal_id === goalId);
  const [instrument, setInstrument] = useState(goal?.holdings[0]?.instrument_id ?? "");
  const [horizon, setHorizon] = useState<Horizon>(() => defaultHorizon(view.as_of, goal));
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [results, setResults] = useState<{ aim: string; horizon: number; res: FeasibilityResponse }[] | null>(null);

  useEffect(() => {
    setInstrument(goal?.holdings[0]?.instrument_id ?? "");
    setHorizon(defaultHorizon(view.as_of, goal));
    setResults(null);
  }, [goal, view.as_of]);

  async function check(e: FormEvent) {
    e.preventDefault();
    const a = percentToFraction(from);
    const b = percentToFraction(to);
    if (a === null || a === "invalid" || b === "invalid" || (b !== null && compareDecimals(b, a) < 0)) {
      setProblem("Enter the aim as numbers only, for example 12 to 15, with the second not below the first.");
      return;
    }
    if (compareDecimals(b ?? a, "1") > 0) {
      setProblem("The aim can be at most 100 % a year.");
      return;
    }
    setProblem(null);
    const aims = b === null || compareDecimals(a, b) === 0 ? [a] : [a, b];
    setPending(true);
    try {
      const out = await Promise.all(
        aims.map((t) => {
          const body: FeasibilityIn = { instrument_id: instrument, target_annual: t, horizon_years: horizon, mode: "CAGR" };
          return api<FeasibilityResponse>("/api/feasibility", { method: "POST", body });
        }),
      );
      setResults(out.map((res, i) => ({ aim: shiftPoint(aims[i]!, 2), horizon, res })));
    } catch (ex) {
      setResults(null);
      setProblem(`The check failed (${ex instanceof ApiError ? ex.code : "REQUEST_FAILED"}). No figure is shown rather than a possibly wrong one.`);
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="feas-title">
      <h2 id="feas-title">Return-target feasibility</h2>
      <p>
        A return aim appears here only as a <strong>historical frequency</strong>: how many past windows of a holding&apos;s
        history reached it. It is not a forecast, and it never raises equity: your loss limit sets equity.
      </p>
      {view.goals.length === 0 ? (
        <Empty title="No goals yet">
          <Link to="/onboarding">Run setup</Link>
        </Empty>
      ) : (
        <form onSubmit={check} noValidate className="card">
          <div className="field">
            <label htmlFor="feas-goal">Goal</label>
            <select id="feas-goal" value={goalId} onChange={(e) => setGoalId(e.target.value)}>
              {view.goals.map((g) => (
                <option key={g.goal_id} value={g.goal_id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>
          {!goal || goal.holdings.length === 0 ? (
            <p className="callout callout--warn">
              ABSTAIN: no holding is mapped to “{goal?.name ?? "this goal"}”. Import a CAS or map a holding to this goal first.
            </p>
          ) : (
            <>
              <div className="field">
                <label htmlFor="feas-holding">Holding</label>
                <select id="feas-holding" value={instrument} onChange={(e) => setInstrument(e.target.value)}>
                  {goal.holdings.map((h) => (
                    <option key={`${h.instrument_id}/${h.folio}`} value={h.instrument_id}>
                      {h.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="feas-horizon">Window length (years)</label>
                <select id="feas-horizon" value={horizon} onChange={(e) => setHorizon(Number(e.target.value) as Horizon)}>
                  {HORIZONS.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="feas-from">Aim from (% a year)</label>
                <span className="pct">
                  <input id="feas-from" inputMode="decimal" value={from} onChange={(e) => setFrom(e.target.value)} />
                </span>
              </div>
              <div className="field">
                <label htmlFor="feas-to">Aim to (% a year)</label>
                <span className="pct">
                  <input id="feas-to" inputMode="decimal" value={to} onChange={(e) => setTo(e.target.value)} />
                </span>
                <div className="hint">Optional. Leave empty to check a single figure.</div>
              </div>
              {problem ? (
                <p role="alert" className="callout callout--stale">
                  {problem}
                </p>
              ) : null}
              <button type="submit" className="btn btn--primary" disabled={pending || !instrument}>
                {pending ? "Checking…" : "Check history"}
              </button>
            </>
          )}
        </form>
      )}
      {pending ? <Loading label="Checking history" /> : null}
      {results ? (
        <section aria-label="Historical frequency">
          {results.map((r) => (
            <FrequencyResult key={r.aim} aim={r.aim} horizon={r.horizon} res={r.res} />
          ))}
        </section>
      ) : null}
    </section>
  );
}

const VIEWS = [
  ["goals", "Goals and loss limits"],
  ["feasibility", "Return-target feasibility"],
] as const;
type ViewKey = (typeof VIEWS)[number][0];

export default function Goals() {
  const [params, setParams] = useSearchParams();
  const view: ViewKey = params.get("view") === "feasibility" ? "feasibility" : "goals";
  const data = useApi<GoalsView>("/api/goals");
  // Keep the last good overview on screen while a reload after Save or Delete is in flight, so the goal cards stay
  // mounted and keyboard focus is kept (useApi clears its data on reload). An error still replaces it.
  const last = useRef<GoalsView | null>(null);
  if (data.data) last.current = data.data;
  const overview = data.data ?? (data.loading ? last.current : null);
  const tabRefs = useRef<Partial<Record<ViewKey, HTMLButtonElement | null>>>({});
  const focusTab = useRef<ViewKey | null>(null);

  useEffect(() => {
    document.title = "Goals · Investment Intelligence Pro";
  }, []);
  useEffect(() => {
    if (focusTab.current === view) {
      focusTab.current = null;
      tabRefs.current[view]?.focus();
    }
  }, [view]);

  const select = (key: ViewKey) => setParams(key === "goals" ? {} : { view: key });
  // WAI-ARIA tabs pattern: arrow keys, Home and End move between tabs (roving tabindex; selection follows focus).
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = VIEWS.findIndex(([k]) => k === view);
    const n = VIEWS.length;
    const moves: Record<string, number> = { ArrowRight: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, Home: 0, End: n - 1 };
    const next = moves[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const key = VIEWS[next]![0];
    focusTab.current = key;
    select(key);
  };

  // After a delete the card is gone: move focus to the next goal (else the previous one, else the selected tab).
  const focusAfterRemove = (goalId: string) => {
    const goals = overview?.goals ?? [];
    const i = goals.findIndex((g) => g.goal_id === goalId);
    const neighbour = goals[i + 1] ?? goals[i - 1];
    const el = neighbour ? document.getElementById(goalTitleId(neighbour.goal_id)) : tabRefs.current.goals;
    el?.focus();
  };

  const tabs = (
    <div role="tablist" aria-label="Goals views" className="tabs">
      {VIEWS.map(([key, label]) => (
        <button
          key={key}
          ref={(el) => {
            tabRefs.current[key] = el;
          }}
          type="button"
          role="tab"
          id={`tab-${key}`}
          aria-selected={view === key}
          // Only the selected tab's panel is rendered, so only it is referenced.
          aria-controls={view === key ? `panel-${key}` : undefined}
          tabIndex={view === key ? 0 : -1}
          onClick={() => select(key)}
          onKeyDown={onTabKey}
        >
          {label}
        </button>
      ))}
    </div>
  );

  let body;
  if (data.error || (!data.loading && !data.data)) body = <ErrorState error={data.error} retry={data.reload} />;
  else if (!overview) body = <Loading label="Loading your goals" />;
  else if (view === "feasibility") body = <Feasibility view={overview} />;
  else
    body = (
      <>
        <CrashHistory history={overview.stress_history} />
        {overview.missing.length ? (
          <p className="callout callout--warn">Missing, so the parts that need it abstain: {overview.missing.join("; ")}.</p>
        ) : null}
        {overview.goals.length === 0 ? (
          <Empty title="No goals yet">
            <p>
              Goals come from setup: one CAS upload and about six answers. <Link to="/onboarding">Run setup</Link>
            </p>
          </Empty>
        ) : (
          overview.goals.map((g) => (
            <GoalCard key={g.goal_id} goal={g} onChanged={data.reload} onRemoved={() => focusAfterRemove(g.goal_id)} />
          ))
        )}
        <p>
          <Link to="/onboarding">Review setup answers</Link>
        </p>
      </>
    );

  return (
    <>
      <PageHeader title="Goals" purpose="Each goal's amount, date and loss limit in rupees. The loss limit, set against past crashes, decides how much equity a goal may hold." />
      {tabs}
      <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
        {body}
      </div>
    </>
  );
}
