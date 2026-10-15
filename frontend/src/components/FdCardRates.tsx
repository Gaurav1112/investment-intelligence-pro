import { useRef, useState, type FormEvent } from "react";
import { dateLabel, percentToFraction } from "../lib/format";
import {
  isFdRatesResponse,
  type FdRateBucket,
  type FdRatesResponse,
  type FdRateTable,
  type FdRateTableIn,
  type FdRateTableOut,
  type PrematureRateBasis,
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

const BASIS_TEXT: Record<PrematureRateBasis, string> = {
  period_card: "Card rate for the period actually held",
  "min(booked,period_card)": "Lower of the booked rate and the card rate for the period held",
};

interface Row {
  key: number;
  min: string;
  max: string;
  pct: string;
}

const WHOLE = /^\d+$/;

function TableCard({ t }: { t: FdRateTable }) {
  return (
    <article className="card inputs-card" aria-labelledby={`fdr-${t.table_id}`}>
      <h4 id={`fdr-${t.table_id}`}>{t.institution}</h4>
      <p className="row-tight small">
        <FreshnessBadge freshness={t.freshness} date={t.as_of} />
        <span className="subtle">
          rates apply from {dateLabel(t.as_of)} · {t.age_days < 0 ? "dated in the future" : `${t.age_days} day${t.age_days === 1 ? "" : "s"} old`}
        </span>
        {t.current ? (
          <span className="badge badge--neutral">used for analysis</span>
        ) : (
          <span className="subtle">superseded by a later table, or dated after today</span>
        )}
      </p>
      <p className="small">Early withdrawal: {BASIS_TEXT[t.premature_rate_basis]}</p>
      <div className="table-wrap">
        <table className="table table--compact">
          <caption className="sr-only">Card rates for {t.institution} from {dateLabel(t.as_of)}</caption>
          <thead>
            <tr>
              <th scope="col">Tenure (days)</th>
              <th scope="col" className="num">
                Rate a year
              </th>
            </tr>
          </thead>
          <tbody>
            {t.buckets.map((b) => (
              <tr key={`${b.min_days}-${b.max_days}`}>
                <td>
                  {b.min_days} – {b.max_days}
                </td>
                <td className="num">{ratePct(b.rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small subtle">
        Source: <span className="mono">{t.citation_url}</span>
        {t.citation_note ? ` · ${t.citation_note}` : ""}
      </p>
    </article>
  );
}

function FdRateList({ data }: { data: FdRatesResponse }) {
  if (data.tables.length === 0)
    return (
      <p className="small subtle">
        No card-rate tables stored. Without one, an early exit from a fixed deposit is shown as not evaluable.
      </p>
    );
  return (
    <>
      <p className="small subtle">
        A table older than {data.stale_after_days} days is marked STALE. Analysis uses each bank&apos;s latest table dated on or before
        today.
      </p>
      {data.tables.map((t) => (
        <TableCard key={t.table_id} t={t} />
      ))}
    </>
  );
}

function FdRateForm({ onSaved }: { onSaved: () => void }) {
  const next = useRef(2);
  const [institution, setInstitution] = useState("");
  const [basis, setBasis] = useState<PrematureRateBasis>("period_card");
  const [rows, setRows] = useState<Row[]>([{ key: 1, min: "", max: "", pct: "" }]);
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState<string | null>(null);
  const m = useMutation<FdRateTableIn, FdRateTableOut>("POST", "/api/inputs/fd-rates");

  const setRow = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addRow = () => {
    setRows((rs) => [...rs, { key: next.current, min: "", max: "", pct: "" }]);
    next.current += 1;
  };
  const removeRow = (key: number) => setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.key !== key) : rs));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    const errs: Record<string, string> = { ...citationProblems(cite) };
    if (institution.trim().length < 2) errs["institution"] = "Enter the bank's name.";
    const buckets: FdRateBucket[] = [];
    rows.forEach((r, i) => {
      if (!WHOLE.test(r.min.trim())) errs[`buckets.${i}.min_days`] = "Whole number of days, e.g. 7.";
      if (!WHOLE.test(r.max.trim())) errs[`buckets.${i}.max_days`] = "Whole number of days, e.g. 45.";
      const rate = percentToFraction(r.pct);
      if (rate === null || rate === "invalid") errs[`buckets.${i}.rate`] = "Rate as a plain number of percent, e.g. 7.25.";
      else buckets.push({ min_days: Number.parseInt(r.min.trim(), 10), max_days: Number.parseInt(r.max.trim(), 10), rate });
    });
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const out = await m.run({ institution: institution.trim(), buckets, premature_rate_basis: basis, citation: citationBody(cite) });
    if (out) {
      setDone(`Saved card-rate table for ${institution.trim()}.`);
      setInstitution("");
      setRows([{ key: next.current, min: "", max: "", pct: "" }]);
      next.current += 1;
      setCite(EMPTY_CITATION);
      onSaved();
    }
  }

  const server = validationErrors(m.error);
  const all = { ...(server ?? {}), ...errors };
  return (
    <form className="inputs-form" onSubmit={submit} aria-label="Enter a bank's FD card-rate table" noValidate>
      <div className="field">
        <label htmlFor="fdr-inst">Bank</label>
        <input id="fdr-inst" className="input-wide" maxLength={120} value={institution} onChange={(e) => setInstitution(e.target.value)}
          aria-invalid={Boolean(all["institution"])} aria-describedby="fdr-inst-hint fdr-inst-err" />
        <div id="fdr-inst-hint" className="hint">Use the same name as on your fixed deposits so the table is matched to them.</div>
        <FieldError id="fdr-inst-err" msg={all["institution"]} />
      </div>
      <fieldset className="field">
        <legend>Card rates by tenure (from the bank&apos;s rate page)</legend>
        {rows.map((r, i) => (
          <div className="inputs-grid" key={r.key} role="group" aria-label={`Tenure band ${i + 1}`}>
            <div className="field">
              <label htmlFor={`fdr-min-${r.key}`}>From (days)</label>
              <input id={`fdr-min-${r.key}`} className="input-short" inputMode="numeric" value={r.min} onChange={(e) => setRow(r.key, { min: e.target.value })}
                aria-invalid={Boolean(all[`buckets.${i}.min_days`])} aria-describedby={`fdr-min-${r.key}-err`} />
              <FieldError id={`fdr-min-${r.key}-err`} msg={all[`buckets.${i}.min_days`]} />
            </div>
            <div className="field">
              <label htmlFor={`fdr-max-${r.key}`}>To (days)</label>
              <input id={`fdr-max-${r.key}`} className="input-short" inputMode="numeric" value={r.max} onChange={(e) => setRow(r.key, { max: e.target.value })}
                aria-invalid={Boolean(all[`buckets.${i}.max_days`])} aria-describedby={`fdr-max-${r.key}-err`} />
              <FieldError id={`fdr-max-${r.key}-err`} msg={all[`buckets.${i}.max_days`]} />
            </div>
            <div className="field">
              <label htmlFor={`fdr-rate-${r.key}`}>Rate (% a year)</label>
              <span className="pct">
                <input id={`fdr-rate-${r.key}`} inputMode="decimal" value={r.pct} onChange={(e) => setRow(r.key, { pct: e.target.value })}
                  aria-invalid={Boolean(all[`buckets.${i}.rate`])} aria-describedby={`fdr-rate-${r.key}-err`} />
              </span>
              <FieldError id={`fdr-rate-${r.key}-err`} msg={all[`buckets.${i}.rate`]} />
            </div>
            {rows.length > 1 ? (
              <button type="button" className="btn btn--small" onClick={() => removeRow(r.key)} aria-label={`Remove tenure band ${i + 1}`}>
                Remove
              </button>
            ) : null}
          </div>
        ))}
        <button type="button" className="btn" onClick={addRow}>
          Add tenure band
        </button>
        <div className="hint">Bands must not overlap; the server checks this and says which band is wrong.</div>
      </fieldset>
      <div className="field">
        <label htmlFor="fdr-basis">Rate paid on early withdrawal</label>
        <select id="fdr-basis" value={basis} onChange={(e) => setBasis(e.target.value as PrematureRateBasis)}>
          {(Object.keys(BASIS_TEXT) as PrematureRateBasis[]).map((b) => (
            <option key={b} value={b}>
              {BASIS_TEXT[b]}
            </option>
          ))}
        </select>
        <div className="hint">As stated in the bank&apos;s premature-withdrawal terms.</div>
      </div>
      <CitationFields prefix="fdr-cite" value={cite} onChange={setCite} errors={all} />
      <p className="hint">For the date, enter the date the bank says these rates apply from.</p>
      {m.error && (!server || server["_"]) ? (
        <div className="field-error" role="alert">
          Not saved: {server?.["_"] ?? errorText(m.error)}
        </div>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={m.pending}>
        {m.pending ? "Saving…" : "Save card-rate table"}
      </button>
      {done ? (
        <p className="small" role="status">
          {done}
        </p>
      ) : null}
    </form>
  );
}

/** Fixed income → Fixed deposits: each bank's card-rate table, used to price an early exit. */
export function FdCardRates() {
  const res = useApi<FdRatesResponse>("/api/inputs/fd-rates");
  return (
    <section className="inputs-section" aria-labelledby="fdr-h">
      <h2 id="fdr-h">FD card-rate tables</h2>
      <p className="small muted">
        The rate a bank pays when you withdraw early depends on its card rate for the period you actually held. Enter the bank&apos;s
        published table with its citation; without it, early-exit scenarios for that bank are refused.
      </p>
      {res.loading ? (
        <p className="small subtle">Loading card-rate tables…</p>
      ) : res.error ? (
        <p className="small field-error">Card-rate tables could not be loaded: {errorText(res.error)}</p>
      ) : isFdRatesResponse(res.data) ? (
        <FdRateList data={res.data} />
      ) : (
        <p className="small subtle">Card-rate tables unavailable.</p>
      )}
      <FdRateForm onSaved={res.reload} />
    </section>
  );
}
