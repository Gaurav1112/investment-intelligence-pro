import { useState, type FormEvent, type ReactNode } from "react";
import { dateLabel, pct, percentToFraction, utcStamp } from "../lib/format";
import {
  isFundFactsResponse,
  RATING_CHOICES,
  SHORT_TERM_RATINGS,
  type FundFacts,
  type FundFactsIn,
  type FundFactsOut,
  type FundFactsResponse,
} from "../lib/types-inputs";
import { useApi, useMutation } from "../lib/useApi";
import {
  citationBody,
  CitationFields,
  citationProblems,
  EMPTY_CITATION,
  errorText,
  FieldError,
  validationErrors,
  type CitationState,
} from "../pages/FixedIncome";
import { FreshnessBadge } from "./FreshnessBadge";
import "../styles/inputs.css";

const DECIMAL = /^\d+(\.\d+)?$/;
const NONE = <span className="subtle">not disclosed / not entered</span>;

const years = (v: string | null) => (v ? `${v} years` : NONE);
const frac = (v: string | null) => (v ? pct(v, 2, false) : NONE);

function stamp(iso: string): string {
  try {
    return utcStamp(iso);
  } catch {
    return iso;
  }
}

function CiteLink({ url }: { url: string }) {
  if (!url.startsWith("https://")) return <span className="mono small">{url}</span>;
  let host = url;
  try {
    host = new URL(url).hostname;
  } catch {
    /* keep raw */
  }
  return (
    <a href={url} target="_blank" rel="noreferrer noopener">
      {host}
    </a>
  );
}

function FactsView({ f, staleAfter }: { f: FundFacts; staleAfter: number }) {
  const rows: [string, ReactNode][] = [
    ["Modified duration", years(f.modified_duration)],
    ["Macaulay duration", years(f.macaulay_duration)],
    ["Portfolio YTM (as published)", frac(f.ytm)],
    ["Average maturity", years(f.average_maturity_years)],
    [
      "Expense ratio",
      f.expense_ratio ? (
        <>
          {pct(f.expense_ratio, 2, false)} <span className="small subtle">({f.expense_ratio_kind ?? "kind not entered"})</span>
        </>
      ) : (
        NONE
      ),
    ],
    [
      "Lowest credit rating held",
      f.lowest_rating ? (
        <>
          {f.lowest_rating}
          {SHORT_TERM_RATINGS.has(f.lowest_rating) ? (
            <span className="small subtle"> (short-term rating — cannot satisfy a long-term credit floor)</span>
          ) : null}
        </>
      ) : (
        NONE
      ),
    ],
    ["Share below AAA", frac(f.share_below_aaa)],
    ["Share in sovereign and cash", frac(f.share_sovereign_cash)],
  ];
  return (
    <div className="facts">
      <p className="facts__head">
        Factsheet as of <strong>{f.as_of_month}</strong> (portfolio date {dateLabel(f.as_of_date)}) ·{" "}
        {f.freshness === "STALE" ? (
          <FreshnessBadge freshness="STALE" date={f.as_of_date} />
        ) : (
          <FreshnessBadge freshness="MANUAL" date={f.as_of_date} />
        )}{" "}
        <span className="small subtle">
          {f.age_days} day{f.age_days === 1 ? "" : "s"} old
          {f.freshness === "STALE" ? ` (older than ${staleAfter} days: duration-based results are labelled STALE)` : ""}
        </span>
      </p>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} className="kv__row">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="small subtle">
        Source: <CiteLink url={f.citation_url} /> · read on {dateLabel(f.verified_on)} · entered {stamp(f.entered_at)}
        {f.citation_note ? ` · ${f.citation_note}` : ""}
      </p>
    </div>
  );
}

interface FormState {
  asOfMonth: string;
  modDur: string;
  macDur: string;
  ytmPct: string;
  avgMat: string;
  erPct: string;
  erKind: "" | "TER" | "BER";
  rating: string;
  belowAaaPct: string;
  sovCashPct: string;
}
const EMPTY: FormState = {
  asOfMonth: "", modDur: "", macDur: "", ytmPct: "", avgMat: "", erPct: "", erKind: "", rating: "", belowAaaPct: "", sovCashPct: "",
};

