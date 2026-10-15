import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { DotPlot } from "../charts/DotPlot";
import { Loading } from "../components/States";
import { api } from "../lib/api";
import { compareDecimals, dateLabel, fractionToPercent, inr, pct, percentToFraction, roundHalfUp } from "../lib/format";
import { useProfile } from "../lib/profile";
import type {
  FeasibilityIn,
  FeasibilityResponse,
  ScenarioIn,
  ScenarioQuantity,
  ScenarioResponse,
  ScenarioResult,
  ShockKey,
  ShocksIn,
} from "../lib/types";
import {
  AmountDateFields,
  AnalysisErrorState,
  ContextLine,
  Ex,
  FixtureCallout,
  RefusalNote,
  SinglePicker,
  WHICH,
  amountDateProblems,
  useExplain,
  type OnExplain,
  type Picked,
} from "./Compare";

type Tab = "lab" | "feasibility";

const fromUrl = (id: string | null): Picked | null => (id ? { instrument_id: id, name: null, fixture: null } : null);

export default function Scenarios() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "feasibility" ? "feasibility" : "lab";
  const id = params.get("id");
  const setTab = (t: Tab) => {
    const p = new URLSearchParams(params);
    p.set("tab", t);
    setParams(p);
  };
  return (
    <section>
      <h1>Scenarios</h1>
      <div className="tabs" role="tablist" aria-label="Scenario tools">
        <button type="button" role="tab" id="tab-lab" aria-selected={tab === "lab"} aria-controls="panel-lab" onClick={() => setTab("lab")}>
          Scenario lab
        </button>
        <button
          type="button"
          role="tab"
          id="tab-feasibility"
          aria-selected={tab === "feasibility"}
          aria-controls="panel-feasibility"
          onClick={() => setTab("feasibility")}
        >
          Return-target feasibility
        </button>
      </div>
      {tab === "lab" ? (
        <div role="tabpanel" id="panel-lab" aria-labelledby="tab-lab">
          <ScenarioLab initial={fromUrl(id)} />
        </div>
      ) : (
        <div role="tabpanel" id="panel-feasibility" aria-labelledby="tab-feasibility">
          <Feasibility initial={fromUrl(id)} />
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ scenario lab

interface ShockDef {
  key: ShockKey;
  label: string;
  hint: string;
  min: string;
  max: string;
  minInclusive: boolean;
  integer?: boolean;
}

// Bounds mirror backend api/routes_analysis.py ShocksIn (validation only; the engine re-checks every value).
const SHOCKS: ShockDef[] = [
  { key: "rate_bp", label: "Interest-rate change (basis points)", hint: "e.g. 100 for +1 percentage point; −1000 to 1000", min: "-1000", max: "1000", minInclusive: true },
  { key: "spread_bp", label: "Credit-spread change (basis points)", hint: "−1000 to 2000", min: "-1000", max: "2000", minInclusive: true },
  { key: "equity_pct", label: "Equity fall (%)", hint: "0 or negative, e.g. -20 for a 20 % fall; −100 to 0", min: "-100", max: "0", minInclusive: true },
  { key: "inflation_pct", label: "Inflation change (percentage points)", hint: "−20 to 50", min: "-20", max: "50", minInclusive: true },
  {
    key: "exit_before_maturity_days",
    label: "Exit early after (days)",
    hint: "whole days from today, 1 to 3650",
    min: "1",
    max: "3650",
    minInclusive: true,
    integer: true,
  },
  { key: "reinvestment_rate", label: "Reinvestment rate (fraction)", hint: "e.g. 0.05 for 5 % a year; above −1, at most 1", min: "-1", max: "1", minInclusive: false },
];

const SHOCK_LABEL: Record<string, string> = Object.fromEntries(SHOCKS.map((s) => [s.key, s.label]));
const SIGNED_DECIMAL = /^-?\d{1,6}(\.\d{1,8})?$/;

/** Validate the shock text fields; returns the request shocks (decimal strings; days as a whole number) and problems. */
export function shocksFrom(text: Record<ShockKey, string>): { shocks: ShocksIn; problems: Record<string, string> } {
  const shocks: ShocksIn = {};
  const problems: Record<string, string> = {};
  for (const s of SHOCKS) {
    const raw = (text[s.key] ?? "").trim().replace(/^−/, "-");
    if (!raw) continue;
    const ok = s.integer ? /^\d{1,4}$/.test(raw) : SIGNED_DECIMAL.test(raw);
    if (!ok) {
      problems[s.key] = s.integer ? "Enter a whole number of days." : "Enter a plain decimal number, e.g. 100 or -12.5.";
      continue;
    }
    const lowOk = s.minInclusive ? compareDecimals(raw, s.min) >= 0 : compareDecimals(raw, s.min) > 0;
    if (!lowOk || compareDecimals(raw, s.max) > 0) {
      problems[s.key] = `Out of range: ${s.hint}.`;
      continue;
    }
    if (s.key === "exit_before_maturity_days") shocks.exit_before_maturity_days = Number.parseInt(raw, 10);
    else shocks[s.key] = raw;
  }
  return { shocks, problems };
}

/** Display an engine scenario quantity without raw internal precision. */
export function quantityText(q: ScenarioQuantity): string {
  if (q.unit === "INR") return inr(q.value);
  if (q.unit === "fraction") return pct(q.value, 2);
  if (q.unit === "days") return `${q.value} days`;
  return roundHalfUp(q.value, 4);
}

const WHICH_LABEL: Record<string, string> = { q05: "Low end (q05)", q50: "Middle (q50)", q95: "High end (q95)", value: "Value" };
const SCENARIO_LABEL: Record<string, string> = {
  "stress scenario": "Stress scenario",
  "illustrative downside": "Illustrative downside scenario",
};

const EMPTY_SHOCKS: Record<ShockKey, string> = {
  rate_bp: "",
  spread_bp: "",
  equity_pct: "",
  inflation_pct: "",
  exit_before_maturity_days: "",
  reinvestment_rate: "",
};

function ScenarioLab({ initial }: { initial: Picked | null }) {
  const [selected, setSelected] = useState<Picked | null>(initial);
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [text, setText] = useState<Record<ShockKey, string>>(EMPTY_SHOCKS);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const { open, drawer } = useExplain();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const { shocks, problems: p } = shocksFrom(text);
    const all = { ...p, ...amountDateProblems(amount, date) };
    if (!selected) all.instrument = "Pick an instrument first.";
    if (Object.keys(shocks).length === 0 && Object.keys(p).length === 0) all._ = "Enter at least one shock.";
    setProblems(all);
    if (Object.keys(all).length || !selected) return;
    const body: ScenarioIn = { instrument_id: selected.instrument_id, shocks };
    if (amount.trim()) body.amount = amount.trim();
    if (date) body.withdrawal_date = date;
    setPending(true);
    setError(null);
    try {
      setResult(await api<ScenarioResponse>("/api/scenario", { method: "POST", body }));
    } catch (err) {
      setResult(null);
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <p className="small subtle">
        Apply one hypothetical shock at a time to one instrument and see proceeds before and after. Shocks are stress scenarios, not forecasts,
        and are not weighted by how often they happened. Impacts are shown <strong>before tax</strong>.
      </p>
      <form className="card" onSubmit={submit} noValidate>
        <SinglePicker idPrefix="scn" selected={selected} onChange={setSelected} />
        {problems.instrument ? (
          <div className="field-error" role="alert">
            {problems.instrument}
          </div>
        ) : null}
        <AmountDateFields idPrefix="scn" amount={amount} date={date} onAmount={setAmount} onDate={setDate} errors={problems} />
        <fieldset>
          <legend>Shocks (leave empty to skip; each is applied on its own)</legend>
          <div className="grid grid--3">
            {SHOCKS.map((s) => (
              <div className="field" key={s.key}>
                <label htmlFor={`shock-${s.key}`}>{s.label}</label>
                <input
                  id={`shock-${s.key}`}
                  inputMode={s.integer ? "numeric" : "decimal"}
                  value={text[s.key]}
                  onChange={(e) => setText((t) => ({ ...t, [s.key]: e.target.value }))}
                  aria-invalid={Boolean(problems[s.key])}
                  aria-describedby={`shock-${s.key}-hint`}
                />
                <div id={`shock-${s.key}-hint`} className="hint">
                  {s.hint}
                </div>
                {problems[s.key] ? (
                  <div className="field-error" role="alert">
                    {problems[s.key]}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </fieldset>
        {problems._ ? (
          <div className="field-error" role="alert">
            {problems._}
          </div>
        ) : null}
        <button type="submit" className="btn btn--primary" disabled={pending}>
          {pending ? "Running…" : "Run scenario"}
        </button>
      </form>
      {pending ? <Loading label="Running scenario" /> : error ? <AnalysisErrorState error={error} /> : result ? <ScenarioView res={result} onExplain={open} /> : null}
      {drawer}
    </div>
  );
}

function ScenarioView({ res, onExplain }: { res: ScenarioResponse; onExplain: OnExplain }) {
  const echoed = Object.entries(res.request.shocks).filter((e): e is [string, string] => e[1] !== null);
  return (
    <div className={res.fixture ? "fixture-zone" : undefined}>
      <FixtureCallout fixture={res.fixture} />
      <h2>
        {res.instrument.name} <span className="small subtle mono">{res.instrument.instrument_id}</span>
      </h2>
      <ContextLine ctx={res.context} />
      <h3>Inputs the engine used</h3>
      <ul className="small" aria-label="Echoed shock inputs">
        {echoed.map(([k, v]) => (
          <li key={k}>
            {SHOCK_LABEL[k] ?? k}: <span className="mono">{v}</span>
          </li>
        ))}
      </ul>
      <p className="small subtle">
        Each shock is applied on its own (not combined). Shocks are hypothetical stress scenarios, not forecasts. Impacts are before tax.
      </p>
      {res.status === "NOT_EVALUABLE" ? (
        <div className="callout callout--warn" role="note">
          <strong>This instrument could not be evaluated, so no scenario was applied.</strong>
          <ul>
            {(res.reasons ?? []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {res.base ? (
        <>
          <h3>Base (no shock)</h3>
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Quantile</th>
                  <th scope="col" className="num">
                    Net proceeds (after tax)
                  </th>
                  <th scope="col" className="num">
                    Proceeds before tax (shocks apply to this)
                  </th>
                </tr>
              </thead>
              <tbody>
                {WHICH.map((w) => (
                  <tr key={w}>
                    <th scope="row">{w === "q05" ? "Illustrative downside scenario (q05)" : WHICH_LABEL[w]}</th>
                    <td className="num">
                      <Ex item={res.base?.net_proceeds[w]} onExplain={onExplain} />
                    </td>
                    <td className="num">
                      <Ex item={res.base?.proceeds_before_tax[w]} onExplain={onExplain} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      {res.results.map((r) => (
        <ShockResult key={r.shock} r={r} onExplain={onExplain} />
      ))}
      <p className="small subtle disclosure">{res.disclaimer}</p>
    </div>
  );
}

function ShockResult({ r, onExplain }: { r: ScenarioResult; onExplain: OnExplain }) {
  const title = `${SHOCK_LABEL[r.shock] ?? r.shock}: ${r.input}`;
  if (r.status === "not_applicable")
    return (
      <div className="card shock-na" role="note">
        <h3>{title}</h3>
        <p>
          <strong>Not applicable:</strong> {(r.reason)}
        </p>
        <p className="small subtle">No impact is shown, because none was computed.</p>
      </div>
    );
  return (
    <div className="card">
      <h3>{title}</h3>
      <p className="small">
        <strong>{SCENARIO_LABEL[r.label] ?? r.label}</strong> · measure: {r.measure}
        {r.approximate ? " · approximate" : ""} · not weighted by how often it happened
      </p>
      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">Quantile</th>
              <th scope="col" className="num">
                Before
              </th>
              <th scope="col" className="num">
                After
              </th>
              <th scope="col" className="num">
                Impact (before tax)
              </th>
              <th scope="col" className="num">
                Impact as share of before
              </th>
            </tr>
          </thead>
          <tbody>
            {r.values.map((v) => (
              <tr key={v.which}>
                <th scope="row">{WHICH_LABEL[v.which] ?? v.which}</th>
                <td className="num">
                  <Ex item={v.before} onExplain={onExplain} />
                </td>
                <td className="num">
                  <Ex item={v.after} onExplain={onExplain} />
                </td>
                <td className="num">
                  <Ex item={v.impact} onExplain={onExplain} />
                </td>
                <td className="num">
                  <Ex item={v.impact_fraction} onExplain={onExplain} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="small">
        <summary>Engine inputs and caveats ({r.scenario_id})</summary>
        <ul>
          {r.inputs.map((q) => (
            <li key={q.name}>
              {q.name.replace(/_/g, " ")}: <span className="num">{quantityText(q)}</span>
            </li>
          ))}
        </ul>
        {r.caveats.length ? <p>Caveats: {r.caveats.map((c) => c.replace(/_/g, " ").toLowerCase()).join(" · ")}</p> : null}
      </details>
    </div>
  );
}

// ------------------------------------------------------------------ return-target feasibility

const HORIZONS = [1, 3, 5] as const;
type Horizon = (typeof HORIZONS)[number];

/** Default horizon from the profile's withdrawal horizon (whole years, rounded down, limited to 1/3/5). */
function defaultHorizon(days: number | null | undefined): Horizon {
  if (!days) return 1;
  if (days >= 5 * 365) return 5;
  if (days >= 3 * 365) return 3;
  return 1;
}

/** Validate a target typed as a percentage; returns the fraction string the API needs, or a problem. */
export function targetFraction(text: string): { fraction: string | null; problem: string | null } {
  const f = percentToFraction(text);
  if (f === null) return { fraction: null, problem: "Enter a target annual return in %, e.g. 20." };
  if (f === "invalid") return { fraction: null, problem: "Enter a plain number of percent, e.g. 20 or 22.5 (no % sign)." };
  if (compareDecimals(f, "1") > 0) return { fraction: null, problem: "The target can be at most 100 % a year." };
  return { fraction: f, problem: null };
}

function Feasibility({ initial }: { initial: Picked | null }) {
  const { status } = useProfile();
  const aspiration = status?.profile.return_aspiration ?? null;
  const [selected, setSelected] = useState<Picked | null>(initial);
  const [target, setTarget] = useState(() => fractionToPercent(aspiration));
  const [horizon, setHorizon] = useState<Horizon>(() => defaultHorizon(status?.horizon_days));
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [result, setResult] = useState<FeasibilityResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const touched = useRef(false);
  const { open, drawer } = useExplain();

  // Pre-fill from the profile once it arrives, unless the user has already typed.
  useEffect(() => {
    if (touched.current) return;
    if (aspiration) setTarget(fractionToPercent(aspiration));
    if (status?.horizon_days) setHorizon(defaultHorizon(status.horizon_days));
  }, [aspiration, status?.horizon_days]);

  const parsed = targetFraction(target);
  const above30 = parsed.fraction !== null && compareDecimals(parsed.fraction, "0.3") > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const p: Record<string, string> = {};
    if (!selected) p.instrument = "Pick a mutual fund scheme first.";
    if (parsed.problem) p.target = parsed.problem;
    setProblems(p);
    if (Object.keys(p).length || !selected || !parsed.fraction) return;
    const body: FeasibilityIn = { instrument_id: selected.instrument_id, target_annual: parsed.fraction, horizon_years: horizon };
    setPending(true);
    setError(null);
    try {
      setResult(await api<FeasibilityResponse>("/api/feasibility", { method: "POST", body }));
    } catch (err) {
      setResult(null);
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <p className="small subtle">
        How often did this fund’s past {horizon}-year periods reach a target annual return, and what losses and falls came along the way? This
        is a <strong>historical frequency, not a forecast</strong>. It describes the past only and is not a suggestion to change how much risk
        you take.
      </p>
      <form className="card" onSubmit={submit} noValidate>
        <SinglePicker idPrefix="feas" selected={selected} onChange={setSelected} />
        {problems.instrument ? (
          <div className="field-error" role="alert">
            {problems.instrument}
          </div>
        ) : null}
        <div className="row">
          <div className="field">
            <label htmlFor="feas-target">Target annual return (%)</label>
            <input
              id="feas-target"
              inputMode="decimal"
              value={target}
              onChange={(e) => {
                touched.current = true;
                setTarget(e.target.value);
              }}
              aria-invalid={Boolean(problems.target)}
              aria-describedby="feas-target-hint"
            />
            <div id="feas-target-hint" className="hint">
              {aspiration ? "Pre-filled from the aspiration in your profile." : "Per year, compounded (e.g. 20)."}
            </div>
            {problems.target ? (
              <div className="field-error" role="alert">
                {problems.target}
              </div>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="feas-horizon">Horizon</label>
            <select
              id="feas-horizon"
              value={horizon}
              onChange={(e) => {
                touched.current = true;
                setHorizon(Number(e.target.value) as Horizon);
              }}
            >
              {HORIZONS.map((h) => (
                <option key={h} value={h}>
                  {h} year{h === 1 ? "" : "s"}
                </option>
              ))}
            </select>
          </div>
        </div>
        {above30 ? (
          <p className="small callout" role="note">
            Arithmetic, not a forecast (research note §2.10): money compounding at 25 % a year is 3.05× after 5 years and 9.31× after 10. The best
            realised 10-year windows of major Indian equity indices were about 21.6–23.4 % a year.
          </p>
        ) : null}
        <button type="submit" className="btn btn--primary" disabled={pending}>
          {pending ? "Checking…" : "Show historical frequency"}
        </button>
      </form>
      {pending ? <Loading label="Checking history" /> : error ? <AnalysisErrorState error={error} /> : result ? <FeasibilityView res={result} onExplain={open} /> : null}
      {drawer}
    </div>
  );
}

const PCT_KEYS = ["p5", "p10", "p25", "p50", "p75", "p90", "p95"];

function FeasibilityView({ res, onExplain }: { res: FeasibilityResponse; onExplain: OnExplain }) {
  const target = res.dots?.target.display ?? pct(res.request.target_annual, 2, false);
  const h = res.request.horizon_years;
  const refused = res.status === "REFUSED" || Boolean(res.refusal);
  return (
    <div className={res.fixture ? "fixture-zone" : undefined}>
      <FixtureCallout fixture={res.fixture} />
      <h2>
        {res.instrument.name} <span className="small subtle">{res.instrument.category}</span>
      </h2>
      <p className="small">
        Target: <strong>{target} a year</strong> over {h} year{h === 1 ? "" : "s"} ({res.request.mode === "CAGR" ? "compound annual" : "every year"}) ·{" "}
        <strong>Historical frequency, not a forecast</strong> · {res.frequency_label}
      </p>
      {res.low_evidence ? (
        <div className="callout callout--warn" role="note">
          <strong>LOW EVIDENCE.</strong> {res.low_evidence_note ?? "Counts only, no percentages."}
        </div>
      ) : null}
      {refused && res.refusal ? (
        <div className="callout callout--warn" role="note">
          <p>
            <RefusalNote r={res.refusal} />
          </p>
          <p className="small">
            What would be needed: a longer stored NAV history for this scheme — at least {h + 1} years of daily NAVs and at least two independent{" "}
            {h}-year periods. Backfill longer history (Data health → ingestion), then check again.
          </p>
        </div>
      ) : null}
      {res.headline ? <p>{(res.headline)}</p> : null}

      {res.reached_target && res.loss ? (
        <div className="table-wrap">
          <table className="table table--compact">
            <caption className="sr-only">Counts over overlapping windows</caption>
            <thead>
              <tr>
                <th scope="col">Outcome over {h}-year windows</th>
                <th scope="col">Count</th>
                <th scope="col" className="num">
                  Historical frequency
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Reached {target} a year or more</th>
                <td>{res.reached_target.display}</td>
                <td className="num">
                  {res.reached_target.frequency ? <Ex item={res.reached_target.frequency} onExplain={onExplain} /> : <span className="subtle">counts only</span>}
                </td>
              </tr>
              <tr>
                <th scope="row">Lost money</th>
                <td>{res.loss.display}</td>
                <td className="num">
                  {res.loss.frequency ? <Ex item={res.loss.frequency} onExplain={onExplain} /> : <span className="subtle">counts only</span>}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}
      {res.independent_periods !== undefined ? (
        <p className="small">
          About <strong>{res.independent_periods}</strong> independent {h}-year period{res.independent_periods === 1 ? "" : "s"}
          {res.windows !== undefined ? ` behind ${res.windows} overlapping windows` : ""}
          {res.grid ? ` (month-end grid ${dateLabel(res.grid.start)} to ${dateLabel(res.grid.end)})` : ""}.
        </p>
      ) : null}

      {res.dots && !res.low_evidence ? (
        <>
          <h3>20 historical outcomes</h3>
          <DotPlot
            label={`Compound annual return of past ${h}-year windows`}
            quantiles={res.dots.values.map((d) => d.value)}
            displays={res.dots.values.map((d) => d.display)}
            target={{ value: res.dots.target.value, display: res.dots.target.display, label: `target ${res.dots.target.display}`, hits: res.dots.reached_target }}
          />
          <p className="small">{res.dots.reached_target_display} — historical frequency, not a forecast.</p>
        </>
      ) : res.dots && res.low_evidence ? (
        <p className="small subtle">Dot plot not shown: with LOW EVIDENCE only counts are shown.</p>
      ) : null}

      {res.percentiles ? (
        <>
          <h3>Range of past {h}-year compound annual returns</h3>
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  {PCT_KEYS.filter((k) => res.percentiles?.[k]).map((k) => (
                    <th key={k} scope="col" className="num">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {PCT_KEYS.filter((k) => res.percentiles?.[k]).map((k) => (
                    <td key={k} className="num">
                      <Ex item={res.percentiles?.[k]} onExplain={onExplain} />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {res.drawdown || res.full_history_drawdown ? <h3>Falls along the way</h3> : null}
      {res.drawdown ? (
        <>
          <div className="table-wrap">
            <table className="table table--compact">
              <caption className="small">Largest fall inside each {h}-year window (percentiles over all windows)</caption>
              <thead>
                <tr>
                  {PCT_KEYS.filter((k) => res.drawdown?.in_window_mdd[k]).map((k) => (
                    <th key={k} scope="col" className="num">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {PCT_KEYS.filter((k) => res.drawdown?.in_window_mdd[k]).map((k) => (
                    <td key={k} className="num">
                      <Ex item={res.drawdown?.in_window_mdd[k]} onExplain={onExplain} />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <dl className="kv">
            <dt>Deepest fall inside a window that reached the target</dt>
            <dd>
              {res.drawdown.worst_in_window_that_reached_target ? (
                <Ex item={res.drawdown.worst_in_window_that_reached_target} onExplain={onExplain} />
              ) : (
                <span className="subtle">no window reached the target</span>
              )}
            </dd>
            <dt>
              Median window’s low point{res.context_amount ? `, on ${res.context_amount.amount}` : ""}
              {res.context_amount?.illustrative ? " (illustrative amount)" : ""}
            </dt>
            <dd>{res.drawdown.median_mdd_inr ? <Ex item={res.drawdown.median_mdd_inr} onExplain={onExplain} /> : <span className="subtle">not computed</span>}</dd>
          </dl>
        </>
      ) : null}
      {res.full_history_drawdown ? (
        <dl className="kv">
          <dt>Full-history maximum drawdown</dt>
          <dd>
            <Ex item={res.full_history_drawdown.depth} onExplain={onExplain} /> — peak {dateLabel(res.full_history_drawdown.peak_date)}, low{" "}
            {dateLabel(res.full_history_drawdown.trough_date)},{" "}
            {res.full_history_drawdown.recovery_date
              ? `recovered ${dateLabel(res.full_history_drawdown.recovery_date)}`
              : res.full_history_drawdown.ongoing
                ? "not yet recovered (ongoing)"
                : "no recovery recorded"}
          </dd>
        </dl>
      ) : null}

      {res.banners?.length ? (
        <ul className="callout" aria-label="Banners">
          {res.banners.map((b) => (
            <li key={b}>{(b)}</li>
          ))}
        </ul>
      ) : null}
      {res.notes?.length ? <p className="small">{res.notes.join(" ")}</p> : null}
      {res.flags?.length ? <p className="small subtle">Flags: {res.flags.join(", ")}</p> : null}
      {res.caveats?.length ? (
        <details className="small" open>
          <summary>Caveats ({res.caveats.length})</summary>
          <ol>
            {res.caveats.map((c) => (
              <li key={c}>{(c)}</li>
            ))}
          </ol>
        </details>
      ) : null}
      <p className="small subtle disclosure">{res.disclaimer}</p>
    </div>
  );
}
