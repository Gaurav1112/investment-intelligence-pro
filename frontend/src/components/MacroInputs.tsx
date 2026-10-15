import { useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import { dateLabel, utcStamp } from "../lib/format";
import {
  isCpiResponse,
  isMospiStatus,
  isRiskFreeResponse,
  type CpiBase,
  type CpiIn,
  type CpiResponse,
  type MospiFetchIn,
  type MospiFetchOut,
  type MospiStatus,
  type RiskFreeIn,
  type RiskFreeResponse,
  type SeriesUpsertOut,
} from "../lib/types-inputs";
import { useApi, useMutation } from "../lib/useApi";
import {
  citationBody,
  CitationFields,
  citationProblems,
  EMPTY_CITATION,
  errorText,
  FieldError,
  ratePct,
  validationErrors,
  type CitationState,
} from "../pages/FixedIncome";
import { FreshnessBadge } from "./FreshnessBadge";
import "../styles/inputs.css";

const DECIMAL = /^\d+(\.\d+)?$/;
const SIGNED_DECIMAL = /^-?\d+(\.\d+)?$/;

function stamp(iso: string): string {
  try {
    return utcStamp(iso);
  } catch {
    return iso;
  }
}

const OUTCOME_TEXT: Record<string, string> = {
  inserted: "Saved.",
  unchanged: "Already stored with the same value — nothing changed.",
  corrected: "Saved as a correction; the earlier value is kept in history.",
};

// ------------------------------------------------------------------------------------------- MoSPI status

/** The server's {detail: {code, message}} refusal, in words (HTTPException with a dict detail). */
function mospiRefusal(e: unknown): string {
  const d = (e instanceof ApiError ? (e.detail as { detail?: unknown } | undefined)?.detail : undefined) as
    | { code?: unknown; message?: unknown }
    | undefined;
  if (d && typeof d.message === "string") {
    if (d.code === "REQUIRES_CONFIGURATION") return `REQUIRES CONFIGURATION: ${d.message}`;
    return `${d.message} (${String(d.code ?? "error")}). Nothing was stored.`;
  }
  return errorText(e);
}

function MospiFetch({ onStored }: { onStored: () => void }) {
  const [base, setBase] = useState<"2012" | "2024">("2024");
  const [month, setMonth] = useState("");
  const [err, setErr] = useState<string | undefined>();
  const [done, setDone] = useState<string | null>(null);
  const m = useMutation<MospiFetchIn, MospiFetchOut>("POST", "/api/inputs/mospi/fetch");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    const ym = /^(\d{4})-(\d{2})$/.exec(month);
    if (!ym) {
      setErr("Choose the reference month to fetch.");
      return;
    }
    setErr(undefined);
    const out = await m.run({ base_year: base === "2024" ? 2024 : 2012, year: Number(ym[1]), month: Number(ym[2]) });
    if (out) {
      setDone(
        `${OUTCOME_TEXT[out.outcome] ?? "Saved."} CPI for ${out.month} (base ${base}) fetched from MoSPI. NOT VERIFIED: check it against the MoSPI release.`,
      );
      onStored();
    }
  }
  return (
    <form className="inputs-form" onSubmit={submit} aria-label="Fetch CPI from MoSPI" noValidate>
      <div className="inputs-grid">
        <div className="field">
          <label htmlFor="mospi-base">Base year (series)</label>
          <select id="mospi-base" value={base} onChange={(e) => setBase(e.target.value as "2012" | "2024")}>
            <option value="2024">2024 = 100</option>
            <option value="2012">2012 = 100</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="mospi-month">Reference month</label>
          <input id="mospi-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-invalid={Boolean(err)} aria-describedby="mospi-month-err" />
          <FieldError id="mospi-month-err" msg={err} />
        </div>
      </div>
      {m.error ? (
        <div className="field-error" role="alert">
          {mospiRefusal(m.error)}
        </div>
      ) : null}
      <button type="submit" className="btn" disabled={m.pending}>
        {m.pending ? "Fetching…" : "Fetch CPI from MoSPI"}
      </button>
      {done ? (
        <p className="small" role="status">
          {done}
        </p>
      ) : null}
    </form>
  );
}

