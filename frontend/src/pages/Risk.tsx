import { useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { useSearchParams } from "react-router-dom";
import { Loading } from "../components/States";
import { dateLabel, pct, roundHalfUp } from "../lib/format";
import type { AnalysisExplained, ForecastResponse, Refusal, RiskResponse, RiskVar } from "../lib/types";
import { useApi } from "../lib/useApi";
import {
  AnalysisErrorState,
  ContextLine,
  Ex,
  FixtureCallout,
  Metric,
  RefusalNote,
  SinglePicker,
  isRefusal,
  useExplain,
  type OnExplain,
  type Picked,
} from "./Compare";

const HORIZON_RE = /^\d{1,4}$/;

export default function Risk() {
  const [params, setParams] = useSearchParams();
  const id = params.get("id");
  const horizon = params.get("horizon_days") ?? "";
  const [selected, setSelected] = useState<Picked | null>(id ? { instrument_id: id, name: null, fixture: null } : null);
  const [horizonText, setHorizonText] = useState(horizon);
  const [horizonErr, setHorizonErr] = useState<string | null>(null);
  const { open, drawer } = useExplain();

  const setUrl = (nextId: string | null, h: string) => {
    const p = new URLSearchParams();
    if (nextId) p.set("id", nextId);
    if (h) p.set("horizon_days", h);
    setParams(p);
  };

  const risk = useApi<RiskResponse>(id ? `/api/risk/${encodeURIComponent(id)}` : null);
  const forecast = useApi<ForecastResponse>(
    id ? `/api/forecast/${encodeURIComponent(id)}${horizon ? `?horizon_days=${encodeURIComponent(horizon)}` : ""}` : null,
  );

  function applyHorizon(e: FormEvent) {
    e.preventDefault();
    const h = horizonText.trim();
    if (h && (!HORIZON_RE.test(h) || Number(h) < 1 || Number(h) > 3650)) {
      setHorizonErr("Enter a whole number of days from 1 to 3650, or leave empty for your profile horizon.");
      return;
    }
    setHorizonErr(null);
    setUrl(id, h);
  }

  return (
    <section>
      <PageHeader
        title="Risk"
        purpose={
          <>
            Past volatility, drawdowns and one-day loss measures for one mutual fund’s stored NAV history, and a historical scenario range. Gated metrics are refused in words, never shown as a number.
          </>
        }
      />
      <div className="card">
        <SinglePicker
          idPrefix="risk"
          selected={selected}
          onChange={(p) => {
            setSelected(p);
            setUrl(p?.instrument_id ?? null, horizon);
          }}
        />
        <form onSubmit={applyHorizon} noValidate className="row">
          <div className="field">
            <label htmlFor="risk-horizon">Scenario-range horizon in days (optional)</label>
            <input id="risk-horizon" inputMode="numeric" value={horizonText} onChange={(e) => setHorizonText(e.target.value)} aria-invalid={Boolean(horizonErr)} />
            <div className="hint">Empty: your profile horizon, else the illustrative 182 days.</div>
            {horizonErr ? (
              <div className="field-error" role="alert">
                {horizonErr}
              </div>
            ) : null}
          </div>
          <button type="submit" className="btn" disabled={!id}>
            Apply horizon
          </button>
        </form>
      </div>
      {!id ? (
        <p className="small subtle">Pick a mutual fund scheme to see its risk metrics. Risk metrics need a stored NAV series.</p>
      ) : (
        <>
          <h2>Risk metrics</h2>
          {risk.loading ? (
            <Loading label="Loading risk metrics" />
          ) : risk.error ? (
            <AnalysisErrorState error={risk.error} retry={risk.reload} />
          ) : risk.data ? (
            <RiskView res={risk.data} onExplain={open} />
          ) : null}
          <h2>Scenario range (not a forecast)</h2>
          {forecast.loading ? (
            <Loading label="Loading scenario range" />
          ) : forecast.error ? (
            <AnalysisErrorState error={forecast.error} retry={forecast.reload} />
          ) : forecast.data ? (
            <ForecastView res={forecast.data} onExplain={open} />
          ) : null}
        </>
      )}
      {drawer}
    </section>
  );
}

function VarRow({ label, m, onExplain }: { label: string; m: RiskVar; onExplain: OnExplain }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      {isRefusal(m) ? (
        <td colSpan={2}>
          <RefusalNote r={m} />
        </td>
      ) : (
        <>
          <td className="num">
            <Ex item={m} onExplain={onExplain} />
          </td>
          <td className="num">
            {m.value_inr ? <Ex item={m.value_inr} onExplain={onExplain} /> : <span className="subtle">no ₹ amount computed</span>}
          </td>
        </>
      )}
    </tr>
  );
}

