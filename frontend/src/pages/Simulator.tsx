import { useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { Link, useSearchParams } from "react-router-dom";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { Loading } from "../components/States";
import { TierLabel } from "../components/Tier";
import { api } from "../lib/api";
import { compareDecimals, dateLabel, inr, percentToFraction, shiftPoint, sumDecimals } from "../lib/format";
import type { SimMaturity, SimulateIn, SimulateResponse } from "../lib/types";
import {
  AmountDateFields,
  AnalysisErrorState,
  BandCell,
  ContextLine,
  Ex,
  FixtureCallout,
  InstrumentPicker,
  RefusalNote,
  amountDateProblems,
  flagText,
  isRefusal,
  useExplain,
  type OnExplain,
  type Picked,
} from "./Compare";

const MAX_ROWS = 20;

export interface AllocRow {
  pick: Picked;
  weightPct: string;
}

export interface WeightCheck {
  /** Exact sum of the valid percentages typed so far (decimal string), or null if any row is invalid. */
  totalPct: string | null;
  /** Per-row fraction strings for the request, in row order (null where the row is invalid). */
  fractions: (string | null)[];
  problems: Record<number, string>;
  /** True only when every row is valid and the percentages sum to exactly 100 (string arithmetic, no floats). */
  ok: boolean;
}

/** Validate weights typed as percentages and check that they sum to EXACTLY 100 %. */
export function checkWeights(rows: readonly { weightPct: string }[]): WeightCheck {
  const problems: Record<number, string> = {};
  const fractions = rows.map((r, i) => {
    const f = percentToFraction(r.weightPct);
    if (f === null) {
      problems[i] = "Enter a weight in %.";
      return null;
    }
    if (f === "invalid") {
      problems[i] = "Enter a plain number of percent, e.g. 33.33 (no % sign).";
      return null;
    }
    if (compareDecimals(f, "0") <= 0 || compareDecimals(f, "1") > 0) {
      problems[i] = "Each weight must be more than 0 % and at most 100 %.";
      return null;
    }
    return f;
  });
  const valid = rows.filter((_, i) => fractions[i] !== null).map((r) => r.weightPct.trim());
  const totalPct = sumDecimals(valid);
  const allValid = rows.length > 0 && Object.keys(problems).length === 0;
  // Both checks are exact: the percentages and the fractions actually sent must each sum to exactly 100 % / 1.
  const ok = allValid && compareDecimals(totalPct, "100") === 0 && compareDecimals(sumDecimals(fractions as string[]), "1") === 0;
  return { totalPct, fractions, problems, ok };
}

const pctOfWeight = (w: string) => `${shiftPoint(w, 2)} %`;

export default function Simulator() {
  const [params] = useSearchParams();
  const initialId = params.get("id");
  const [rows, setRows] = useState<AllocRow[]>(() =>
    initialId ? [{ pick: { instrument_id: initialId, name: null, fixture: null }, weightPct: "100" }] : [],
  );
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [result, setResult] = useState<SimulateResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const { open, drawer } = useExplain();

  const check = checkWeights(rows);
  const setWeight = (i: number, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, weightPct: v } : r)));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const p = amountDateProblems(amount, date);
    setProblems(p);
    if (Object.keys(p).length || !check.ok) return;
    const body: SimulateIn = {
      allocations: rows.map((r, i) => ({ instrument_id: r.pick.instrument_id, weight: check.fractions[i] as string })),
    };
    if (amount.trim()) body.amount = amount.trim();
    if (date) body.withdrawal_date = date;
    setPending(true);
    setError(null);
    try {
      setResult(await api<SimulateResponse>("/api/simulate", { method: "POST", body }));
    } catch (err) {
      setResult(null);
      setError(err);
    } finally {
      setPending(false);
    }
  }

  const totalText = check.totalPct === null ? "—" : `${check.totalPct} %`;
  return (
    <section>
      <PageHeader
        title="Portfolio simulator"
        purpose={
          <>
            Split one amount across instruments and see each holding’s range of proceeds at your withdrawal date. Weights must add up to exactly 100 %. Not a recommendation.
          </>
        }
      />
      <form className="card" onSubmit={submit} noValidate>
        <h2 className="h-inline">Allocation</h2>
        {rows.length ? (
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Instrument</th>
                  <th scope="col">Weight (%)</th>
                  <th scope="col">
                    <span className="sr-only">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.pick.instrument_id}>
                    <td>
                      {r.pick.name ?? r.pick.instrument_id} <span className="small subtle mono">{r.pick.instrument_id}</span>{" "}
                      {r.pick.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
                    </td>
                    <td>
                      <label className="sr-only" htmlFor={`w-${i}`}>
                        Weight for {r.pick.name ?? r.pick.instrument_id} (%)
                      </label>
                      <input
                        id={`w-${i}`}
                        inputMode="decimal"
                        value={r.weightPct}
                        onChange={(e) => setWeight(i, e.target.value)}
                        aria-invalid={Boolean(check.problems[i])}
                        size={8}
                      />
                      {check.problems[i] && r.weightPct.trim() ? <div className="field-error">{check.problems[i]}</div> : null}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                        aria-label={`Remove ${r.pick.name ?? r.pick.instrument_id}`}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Total</th>
                  <td colSpan={2}>
                    <output aria-live="polite" data-testid="weight-total">
                      <strong>{totalText}</strong>
                    </output>{" "}
                    {check.ok ? (
                      <span className="small">✓ exactly 100 %</span>
                    ) : (
                      <span className="small field-error">must be exactly 100 % to run</span>
                    )}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        ) : (
          <p className="small subtle">No holdings yet. Add instruments below.</p>
        )}
        {rows.length < MAX_ROWS ? (
          <InstrumentPicker
            idPrefix="sim"
            label="Add an instrument"
            exclude={rows.map((r) => r.pick.instrument_id)}
            onPick={(p) => setRows((rs) => [...rs, { pick: p, weightPct: "" }])}
          />
        ) : null}
        <AmountDateFields idPrefix="sim" amount={amount} date={date} onAmount={setAmount} onDate={setDate} errors={problems} />
        <button type="submit" className="btn btn--primary" disabled={!check.ok || pending}>
          {pending ? "Simulating…" : "Simulate"}
        </button>
      </form>
      {pending ? <Loading label="Simulating" /> : error ? <AnalysisErrorState error={error} /> : result ? <SimView res={result} onExplain={open} /> : null}
      {drawer}
    </section>
  );
}