function MospiPanel({ onStored }: { onStored: () => void }) {
  const res = useApi<MospiStatus>("/api/inputs/mospi/status");
  if (res.loading) return <p className="small subtle">Loading MoSPI configuration status…</p>;
  if (res.error) return <p className="small field-error">MoSPI status could not be loaded: {errorText(res.error)}</p>;
  if (!isMospiStatus(res.data)) return <p className="small subtle">MoSPI status unavailable.</p>;
  const s = res.data;
  const configured = s.status === "CONFIGURED";
  return (
    <div className="card inputs-card">
      <h3>MoSPI CPI API</h3>
      <p>
        <span className={`badge ${configured ? "badge--eod" : "badge--stale"}`}>
          <span aria-hidden="true">{configured ? "✓" : "⚙"}</span> {configured ? "CONFIGURED" : "REQUIRES CONFIGURATION"}
        </span>{" "}
        {s.verified ? null : <span className="badge badge--delayed">NOT VERIFIED</span>}
        {configured && s.method ? <span className="small subtle"> · method: {s.method}</span> : null}
      </p>
      <p className="small">{s.message}</p>
      {s.env_vars.length ? (
        <p className="small">
          Environment variables: {s.env_vars.map((v, i) => (
            <span key={v}>
              {i ? ", " : ""}
              <code>{v}</code>
            </span>
          ))}
        </p>
      ) : null}
      {configured ? (
        <MospiFetch onStored={onStored} />
      ) : (
        <p className="small subtle">
          Fetching from MoSPI is unavailable until it is configured (REQUIRES CONFIGURATION). Until then, enter CPI values by hand
          below, with the official release as the citation.
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------- CPI

function CpiForm({ onSaved }: { onSaved: () => void }) {
  const [base, setBase] = useState<CpiBase>("2024");
  const [month, setMonth] = useState("");
  const [index, setIndex] = useState("");
  const [yoy, setYoy] = useState("");
  const [provisional, setProvisional] = useState(false);
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState<string | null>(null);
  const m = useMutation<CpiIn, SeriesUpsertOut>("POST", "/api/inputs/cpi");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    const errs: Record<string, string> = { ...citationProblems(cite) };
    if (!/^\d{4}-\d{2}$/.test(month)) errs["month"] = "Enter the reference month (YYYY-MM).";
    if (!DECIMAL.test(index.trim())) errs["index"] = "Enter the index value exactly as published, e.g. 104.6.";
    if (yoy.trim() && !SIGNED_DECIMAL.test(yoy.trim())) errs["yoy_inflation_pct"] = "Enter a percentage, e.g. 2.07 or -0.5.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const body: CpiIn = { base_year: base, month, index: index.trim(), provisional, citation: citationBody(cite) };
    if (yoy.trim()) body.yoy_inflation_pct = yoy.trim();
    const out = await m.run(body);
    if (out) {
      setDone(OUTCOME_TEXT[out.outcome] ?? "Saved.");
      setMonth("");
      setIndex("");
      setYoy("");
      setProvisional(false);
      setCite(EMPTY_CITATION);
      onSaved();
    }
  }
  const all = { ...(validationErrors(m.error) ?? {}), ...errors };
  return (
    <form className="inputs-form" onSubmit={submit} aria-label="Enter a CPI point" noValidate>
      <div className="inputs-grid">
        <div className="field">
          <label htmlFor="cpi-base">Base year (series)</label>
          <select id="cpi-base" value={base} onChange={(e) => setBase(e.target.value as CpiBase)}>
            <option value="2024">2024 = 100 (current series, from Jan-2026)</option>
            <option value="2012">2012 = 100 (previous series)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="cpi-month">Reference month</label>
          <input id="cpi-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-invalid={Boolean(all["month"])} aria-describedby="cpi-month-err" required />
          <FieldError id="cpi-month-err" msg={all["month"]} />
        </div>
        <div className="field">
          <label htmlFor="cpi-index">All-India CPI (Combined, General) index</label>
          <input id="cpi-index" inputMode="decimal" value={index} onChange={(e) => setIndex(e.target.value)} aria-invalid={Boolean(all["index"])} aria-describedby="cpi-index-err" required />
          <FieldError id="cpi-index-err" msg={all["index"]} />
        </div>
        <div className="field">
          <label htmlFor="cpi-yoy">Published year-on-year inflation (%, optional)</label>
          <input id="cpi-yoy" inputMode="decimal" value={yoy} onChange={(e) => setYoy(e.target.value)} aria-invalid={Boolean(all["yoy_inflation_pct"])} aria-describedby="cpi-yoy-err" />
          <FieldError id="cpi-yoy-err" msg={all["yoy_inflation_pct"]} />
        </div>
      </div>
      <div className="field inputs-check">
        <input id="cpi-prov" type="checkbox" checked={provisional} onChange={(e) => setProvisional(e.target.checked)} />
        <label htmlFor="cpi-prov">Provisional (the latest month is revised in the next release)</label>
      </div>
      <CitationFields prefix="cpi-cite" value={cite} onChange={setCite} errors={all} />
      <p className="hint">Cite the MoSPI/PIB release; for the date, enter the release date.</p>
      {m.error && !validationErrors(m.error) ? (
        <div className="field-error" role="alert">
          {errorText(m.error)}
        </div>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={m.pending}>
        {m.pending ? "Saving…" : "Save CPI point"}
      </button>
      {done ? (
        <p className="small" role="status">
          {done}
        </p>
      ) : null}
    </form>
  );
}

function CpiList({ data }: { data: CpiResponse }) {
  return (
    <>
      <p className="callout" role="note">
        <strong>Base 2012 and base 2024 are separate series and are never chained.</strong> {data.note}
      </p>
      {data.series.length === 0 ? (
        <p className="small subtle">No CPI points stored. Inflation shocks and real returns stay unavailable until you enter some.</p>
      ) : (
        data.series.map((s) => (
          <div key={s.series_id} className="table-wrap">
            <table className="table table--compact">
              <caption>
                CPI base {s.base_year} = 100 <span className="mono small subtle">({s.series_id})</span>
              </caption>
              <thead>
                <tr>
                  <th scope="col">Month</th>
                  <th scope="col" className="num">Index</th>
                  <th scope="col" className="num">YoY inflation</th>
                  <th scope="col">Status</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {s.points.map((p) => (
                  <tr key={p.month + p.source_id}>
                    <td className="nowrap">{p.month}</td>
                    <td className="num">{p.index}</td>
                    <td className="num">{p.yoy_inflation_pct === null ? <span className="subtle">not entered</span> : `${p.yoy_inflation_pct} %`}</td>
                    <td className="small">{p.provisional ? "PROVISIONAL" : "final"}</td>
                    <td className="small">
                      {p.source_id}
                      <div className="subtle mono">{p.source_url}</div>
                      <div className="subtle">entered {stamp(p.retrieved_at)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
    </>
  );
}

function CpiPanel() {
  const res = useApi<CpiResponse>("/api/inputs/cpi");
  return (
    <div className="inputs-card">
      <h3>Consumer price index (CPI)</h3>
      {res.loading ? (
        <p className="small subtle">Loading CPI points…</p>
      ) : res.error ? (
        <p className="small field-error">CPI points could not be loaded: {errorText(res.error)}</p>
      ) : isCpiResponse(res.data) ? (
        <CpiList data={res.data} />
      ) : (
        <p className="small subtle">CPI points unavailable.</p>
      )}
      <CpiForm onSaved={res.reload} />
    </div>
  );
}

// ------------------------------------------------------------------------------------------- 91-day T-bill

const RF_BADGE = { FRESH: "MANUAL", STALE: "STALE", EXPIRED: "STALE", UNAVAILABLE: "UNAVAILABLE" } as const;

function RiskFreeForm({ onSaved }: { onSaved: () => void }) {
  const [y, setY] = useState("");
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState<string | null>(null);
  const m = useMutation<RiskFreeIn, SeriesUpsertOut>("POST", "/api/inputs/riskfree");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    const errs: Record<string, string> = { ...citationProblems(cite) };
    if (!DECIMAL.test(y.trim())) errs["yield_fraction"] = "Enter the cut-off yield as a fraction, e.g. 0.057281 for 5.7281 %.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const out = await m.run({ yield_fraction: y.trim(), citation: citationBody(cite) });
    if (out) {
      setDone(OUTCOME_TEXT[out.outcome] ?? "Saved.");
      setY("");
      setCite(EMPTY_CITATION);
      onSaved();
    }
  }
  const all = { ...(validationErrors(m.error) ?? {}), ...errors };
  return (
    <form className="inputs-form" onSubmit={submit} aria-label="Enter a 91-day T-bill cut-off yield" noValidate>
      <div className="field">
        <label htmlFor="rf-yield">91-day cut-off yield (fraction)</label>
        <input id="rf-yield" inputMode="decimal" value={y} onChange={(e) => setY(e.target.value)} aria-invalid={Boolean(all["yield_fraction"])} aria-describedby="rf-yield-hint rf-yield-err" required />
        <div id="rf-yield-hint" className="hint">
          From the RBI press release &ldquo;91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off&rdquo; — e.g. YTM 5.7281 % is entered as 0.057281.
        </div>
        <FieldError id="rf-yield-err" msg={all["yield_fraction"]} />
      </div>
      <CitationFields prefix="rf-cite" value={cite} onChange={setCite} errors={all} />
      <p className="hint">For the date, enter the auction date.</p>
      {m.error && !validationErrors(m.error) ? (
        <div className="field-error" role="alert">
          {errorText(m.error)}
        </div>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={m.pending}>
        {m.pending ? "Saving…" : "Save T-bill yield"}
      </button>
      {done ? (
        <p className="small" role="status">
          {done}
        </p>
      ) : null}
    </form>
  );
}

function RiskFreeList({ data }: { data: RiskFreeResponse }) {
  return (
    <>
      <p>
        Series <span className="mono small">{data.series_id}</span> ·{" "}
        <FreshnessBadge freshness={RF_BADGE[data.freshness]} date={data.latest?.auction_date ?? null} />
        {data.freshness === "EXPIRED" ? <span className="small field-error"> expired — enter the latest auction</span> : null}
      </p>
      {data.points.length === 0 ? (
        <p className="small subtle">No yields stored. The Sharpe ratio stays refused until the series covers the return window.</p>
      ) : (
        <div className="table-wrap table-wrap--scroll">
          <table className="table table--compact">
            <caption className="sr-only">91-day T-bill cut-off yields, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Auction date</th>
                <th scope="col" className="num">Cut-off yield</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {[...data.points].reverse().map((p) => (
                <tr key={p.auction_date}>
                  <td className="nowrap">{dateLabel(p.auction_date)}</td>
                  <td className="num">{ratePct(p.yield_fraction)}</td>
                  <td className="small">
                    <span className="subtle mono">{p.source_url}</span>
                    <div className="subtle">entered {stamp(p.retrieved_at)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function RiskFreePanel() {
  const res = useApi<RiskFreeResponse>("/api/inputs/riskfree");
  return (
    <div className="inputs-card">
      <h3>91-day T-bill cut-off yields (risk-free series)</h3>
      {res.loading ? (
        <p className="small subtle">Loading T-bill yields…</p>
      ) : res.error ? (
        <p className="small field-error">T-bill yields could not be loaded: {errorText(res.error)}</p>
      ) : isRiskFreeResponse(res.data) ? (
        <RiskFreeList data={res.data} />
      ) : (
        <p className="small subtle">T-bill yields unavailable.</p>
      )}
      <RiskFreeForm onSaved={res.reload} />
    </div>
  );
}

/** Data health → Macro inputs: MoSPI status, CPI points and the 91-day T-bill series, each entered with a citation. */
export function MacroInputs() {
  // A MoSPI fetch stores a CPI point; remounting the CPI panel reloads its list.
  const [cpiKey, setCpiKey] = useState(0);
  return (
    <section className="inputs-section" aria-labelledby="macro-h">
      <h2 id="macro-h">Macro inputs</h2>
      <p className="small muted">
        Inflation (CPI) and the risk-free rate are entered by you with an official citation. Nothing here is assumed: without these values,
        real returns, inflation shocks and the Sharpe ratio are refused.
      </p>
      <MospiPanel onStored={() => setCpiKey((k) => k + 1)} />
      <CpiPanel key={cpiKey} />
      <RiskFreePanel />
    </section>
  );
}