function RiskView({ res, onExplain }: { res: RiskResponse; onExplain: OnExplain }) {
  const m = res.metrics;
  const dd = m?.max_drawdown;
  return (
    <div className={res.fixture ? "fixture-zone" : undefined}>
      <FixtureCallout fixture={res.fixture} />
      <p>
        <strong>{res.instrument.name}</strong> <span className="small subtle">{res.instrument.category} · risk category {res.instrument.risk_category}</span>
      </p>
      <ContextLine ctx={res.context_amount} />
      {res.status === "REFUSED" && res.refusal ? (
        <p className="callout callout--warn">
          <RefusalNote r={res.refusal} />
        </p>
      ) : null}
      {m && dd ? (
        <>
          <dl className="kv">
            <dt>Annualised volatility</dt>
            <dd>
              <Metric value={m.volatility} onExplain={onExplain} />
            </dd>
            <dt>Maximum drawdown</dt>
            <dd>
              {isRefusal(dd) ? (
                <RefusalNote r={dd} />
              ) : (
                <>
                  <Ex item={dd} onExplain={onExplain} />{" "}
                  <span className="small">
                    {dd.peak_date ? `peak ${dateLabel(dd.peak_date)}` : "no fall from a peak recorded"}
                    {dd.trough_date ? ` · low ${dateLabel(dd.trough_date)}` : ""}
                    {dd.peak_date ? (dd.recovery_date ? ` · recovered ${dateLabel(dd.recovery_date)}` : dd.recovered ? "" : " · not yet recovered") : ""}
                  </span>
                </>
              )}
            </dd>
            <dt>Sharpe ratio</dt>
            <dd>
              <Metric value={m.sharpe} onExplain={onExplain} />
            </dd>
          </dl>
          <div className="table-wrap">
            <table className="table table--compact">
              <caption className="small">One-day historical loss measures (a loss is shown as a positive share; ₹ on {res.context_amount.amount})</caption>
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col" className="num">
                    Share of amount
                  </th>
                  <th scope="col" className="num">
                    In ₹
                  </th>
                </tr>
              </thead>
              <tbody>
                <VarRow label="1-day historical VaR at 95 %" m={m.var_95} onExplain={onExplain} />
                <VarRow label="1-day historical CVaR at 95 %" m={m.cvar_95} onExplain={onExplain} />
                <VarRow label="1-day historical VaR at 99 %" m={m.var_99} onExplain={onExplain} />
                <VarRow label="1-day historical CVaR at 99 %" m={m.cvar_99} onExplain={onExplain} />
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      <p className="small subtle disclosure">{res.disclaimer}</p>
    </div>
  );
}

function Refused({ r }: { r: Refusal }) {
  return (
    <p className="callout callout--warn">
      <RefusalNote r={r} />
    </p>
  );
}

function Val({ item, onExplain }: { item: AnalysisExplained | undefined; onExplain: OnExplain }) {
  return <Ex item={item} onExplain={onExplain} />;
}

function ForecastView({ res, onExplain }: { res: ForecastResponse; onExplain: OnExplain }) {
  const sr = res.scenario_range;
  const v = res.validation;
  return (
    <div className={res.fixture ? "fixture-zone" : undefined}>
      <FixtureCallout fixture={res.fixture} />
      <p>
        <strong>{res.label}</strong> · {res.instrument.name} · horizon {res.horizon.days} days ({res.horizon.steps} observations)
      </p>
      <p className="small">
        Promotion: <strong>{res.promotion.status}</strong> — {res.promotion.reason}
      </p>
      {res.status === "REFUSED" && res.refusal ? <Refused r={res.refusal} /> : null}
      {res.context_amount ? <ContextLine ctx={res.context_amount} /> : null}
      {sr ? (
        <>
          <div className="table-wrap">
            <table className="table table--compact">
              <caption className="small">
                {sr.label}: historical {res.horizon.days}-day returns at each level ({sr.model_id} v{sr.model_version}, data to {dateLabel(sr.data_cutoff)};{" "}
                {sr.n_windows} overlapping windows ≈ {sr.n_eff} independent)
              </caption>
              <thead>
                <tr>
                  <th scope="col">Level</th>
                  <th scope="col" className="num">
                    Return over the horizon
                  </th>
                  <th scope="col" className="num">
                    Amount (before costs and tax)
                  </th>
                </tr>
              </thead>
              <tbody>
                {sr.quantiles.map((q) => (
                  <tr key={q.level}>
                    <th scope="row">{pct(q.level, 0, false)}</th>
                    <td className="num">
                      <Ex item={q.return} onExplain={onExplain} />
                    </td>
                    <td className="num">
                      <Ex item={q.value_inr} onExplain={onExplain} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sr.warnings.length ? <p className="small">⚠ {sr.warnings.join(" · ")}</p> : null}
        </>
      ) : null}
      {res.baseline_comparator ? (
        <p className="small">
          Baseline comparator: {res.baseline_comparator.label} ({res.baseline_comparator.model_id}) — return {pct(res.baseline_comparator.point)}.
        </p>
      ) : null}
      {v ? (
        <>
          <h3>Validation (walk-forward, held-out)</h3>
          {v.refusal ? (
            <Refused r={v.refusal} />
          ) : (
            <dl className="kv">
              <dt>Method</dt>
              <dd>
                {v.method_id} · {v.origins} origins · embargo {v.embargo} · nominal band {v.nominal_band} · status {v.status}
              </dd>
              <dt>Empirical coverage</dt>
              <dd>
                <Val item={v.coverage} onExplain={onExplain} /> ({v.inside} of {v.n} held-out outcomes inside the band)
              </dd>
              <dt>Calibration</dt>
              <dd>
                {v.calibration_status?.replace(/_/g, " ")} · coverage gate {v.passes_coverage_gate ? "passed" : "not passed"}
                {v.kupiec_p ? ` · Kupiec p-value ${roundHalfUp(v.kupiec_p, 4)}` : ""}
              </dd>
              <dt>Mean pinball loss</dt>
              <dd>
                <Val item={v.mean_pinball} onExplain={onExplain} />
              </dd>
              <dt>MAE of the median</dt>
              <dd>
                <Val item={v.mae_b1_median} onExplain={onExplain} />
              </dd>
              <dt>MAE of zero-drift comparator</dt>
              <dd>
                <Val item={v.mae_b3_zero_drift} onExplain={onExplain} />
              </dd>
            </dl>
          )}
        </>
      ) : null}
      {res.unreliable_when?.length ? (
        <>
          <h3>Unreliable when</h3>
          <ul className="small">
            {res.unreliable_when.map((x) => (
              <li key={x}>{(x)}</li>
            ))}
          </ul>
        </>
      ) : null}
      {res.assumptions?.length || res.limitations?.length ? (
        <details className="small">
          <summary>Assumptions and limitations</summary>
          <ul>
            {[...(res.assumptions ?? []), ...(res.limitations ?? [])].map((x) => (
              <li key={x}>{(x)}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="small subtle disclosure">{res.disclaimer}</p>
    </div>
  );
}