/** Build the request body; blank optional fields are OMITTED (never sent as "" or 0). */
export function factsBody(s: FormState, c: CitationState): { body: FundFactsIn | null; errors: Record<string, string> } {
  const errors: Record<string, string> = { ...citationProblems(c) };
  const body: FundFactsIn = { as_of_month: s.asOfMonth, citation: citationBody(c) };
  if (!/^\d{4}-\d{2}$/.test(s.asOfMonth)) errors["as_of_month"] = "Enter the factsheet month (YYYY-MM).";
  const years: [keyof FormState, "modified_duration" | "macaulay_duration" | "average_maturity_years"][] = [
    ["modDur", "modified_duration"],
    ["macDur", "macaulay_duration"],
    ["avgMat", "average_maturity_years"],
  ];
  for (const [k, field] of years) {
    const t = s[k].trim();
    if (!t) continue;
    if (!DECIMAL.test(t)) errors[field] = "Enter a number of years, e.g. 2.35.";
    else body[field] = t;
  }
  const pcts: [keyof FormState, "ytm" | "expense_ratio" | "share_below_aaa" | "share_sovereign_cash"][] = [
    ["ytmPct", "ytm"],
    ["erPct", "expense_ratio"],
    ["belowAaaPct", "share_below_aaa"],
    ["sovCashPct", "share_sovereign_cash"],
  ];
  for (const [k, field] of pcts) {
    const f = percentToFraction(s[k]);
    if (f === null) continue;
    if (f === "invalid") errors[field] = "Enter a percentage, e.g. 7.25.";
    else body[field] = f;
  }
  if (s.erKind) body.expense_ratio_kind = s.erKind;
  if (s.rating) body.lowest_rating = s.rating;
  const metrics = [
    body.modified_duration, body.macaulay_duration, body.ytm, body.average_maturity_years, body.expense_ratio,
    body.lowest_rating, body.share_below_aaa, body.share_sovereign_cash,
  ];
  if (metrics.every((m) => m === undefined)) errors["_"] = "Enter at least one figure from the factsheet.";
  return { body: Object.keys(errors).length ? null : body, errors };
}

function Num({ id, label, value, onChange, hint, err }: { id: string; label: string; value: string; onChange: (v: string) => void; hint?: string; err?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={Boolean(err)} aria-describedby={`${id}-err`} />
      {hint ? <div className="hint">{hint}</div> : null}
      <FieldError id={`${id}-err`} msg={err} />
    </div>
  );
}

