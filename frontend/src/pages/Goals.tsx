// Goals (C02, PLAN.md wave 2): each goal with its amount, date, loss limit in ₹ and recovery time, shown under the
// worst-falls history so the limit is set against crashes, never against returns. The second view, "Return-target
// feasibility", is the ONLY place a return aim appears, and only as a historical frequency from POST /api/feasibility
// (engine/feasibility.py). The aim never raises equity: the loss limit sets equity (PLAN §2.2, design-risk-first §11).
import { useEffect, useState, type FormEvent } from "react";
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
    if (problems.length) {
      setProblem(`Not saved: ${problems.join(" ")}`);
      return;
    }
    const body: GoalUpdate = {
      name: name.trim(),
      priority: goal.priority,
      target_amount: amount.trim() ? money(amount) : null,
      target_date: date || null,
      loss_budget_inr: loss.trim() ? money(loss) : null,
      recovery_months: recovery.trim() ? Number.parseInt(recovery, 10) : null,
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
        <input id={`${id}-name`} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
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

function GoalCard({ goal, onChanged }: { goal: GoalView; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const titleId = `goal-${goal.goal_id}-title`;

  async function remove() {
    setProblem(null);
    try {
      await api(`/api/goals/${encodeURIComponent(goal.goal_id)}`, { method: "DELETE" });
      onChanged();
    } catch (ex) {
      setProblem(`Not deleted (${ex instanceof ApiError ? ex.code : "REQUEST_FAILED"}).`);
    }
  }

  return (
    <section className="card" aria-labelledby={titleId}>
      <h3 id={titleId}>{goal.name}</h3>
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
          onCancel={() => setEditing(false)}
          onSaved={() => {
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
            <button type="button" className="btn" onClick={() => setEditing(true)}>
              Edit
            </button>
            {confirming ? (
              <>
                <button type="button" className="btn btn--danger" onClick={remove}>
                  Yes, delete “{goal.name}”
                </button>
                <button type="button" className="btn" onClick={() => setConfirming(false)}>
                  Keep it
                </button>
                <span className="hint">Its holdings become Unassigned; the decision log keeps its rows.</span>
              </>
            ) : (
              <button type="button" className="btn btn--ghost" onClick={() => setConfirming(true)}>
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

export default function Goals() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "feasibility" ? "feasibility" : "goals";
  const data = useApi<GoalsView>("/api/goals");

  useEffect(() => {
    document.title = "Goals · Investment Intelligence Pro";
  }, []);

  const tabs = (
    <div role="tablist" aria-label="Goals views" className="row">
      {(
        [
          ["goals", "Goals and loss limits"],
          ["feasibility", "Return-target feasibility"],
        ] as const
      ).map(([key, label]) => (
        <button
          key={key}
          type="button"
          role="tab"
          id={`tab-${key}`}
          aria-selected={view === key}
          aria-controls={`panel-${key}`}
          className="btn btn--ghost"
          onClick={() => setParams(key === "goals" ? {} : { view: key })}
        >
          {label}
        </button>
      ))}
    </div>
  );

  let body;
  if (data.loading) body = <Loading label="Loading your goals" />;
  else if (data.error || !data.data) body = <ErrorState error={data.error} retry={data.reload} />;
  else if (view === "feasibility") body = <Feasibility view={data.data} />;
  else
    body = (
      <>
        <CrashHistory history={data.data.stress_history} />
        {data.data.missing.length ? (
          <p className="callout callout--warn">Missing, so the parts that need it abstain: {data.data.missing.join("; ")}.</p>
        ) : null}
        {data.data.goals.length === 0 ? (
          <Empty title="No goals yet">
            <p>
              Goals come from setup: one CAS upload and about six answers. <Link to="/onboarding">Run setup</Link>
            </p>
          </Empty>
        ) : (
          data.data.goals.map((g) => <GoalCard key={g.goal_id} goal={g} onChanged={data.reload} />)
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