function MaturityText({ m }: { m: SimMaturity }) {
  if (m.status === "MATURITY_MISMATCH_after_withdrawal")
    return (
      <strong className="mismatch">
        ⚠ MATURITY MISMATCH — matures {m.days_between} days after your withdrawal date. {m.note}
      </strong>
    );
  if (m.status === "no_maturity") return <span>No maturity. {m.note}</span>;
  if (m.status === "matures_on_withdrawal") return <span>Matures on your withdrawal date.</span>;
  return <span>Matures before your withdrawal date. {m.note}</span>;
}

function SimView({ res, onExplain }: { res: SimulateResponse; onExplain: OnExplain }) {
  const name = (id: string) => res.holdings.find((h) => h.instrument_id === id)?.name ?? id;
  return (
    <div className={res.fixture ? "fixture-zone" : undefined}>
      <FixtureCallout fixture={res.fixture} />
      <ContextLine ctx={res.context} />

      <h2>Holdings</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Instrument</th>
              <th scope="col" className="num">
                Weight
              </th>
              <th scope="col" className="num">
                Allocated ₹
              </th>
              <th scope="col">Certainty</th>
              <th scope="col" className="num">
                Net proceeds at your date
                <div className="small subtle">illustrative downside scenario · middle · high end</div>
              </th>
            </tr>
          </thead>
          <tbody>
            {res.holdings.map((h) => (
              <tr key={h.instrument_id} className={h.fixture ? "fixture-zone" : undefined}>
                <td>
                  <Link to={`/i/${encodeURIComponent(h.instrument_id)}`}>{h.name}</Link> {h.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
                  {h.flags.length ? <div className="small subtle">⚠ {h.flags.map(flagText).join(" · ")}</div> : null}
                  {h.eligibility_reasons.length ? <div className="small">{h.eligibility_reasons.join("; ")}</div> : null}
                </td>
                <td className="num">{pctOfWeight(h.weight)}</td>
                <td className="num">
                  <Ex item={h.allocation} onExplain={onExplain} />
                </td>
                <td>{h.tier ? <TierLabel tier={h.tier} /> : <span className="subtle">—</span>}</td>
                <td className="num">{h.band ? <BandCell band={h.band} onExplain={onExplain} /> : <span>Not evaluated: no band computed.</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small subtle">
        Allocations sum to {inr(res.reconciliation.sum_of_allocations)} of {inr(res.reconciliation.amount)}
        {res.reconciliation.reconciles ? " — reconciles exactly." : " — DOES NOT reconcile; do not rely on this result."}
      </p>

      <h2>Portfolio band</h2>
      {isRefusal(res.portfolio) ? (
        <p>
          <RefusalNote r={res.portfolio} />
        </p>
      ) : (
        <>
          <dl className="kv">
            <dt>Conservative sum, ignores diversification (q05)</dt>
            <dd>
              <Ex item={res.portfolio.band.q05} onExplain={onExplain} />
            </dd>
            <dt>{res.portfolio.band.q50.label}</dt>
            <dd>
              <Ex item={res.portfolio.band.q50} onExplain={onExplain} />
            </dd>
            <dt>{res.portfolio.band.q95.label}</dt>
            <dd>
              <Ex item={res.portfolio.band.q95} onExplain={onExplain} />
            </dd>
          </dl>
          <p className="small subtle">Method: {res.portfolio.method}.</p>
        </>
      )}

      <h2>Concentration</h2>
      <dl className="kv">
        <dt>Concentration (HHI)</dt>
        <dd>
          <Ex item={res.concentration.hhi} onExplain={onExplain} /> — {res.concentration.band}
        </dd>
        <dt>Effective number of holdings</dt>
        <dd>
          <Ex item={res.concentration.effective_count} onExplain={onExplain} />
        </dd>
      </dl>

      <h2>Liquidity ladder</h2>
      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">Cash available</th>
              <th scope="col">Holdings</th>
              <th scope="col" className="num">
                ₹ in bucket
              </th>
              <th scope="col" className="num">
                Cumulative ₹
              </th>
            </tr>
          </thead>
          <tbody>
            {res.liquidity_ladder.map((b) => (
              <tr key={String(b.days_to_cash)}>
                <th scope="row">{b.label}</th>
                <td>{b.holdings.map(name).join(", ")}</td>
                <td className="num">
                  <Ex item={b.amount} onExplain={onExplain} />
                </td>
                <td className="num">
                  <Ex item={b.cumulative} onExplain={onExplain} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Maturity vs withdrawal date</h2>
      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">Instrument</th>
              <th scope="col">Maturity</th>
              <th scope="col">Against your withdrawal date ({dateLabel(res.context.withdrawal_date)})</th>
            </tr>
          </thead>
          <tbody>
            {res.maturity.map((m) => (
              <tr key={m.instrument_id}>
                <th scope="row">{name(m.instrument_id)}</th>
                <td>{m.maturity_date ? dateLabel(m.maturity_date) : "—"}</td>
                <td>
                  <MaturityText m={m} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>DICGC deposit insurance</h2>
      {res.dicgc.applicable ? (
        <>
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Institution</th>
                  <th scope="col" className="num">
                    Total (principal + interest)
                  </th>
                  <th scope="col" className="num">
                    Insured
                  </th>
                  <th scope="col" className="num">
                    Uninsured
                  </th>
                </tr>
              </thead>
              <tbody>
                {res.dicgc.groups.map((g) => (
                  <tr key={g.institution}>
                    <th scope="row">
                      {g.institution} <span className="small subtle">({g.institution_type})</span>
                      {g.flags.length ? <div className="small">⚠ {g.flags.join(", ")}</div> : null}
                    </th>
                    <td className="num">
                      <Ex item={g.total} onExplain={onExplain} />
                    </td>
                    <td className="num">
                      <Ex item={g.insured} onExplain={onExplain} />
                    </td>
                    <td className="num">
                      <Ex item={g.uninsured} onExplain={onExplain} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="small subtle">
            {[...res.dicgc.conventions, ...res.dicgc.warnings.map((w) => w.replace(/_/g, " ").toLowerCase()), ...res.dicgc.notes].map((x) => (
              <li key={x}>{(x)}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="small">{res.dicgc.reason}</p>
      )}
      <p className="small subtle disclosure">{res.disclaimer}</p>
    </div>
  );
}