function FactsForm({ instrumentId, onSaved }: { instrumentId: string; onSaved: () => void }) {
  const [s, setS] = useState<FormState>(EMPTY);
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const m = useMutation<FundFactsIn, FundFactsOut>("POST", `/api/inputs/fund-facts/${encodeURIComponent(instrumentId)}`);
  const set = (k: keyof FormState) => (v: string) => setS((x) => ({ ...x, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    const { body, errors: problems } = factsBody(s, cite);
    setErrors(problems);
    if (!body) return;
    const out = await m.run(body);
    if (out) {
      setS(EMPTY);
      setCite(EMPTY_CITATION);
      setSaved(true);
      onSaved();
    }
  }
  const server = validationErrors(m.error) ?? {};
  const all = { ...server, ...errors };
  return (
    <form className="inputs-form" onSubmit={submit} aria-label="Enter factsheet facts" noValidate>
      <p className="small subtle">
        Copy figures exactly as the AMC&apos;s monthly factsheet publishes them. Leave a field blank if it is not disclosed — nothing is assumed.
      </p>
      <div className="field">
        <label htmlFor="ff-month">Factsheet month (portfolio as of month end)</label>
        <input id="ff-month" type="month" value={s.asOfMonth} onChange={(e) => set("asOfMonth")(e.target.value)} aria-invalid={Boolean(all["as_of_month"])} aria-describedby="ff-month-err" required />
        <FieldError id="ff-month-err" msg={all["as_of_month"]} />
      </div>
      <div className="inputs-grid">
        <Num id="ff-moddur" label="Modified duration (years)" value={s.modDur} onChange={set("modDur")} err={all["modified_duration"]} />
        <Num id="ff-macdur" label="Macaulay duration (years)" value={s.macDur} onChange={set("macDur")} err={all["macaulay_duration"]} />
        <Num id="ff-avgmat" label="Average maturity (years)" value={s.avgMat} onChange={set("avgMat")} err={all["average_maturity_years"]} />
        <Num id="ff-ytm" label="Portfolio YTM (%)" value={s.ytmPct} onChange={set("ytmPct")} err={all["ytm"]} />
        <Num id="ff-er" label="Expense ratio (%)" value={s.erPct} onChange={set("erPct")} err={all["expense_ratio"]} />
        <div className="field">
          <label htmlFor="ff-erkind">Expense ratio kind</label>
          <select id="ff-erkind" value={s.erKind} onChange={(e) => set("erKind")(e.target.value)}>
            <option value="">— not entered —</option>
            <option value="TER">TER (total expense ratio)</option>
            <option value="BER">BER (base expense ratio, levies excluded)</option>
          </select>
          <FieldError id="ff-erkind-err" msg={all["expense_ratio_kind"]} />
        </div>
        <div className="field">
          <label htmlFor="ff-rating">Lowest credit rating held</label>
          <select id="ff-rating" value={s.rating} onChange={(e) => set("rating")(e.target.value)} aria-describedby="ff-rating-hint ff-rating-err">
            <option value="">— not entered —</option>
            {RATING_CHOICES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <div id="ff-rating-hint" className="hint">
            Short-term ratings (A1+ … A4) are accepted but cannot satisfy a long-term credit floor; such a fund is excluded when you set a floor.
          </div>
          <FieldError id="ff-rating-err" msg={all["lowest_rating"]} />
        </div>
        <Num id="ff-belowaaa" label="Share below AAA (%)" value={s.belowAaaPct} onChange={set("belowAaaPct")} err={all["share_below_aaa"]} />
        <Num id="ff-sovcash" label="Share in sovereign and cash (%)" value={s.sovCashPct} onChange={set("sovCashPct")} err={all["share_sovereign_cash"]} />
      </div>
      <CitationFields prefix="ff-cite" value={cite} onChange={setCite} errors={all} />
      <p className="hint">For the citation date, enter the date you read the factsheet.</p>
      <FieldError id="ff-form-err" msg={all["_"]} />
      {m.error && !validationErrors(m.error) ? (
        <div className="field-error" role="alert">
          {errorText(m.error)}
        </div>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={m.pending}>
        {m.pending ? "Saving…" : "Save factsheet facts"}
      </button>
      {saved ? (
        <p className="small" role="status">
          Saved. The newest factsheet is now used; earlier entries are kept as history.
        </p>
      ) : null}
    </form>
  );
}

/** Mutual-fund factsheet facts: latest values with as-of date and freshness, plus the entry form. */
export function FundFactsPanel({ instrumentId }: { instrumentId: string }) {
  const res = useApi<FundFactsResponse>(`/api/inputs/fund-facts/${encodeURIComponent(instrumentId)}`);
  const [open, setOpen] = useState(false);
  const data = isFundFactsResponse(res.data) ? res.data : null;
  return (
    <section className="inputs-section" aria-labelledby="facts-h">
      <h2 id="facts-h">Factsheet facts</h2>
      {res.loading ? (
        <p className="small subtle">Loading factsheet facts…</p>
      ) : res.error ? (
        <p className="small field-error">Factsheet facts could not be loaded: {errorText(res.error)}</p>
      ) : data?.latest ? (
        <FactsView f={data.latest} staleAfter={data.stale_after_days} />
      ) : (
        <p className="callout callout--warn">
          No factsheet facts entered — rate/spread shocks, yield-carry ranges and the credit-floor check are unavailable for this fund.
        </p>
      )}
      {data && data.history.length > 1 ? (
        <p className="small subtle">{data.history.length} factsheet entries stored; the newest is used.</p>
      ) : null}
      <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen((x) => !x)}>
        {open ? "Close factsheet form" : "Enter factsheet facts"}
      </button>
      {open ? <FactsForm instrumentId={instrumentId} onSaved={res.reload} /> : null}
    </section>
  );
}
