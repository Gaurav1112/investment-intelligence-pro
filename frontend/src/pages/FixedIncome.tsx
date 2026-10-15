import { useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "../components/PageHeader";
import { Link } from "react-router-dom";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { Empty, ErrorState, Loading } from "../components/States";
import { api, ApiError } from "../lib/api";
import { dateLabel, groupIndian, inr, percentToFraction, roundHalfUp, shiftPoint } from "../lib/format";
import type {
  CitationIn,
  FDIn,
  InstitutionType,
  InstrumentDetailResponse,
  InstrumentList,
  InstrumentListItem,
  TBillIn,
  ValidationErrorBody,
} from "../lib/types";
import {
  CORPORATE_RATINGS,
  RATING_AGENCIES,
  type BondKind,
  type BondList,
  type BondListItem,
  type CallIn,
  type CorporateBondIn,
  type CorporateRating,
  type GsecIn,
  type RatingAgency,
  type YieldCompounding,
} from "../lib/types-bonds";
import { useApi } from "../lib/useApi";
import "../styles/bonds.css";

// ------------------------------------------------------------------ shared helpers (also used by MfExplorer / InstrumentDetail)

/** Today's calendar date in India (IST), as YYYY-MM-DD. */
export function todayIst(now: Date = new Date()): string {
  return now.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

/** Whole calendar days from `fromIso` to `toIso` (both YYYY-MM-DD). Integer arithmetic only. */
export function daysBetween(fromIso: string, toIso: string): number {
  const d = (iso: string) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (!m) throw new Error(`not an ISO date: ${iso}`);
    return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  };
  return Math.round((d(toIso) - d(fromIso)) / 86_400_000);
}

/** Fraction string → percent with the precision entered (2–4 dp): "0.0650" → "6.50 %", "0.065432" → "6.5432 %". */
export function ratePct(fraction: string): string {
  const exact = shiftPoint(fraction, 2);
  const [, frac = ""] = exact.split(".");
  const dp = Math.min(Math.max(frac.length, 2), 4);
  return `${roundHalfUp(exact, dp)} %`;
}

/** NAV per unit as AMFI publishes it: up to 4 decimals, Indian grouping. "1234.56789" → "₹1,234.5679". */
export function navLabel(value: string): string {
  const r = roundHalfUp(value, 4);
  const [int = "0", frac = ""] = r.replace("-", "").split(".");
  return `${r.startsWith("-") ? "−" : ""}₹${groupIndian(int)}.${frac}`;
}

/** A short human message for a failed request; backend `detail` strings are shown verbatim. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const wait = (e.detail as { retry_after_s?: unknown } | undefined)?.retry_after_s;
    const minutes = typeof wait === "number" ? Math.max(1, Math.ceil(wait / 60)) : null;
    const later = minutes === null ? "later" : `in about ${minutes} minute${minutes === 1 ? "" : "s"}`;
    if (e.code === "BACKFILL_IN_PROGRESS") return `Another history backfill is still running. Try this one ${later}.`;
    if (e.code === "RATE_LIMITED") return `This was fetched recently; to be polite to the source, try again ${later}.`;
    const d = (e.detail as { detail?: unknown } | undefined)?.detail;
    if (typeof d === "string") return `${d} (HTTP ${e.status})`;
    return `The request failed (HTTP ${e.status}, ${e.code}).`;
  }
  return "The request failed (network error).";
}

/** FastAPI 422 → { "citation.url": "…", "rate": "…" } keyed by the body path. */
export function validationErrors(e: unknown): Record<string, string> | null {
  if (!(e instanceof ApiError) || e.status !== 422) return null;
  const body = e.detail as Partial<ValidationErrorBody> | undefined;
  const out: Record<string, string> = {};
  for (const item of Array.isArray(body?.detail) ? body.detail : []) {
    const key = item.loc.filter((p) => p !== "body").join(".") || "_";
    out[key] = item.msg;
  }
  return out;
}

export interface CitationState {
  url: string;
  asOf: string;
  note: string;
}
export const EMPTY_CITATION: CitationState = { url: "", asOf: "", note: "" };

export function citationProblems(c: CitationState): Record<string, string> {
  const out: Record<string, string> = {};
  if (!/^https:\/\/\S+$/.test(c.url.trim())) out["citation.url"] = "Enter the https:// address of the official page.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(c.asOf)) out["citation.as_of"] = "Enter the date the page says the value applies from.";
  return out;
}

export function citationBody(c: CitationState): CitationIn {
  const body: CitationIn = { url: c.url.trim(), as_of: c.asOf };
  if (c.note.trim()) body.note = c.note.trim();
  return body;
}

export function FieldError({ id, msg }: { id: string; msg: string | undefined }) {
  return msg ? (
    <div id={id} className="field-error" role="alert">
      {msg}
    </div>
  ) : null;
}

export function CitationFields({
  prefix,
  value,
  onChange,
  errors,
}: {
  prefix: string;
  value: CitationState;
  onChange: (c: CitationState) => void;
  errors: Record<string, string>;
}) {
  return (
    <fieldset className="field">
      <legend>Citation (required)</legend>
      <div className="field">
        <label htmlFor={`${prefix}-url`}>Official page URL</label>
        <input
          id={`${prefix}-url`}
          type="url"
          className="input-wide"
          placeholder="https://"
          value={value.url}
          onChange={(e) => onChange({ ...value, url: e.target.value })}
          aria-invalid={Boolean(errors["citation.url"])}
          aria-describedby={`${prefix}-url-err`}
          required
        />
        <FieldError id={`${prefix}-url-err`} msg={errors["citation.url"]} />
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-asof`}>Value applies as of</label>
        <input
          id={`${prefix}-asof`}
          type="date"
          value={value.asOf}
          onChange={(e) => onChange({ ...value, asOf: e.target.value })}
          aria-invalid={Boolean(errors["citation.as_of"])}
          aria-describedby={`${prefix}-asof-err`}
          required
        />
        <FieldError id={`${prefix}-asof-err`} msg={errors["citation.as_of"]} />
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-note`}>Note (optional)</label>
        <input
          id={`${prefix}-note`}
          className="input-wide"
          maxLength={300}
          value={value.note}
          onChange={(e) => onChange({ ...value, note: e.target.value })}
        />
        <FieldError id={`${prefix}-note-err`} msg={errors["citation.note"]} />
      </div>
    </fieldset>
  );
}

/** Origin badge: FIXTURE is loud, MANUAL is marked, source data carries no extra badge here. */
export function OriginBadge({ origin }: { origin: string }) {
  if (origin === "fixture") return <FreshnessBadge freshness="FIXTURE" />;
  if (origin === "manual") return <FreshnessBadge freshness="MANUAL" />;
  return <span className="badge badge--neutral">Official source feed</span>;
}

// Staleness thresholds for manual entries (backend services/instruments.py: TBILL_FRESH_DAYS, FD_RATE_STALE_DAYS;
// ux-design §4.4). Shown as calendar-day age; the engine enforces the same limits when it evaluates.
export const TBILL_FRESH_DAYS = 7;
export const FD_RATE_STALE_DAYS = 30;

export function ManualAge({ asOf, staleAfter, fixture }: { asOf: string; staleAfter: number; fixture: boolean }) {
  if (fixture) return <FreshnessBadge freshness="FIXTURE" date={asOf} />;
  const age = daysBetween(asOf, todayIst());
  return (
    <span className="row-tight">
      {age > staleAfter ? <FreshnessBadge freshness="STALE" date={asOf} /> : <FreshnessBadge freshness="MANUAL" date={asOf} />}
      <span className="small subtle">
        {age < 0 ? "dated in the future — check the as-of date" : `${age} day${age === 1 ? "" : "s"} old`}
        {age > staleAfter ? ` (older than ${staleAfter} days)` : ""}
      </span>
    </span>
  );
}

function CiteLink({ url }: { url: string | null | undefined }) {
  if (!url) return <span className="subtle">none stored</span>;
  if (!url.startsWith("https://")) return <span className="mono small">{url}</span>;
  let host = url;
  try {
    host = new URL(url).hostname;
  } catch {
    /* keep the raw text */
  }
  return (
    <a href={url} target="_blank" rel="noreferrer noopener">
      {host}
    </a>
  );
}

// ------------------------------------------------------------------ list rows

type Deletable = Pick<InstrumentListItem, "instrument_id" | "name" | "origin" | "fixture">;

function DeleteButton({ item, onDeleted }: { item: Deletable; onDeleted: (msg: string) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (item.origin !== "manual") return <span className="small subtle">{item.fixture ? "fixture" : "source data"}</span>;
  async function go() {
    setPending(true);
    setErr(null);
    try {
      await api(`/api/instruments/${encodeURIComponent(item.instrument_id)}`, { method: "DELETE" });
      onDeleted(`Deleted ${item.name}.`);
    } catch (e) {
      setErr(errorText(e));
      setPending(false);
    }
  }
  return (
    <span className="row-tight">
      {confirming ? (
        <>
          <button type="button" className="btn btn--danger" onClick={go} disabled={pending} aria-label={`Confirm delete ${item.name}`}>
            {pending ? "Deleting…" : "Confirm delete"}
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => setConfirming(false)} disabled={pending}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" className="btn" onClick={() => setConfirming(true)} aria-label={`Delete ${item.name}`}>
          Delete
        </button>
      )}
      {err ? (
        <span className="field-error" role="alert">
          {err}
        </span>
      ) : null}
    </span>
  );
}

function TBillRow({ item, onDeleted }: { item: InstrumentListItem; onDeleted: (m: string) => void }) {
  const d = useApi<InstrumentDetailResponse>(`/api/instruments/${encodeURIComponent(item.instrument_id)}`);
  const pts = d.data?.series.points ?? [];
  const last = pts.length ? pts[pts.length - 1] : undefined;
  const maturity = d.data?.bond_terms?.maturity_date;
  const today = todayIst();
  return (
    <tr className={item.fixture ? "fixture-zone" : undefined}>
      <td>
        <Link to={`/i/${encodeURIComponent(item.instrument_id)}`}>{item.name}</Link>
        <div className="row-tight small">
          <OriginBadge origin={item.origin} />
        </div>
      </td>
      {d.loading ? (
        <td colSpan={4} aria-busy="true">
          <span className="subtle">—</span>
        </td>
      ) : d.error ? (
        <td colSpan={4} className="small">
          Details could not be loaded: {errorText(d.error)}
        </td>
      ) : (
        <>
          <td className="num">
            {last ? ratePct(last.value) : <span className="subtle">no yield stored</span>}
            <div className="small subtle">money-market yield, ACT/365 (RBI)</div>
          </td>
          <td>
            {maturity ? (
              <>
                {dateLabel(maturity)}
                {daysBetween(today, maturity) < 0 ? <div className="small field-error">matured</div> : null}
              </>
            ) : (
              "—"
            )}
          </td>
          <td>{last ? <ManualAge asOf={last.observation_date} staleAfter={TBILL_FRESH_DAYS} fixture={item.fixture} /> : "—"}</td>
          <td>
            <CiteLink url={last?.source_url} />
          </td>
        </>
      )}
      <td>
        <DeleteButton item={item} onDeleted={onDeleted} />
      </td>
    </tr>
  );
}

function FdRow({ item, onDeleted }: { item: InstrumentListItem; onDeleted: (m: string) => void }) {
  const d = useApi<InstrumentDetailResponse>(`/api/instruments/${encodeURIComponent(item.instrument_id)}`);
  const t = d.data?.deposit_terms;
  return (
    <tr className={item.fixture ? "fixture-zone" : undefined}>
      <td>
        <Link to={`/i/${encodeURIComponent(item.instrument_id)}`}>{item.name}</Link>
        <div className="row-tight small">
          <OriginBadge origin={item.origin} />
        </div>
      </td>
      {d.loading ? (
        <td colSpan={5} aria-busy="true">
          <span className="subtle">—</span>
        </td>
      ) : d.error || !t ? (
        <td colSpan={5} className="small">
          {d.error ? `Details could not be loaded: ${errorText(d.error)}` : "No deposit terms stored."}
        </td>
      ) : (
        <>
          <td className="num">
            {ratePct(t.rate)}
            <div className="small subtle">a year, {t.compounding} compounding</div>
          </td>
          <td className="num">{t.tenure_days} days</td>
          <td className="small">
            Early-exit penalty: {t.premature_penalty === null ? "not entered" : ratePct(t.premature_penalty)}
            <br />
            DICGC-eligible institution type: {t.dicgc_eligible ? "yes" : "no"}
          </td>
          <td>
            <ManualAge asOf={t.rate_as_of} staleAfter={FD_RATE_STALE_DAYS} fixture={item.fixture} />
          </td>
          <td>
            <CiteLink url={t.citation_url} />
          </td>
        </>
      )}
      <td>
        <DeleteButton item={item} onDeleted={onDeleted} />
      </td>
    </tr>
  );
}

function ListTable({ kind, caption, head, rows }: { kind: string; caption: string; head: string[]; rows: ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="table" data-kind={kind}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={h} scope="col" className={i === 1 ? "num" : undefined}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ forms

const OFFICIAL_SOURCE_NOTE = (
  <p className="callout small">
    Values here are entered by you, not fetched. Copy the yield or rate from an official page only — the RBI press release
    with the auction result for a T-bill, or the bank&apos;s own published interest-rate page for a deposit. The page URL
    and the as-of date are stored with the value as its citation, and the value is shown as MANUAL ENTRY everywhere it
    is used.
  </p>
);

function SubmitFeedback({ error, ok, fieldErrors }: { error: unknown; ok: string | null; fieldErrors: Record<string, string> | null }) {
  if (ok)
    return (
      <p className="callout" role="status">
        {ok}
      </p>
    );
  if (!error) return null;
  if (fieldErrors) {
    const n = Object.keys(fieldErrors).length;
    return (
      <p className="callout callout--stale" role="alert">
        Not saved: the server rejected {n} field{n === 1 ? "" : "s"} (marked below).
        {fieldErrors["_"] ? ` ${fieldErrors["_"]}` : ""}
      </p>
    );
  }
  return (
    <p className="callout callout--stale" role="alert">
      Not saved: {errorText(error)}
    </p>
  );
}

function TBillForm({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState("");
  const [tenor, setTenor] = useState<TBillIn["tenor"]>("182");
  const [maturity, setMaturity] = useState("");
  const [yieldPct, setYieldPct] = useState("");
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [local, setLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const server = validationErrors(error);
  const errs = { ...(server ?? {}), ...local };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setOk(null);
    const problems: Record<string, string> = { ...citationProblems(cite) };
    if (name.trim().length < 3) problems["name"] = "Enter a name of at least 3 characters.";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(maturity)) problems["maturity"] = "Enter the maturity date.";
    const fr = percentToFraction(yieldPct);
    if (fr === null || fr === "invalid") problems["yield_fraction"] = "Enter the yield as a plain number of percent, e.g. 6.54.";
    setLocal(problems);
    if (Object.keys(problems).length || fr === null || fr === "invalid") return;
    const body: TBillIn = { name: name.trim(), tenor, maturity, yield_fraction: fr, citation: citationBody(cite) };
    setPending(true);
    setError(null);
    try {
      const out = await api<{ instrument_id: string }>("/api/instruments/tbill", { method: "POST", body });
      setOk(`Saved as ${out.instrument_id}.`);
      setName("");
      setYieldPct("");
      setMaturity("");
      setCite(EMPTY_CITATION);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="tbill-form-title">
      <h2 id="tbill-form-title">Add a T-bill</h2>
      {OFFICIAL_SOURCE_NOTE}
      <div className="field">
        <label htmlFor="tb-name">Name</label>
        <input id="tb-name" className="input-wide" value={name} onChange={(e) => setName(e.target.value)} maxLength={120}
          aria-invalid={Boolean(errs["name"])} aria-describedby="tb-name-err" placeholder="e.g. 182-day T-bill, auction of 14-Oct-2026" />
        <FieldError id="tb-name-err" msg={errs["name"]} />
      </div>
      <div className="field">
        <label htmlFor="tb-tenor">Tenor</label>
        <select id="tb-tenor" value={tenor} onChange={(e) => setTenor(e.target.value as TBillIn["tenor"])}>
          <option value="91">91 days</option>
          <option value="182">182 days</option>
          <option value="364">364 days</option>
        </select>
        <FieldError id="tb-tenor-err" msg={errs["tenor"]} />
      </div>
      <div className="field">
        <label htmlFor="tb-maturity">Maturity date</label>
        <input id="tb-maturity" type="date" value={maturity} onChange={(e) => setMaturity(e.target.value)}
          aria-invalid={Boolean(errs["maturity"])} aria-describedby="tb-maturity-err" />
        <FieldError id="tb-maturity-err" msg={errs["maturity"]} />
      </div>
      <div className="field">
        <label htmlFor="tb-yield">Cut-off yield (% a year)</label>
        <span className="pct">
        <input id="tb-yield" inputMode="decimal" value={yieldPct} onChange={(e) => setYieldPct(e.target.value)}
          aria-invalid={Boolean(errs["yield_fraction"])} aria-describedby="tb-yield-hint tb-yield-err" />
        </span>
        <div id="tb-yield-hint" className="hint">
          As printed in the RBI press release (money-market yield, ACT/365). Must be above 0 % and below 50 %.
        </div>
        <FieldError id="tb-yield-err" msg={errs["yield_fraction"]} />
      </div>
      <CitationFields prefix="tb" value={cite} onChange={setCite} errors={errs} />
      <p className="small subtle">A second entry with the same tenor and maturity date replaces the earlier yield entry for that date.</p>
      <SubmitFeedback error={error} ok={ok} fieldErrors={server} />
      <button type="submit" className="btn btn--primary" disabled={pending}>
        {pending ? "Saving…" : "Save T-bill"}
      </button>
    </form>
  );
}

const INSTITUTION_TYPES: [InstitutionType, string][] = [
  ["bank", "Bank"],
  ["small_finance_bank", "Small finance bank"],
  ["nbfc", "NBFC"],
  ["hfc", "Housing finance company"],
  ["post_office", "Post office"],
];

function FdForm({ onSaved }: { onSaved: () => void }) {
  const [institution, setInstitution] = useState("");
  const [itype, setItype] = useState<InstitutionType>("bank");
  const [ratePctText, setRatePct] = useState("");
  const [tenure, setTenure] = useState("");
  const [penaltyPct, setPenaltyPct] = useState("");
  const [existing, setExisting] = useState("0");
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [local, setLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const server = validationErrors(error);
  const errs = { ...(server ?? {}), ...local };
  const existingClean = existing.replace(/[,\s₹]/g, "");
  const existingValid = /^\d+(\.\d+)?$/.test(existingClean);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setOk(null);
    const problems: Record<string, string> = { ...citationProblems(cite) };
    if (institution.trim().length < 2) problems["institution"] = "Enter the institution name.";
    const rate = percentToFraction(ratePctText);
    if (rate === null || rate === "invalid") problems["rate"] = "Enter the rate as a plain number of percent, e.g. 7.25.";
    const penalty = percentToFraction(penaltyPct);
    if (penalty === "invalid") problems["premature_penalty"] = "Enter the penalty as a plain number of percent, or leave it empty.";
    if (!/^\d+$/.test(tenure.trim())) problems["tenure_days"] = "Enter the tenure as a whole number of days (7 to 3650).";
    if (!existingValid) problems["existing_deposits_at_institution"] = "Enter an amount in rupees (digits only), or 0.";
    setLocal(problems);
    if (Object.keys(problems).length || rate === null || rate === "invalid" || penalty === "invalid") return;
    const body: FDIn = {
      institution: institution.trim(),
      institution_type: itype,
      rate,
      tenure_days: Number.parseInt(tenure.trim(), 10),
      premature_penalty: penalty,
      existing_deposits_at_institution: existingClean,
      citation: citationBody(cite),
    };
    setPending(true);
    setError(null);
    try {
      const out = await api<{ instrument_id: string }>("/api/instruments/fd", { method: "POST", body });
      setOk(`Saved as ${out.instrument_id}.`);
      setInstitution("");
      setRatePct("");
      setTenure("");
      setPenaltyPct("");
      setExisting("0");
      setCite(EMPTY_CITATION);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="fd-form-title">
      <h2 id="fd-form-title">Add a fixed deposit</h2>
      {OFFICIAL_SOURCE_NOTE}
      <div className="field">
        <label htmlFor="fd-inst">Institution</label>
        <input id="fd-inst" className="input-wide" value={institution} onChange={(e) => setInstitution(e.target.value)} maxLength={120}
          aria-invalid={Boolean(errs["institution"])} aria-describedby="fd-inst-err" />
        <FieldError id="fd-inst-err" msg={errs["institution"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-type">Institution type</label>
        <select id="fd-type" value={itype} onChange={(e) => setItype(e.target.value as InstitutionType)}>
          {INSTITUTION_TYPES.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <div className="hint">Only banks and small finance banks are treated as DICGC-eligible.</div>
        <FieldError id="fd-type-err" msg={errs["institution_type"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-rate">Interest rate (% a year)</label>
        <span className="pct">
        <input id="fd-rate" inputMode="decimal" value={ratePctText} onChange={(e) => setRatePct(e.target.value)}
          aria-invalid={Boolean(errs["rate"])} aria-describedby="fd-rate-hint fd-rate-err" />
        </span>
        <div id="fd-rate-hint" className="hint">
          The card rate for this exact tenure from the bank&apos;s rate page. Stored with quarterly compounding. Below 30 %.
        </div>
        <FieldError id="fd-rate-err" msg={errs["rate"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-tenure">Tenure (days)</label>
        <input id="fd-tenure" className="input-short" inputMode="numeric" value={tenure} onChange={(e) => setTenure(e.target.value)}
          aria-invalid={Boolean(errs["tenure_days"])} aria-describedby="fd-tenure-err" />
        <FieldError id="fd-tenure-err" msg={errs["tenure_days"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-penalty">Premature-withdrawal penalty (percentage points) — optional</label>
        <span className="pct">
        <input id="fd-penalty" inputMode="decimal" value={penaltyPct} onChange={(e) => setPenaltyPct(e.target.value)}
          aria-invalid={Boolean(errs["premature_penalty"])} aria-describedby="fd-penalty-hint fd-penalty-err" />
        </span>
        <div id="fd-penalty-hint" className="hint">Leave empty if the bank page does not state it; it is then shown as unknown. Below 10.</div>
        <FieldError id="fd-penalty-err" msg={errs["premature_penalty"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-existing">Deposits you already hold at this institution (₹)</label>
        <span className="money">
        <input id="fd-existing" inputMode="decimal" value={existing} onChange={(e) => setExisting(e.target.value)}
          aria-invalid={Boolean(errs["existing_deposits_at_institution"])} aria-describedby="fd-existing-hint fd-existing-err" />
        </span>
        <div id="fd-existing-hint" className="hint">
          {existingValid ? inr(existingClean) : "Digits only."} Used to check the DICGC cover limit per institution.
        </div>
        <FieldError id="fd-existing-err" msg={errs["existing_deposits_at_institution"]} />
      </div>
      <CitationFields prefix="fd" value={cite} onChange={setCite} errors={errs} />
      <SubmitFeedback error={error} ok={ok} fieldErrors={server} />
      <button type="submit" className="btn btn--primary" disabled={pending}>
        {pending ? "Saving…" : "Save fixed deposit"}
      </button>
    </form>
  );
}

// ------------------------------------------------------------------ G-secs, SDLs, corporate bonds

/** ISO 6166 check: 2 letters + 9 alphanumerics + check digit (Luhn over letters expanded to A=10 … Z=35). */
export function isinProblem(raw: string): string | null {
  const isin = raw.trim().toUpperCase();
  if (!/^[A-Z]{2}[A-Z0-9]{9}[0-9]$/.test(isin)) return "Enter the 12-character ISIN exactly as on the official page.";
  const digits = isin
    .slice(0, -1)
    .split("")
    .map((c) => Number.parseInt(c, 36).toString())
    .join("");
  let total = 0;
  for (let i = 0; i < digits.length; i += 1) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 0) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    total += d;
  }
  return (10 - (total % 10)) % 10 === Number(isin[11]) ? null : "The ISIN check digit does not match — re-check it.";
}

const DECIMAL = /^\d+(\.\d+)?$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export const BOND_QUOTE_STALE_DAYS = 7; // backend services/instruments.py BOND_QUOTE_STALE_DAYS
export const RATING_STALE_DAYS = 365; // backend services/instruments.py RATING_STALE_DAYS

const BOND_KIND_LABEL: Record<BondKind, string> = { gsec: "G-sec", sdl: "SDL", corp_bond: "Corporate bond" };

function QuoteCell({ item }: { item: BondListItem }) {
  const q = item.quote;
  if (!q) return <span className="subtle">{item.quote_problem ?? "no quote stored"}</span>;
  const comp = q.convention?.match(/compounding=(\w+)/)?.[1];
  return (
    <>
      {q.kind === "clean_price" ? `${roundHalfUp(q.value, 4)} per ₹100` : `${ratePct(q.value)} YTM`}
      <div className="small subtle">{q.kind === "clean_price" ? "clean price" : `yield, ${comp ?? "compounding not recorded"}`}</div>
    </>
  );
}

function QuoteAge({ item }: { item: BondListItem }) {
  const q = item.quote;
  if (!q) return <>—</>;
  if (item.fixture) return <FreshnessBadge freshness="FIXTURE" date={q.quote_date} />;
  const stale = q.freshness === "STALE" || q.age_days > BOND_QUOTE_STALE_DAYS || q.age_days < 0;
  return (
    <span className="row-tight">
      <FreshnessBadge freshness={stale ? "STALE" : "MANUAL"} date={q.quote_date} />
      <span className="small subtle">
        {q.age_days < 0 ? "dated in the future — check the quote date" : `${q.age_days} day${q.age_days === 1 ? "" : "s"} old`}
        {stale && q.age_days >= 0 ? ` (older than ${BOND_QUOTE_STALE_DAYS} days: excluded)` : ""}
      </span>
      {item.quote_problem ? <span className="field-error">{item.quote_problem}</span> : null}
    </span>
  );
}

function RatingCell({ item }: { item: BondListItem }) {
  if (item.kind === "gsec") return <span className="small">Sovereign (Government of India)</span>;
  if (item.kind === "sdl") return <span className="small">State government (not sovereign; tier T2)</span>;
  const r = item.rating;
  if (!r) return <span className="field-error">No rating stored: excluded (MISSING_RATING)</span>;
  return (
    <span className="bond-rating">
      <strong>{r.rating}</strong> <span className="small">{r.agency ?? "agency not stored"}</span>
      <span className="row-tight small">
        {r.stale ? <FreshnessBadge freshness="STALE" date={r.rating_date} /> : <span>rated {dateLabel(r.rating_date)}</span>}
        <span className="subtle">
          {r.age_days} days old{r.stale ? ` (older than ${RATING_STALE_DAYS} days: excluded)` : ""}
        </span>
      </span>
      <span className="small">
        Rationale: <CiteLink url={r.citation_url} />
      </span>
    </span>
  );
}

function BondRow({ item, onDeleted }: { item: BondListItem; onDeleted: (m: string) => void }) {
  const t = item.terms;
  return (
    <tr className={item.fixture ? "fixture-zone" : undefined}>
      <td>
        <Link to={`/i/${encodeURIComponent(item.instrument_id)}`}>{item.name}</Link>
        <div className="row-tight small">
          <OriginBadge origin={item.origin} />
          <span className="badge badge--neutral">{BOND_KIND_LABEL[item.kind]}</span>
          {item.isin ? <span className="mono subtle">{item.isin}</span> : null}
        </div>
      </td>
      <td className="num">
        {t ? (
          <>
            {ratePct(t.coupon_rate)} coupon
            <div className="small subtle">
              matures {dateLabel(t.maturity)} · {t.day_count}
              {t.calls.length ? ` · callable (${t.calls.length})` : ""}
            </div>
          </>
        ) : (
          <span className="subtle">terms not stored</span>
        )}
      </td>
      <td className="num">
        <QuoteCell item={item} />
      </td>
      <td>
        <QuoteAge item={item} />
      </td>
      <td>
        <RatingCell item={item} />
      </td>
      <td>
        <CiteLink url={item.quote?.citation_url} />
      </td>
      <td>
        <DeleteButton item={item} onDeleted={onDeleted} />
      </td>
    </tr>
  );
}

interface QuoteState {
  mode: "clean_price" | "ytm";
  value: string;
  date: string;
}

/** Shared bond fields → (body fragment, problems). Percent inputs become fractions; nothing is defaulted. */
function commonBondFields(f: {
  issuer: string;
  isin: string;
  couponPct: string;
  issue: string;
  maturity: string;
  face: string;
  quote: QuoteState;
  spreadPct: string;
  cite: CitationState;
}): { body: Record<string, unknown>; problems: Record<string, string> } {
  const problems: Record<string, string> = { ...citationProblems(f.cite) };
  if (f.issuer.trim().length < 2) problems["issuer"] = "Enter the issuer as named on the official page.";
  const isinErr = isinProblem(f.isin);
  if (isinErr) problems["isin"] = isinErr;
  const coupon = percentToFraction(f.couponPct);
  if (coupon === null || coupon === "invalid") problems["coupon_rate"] = "Enter the coupon as a plain number of percent, e.g. 7.10.";
  if (!ISO_DATE.test(f.issue)) problems["issue_date"] = "Enter the issue date.";
  if (!ISO_DATE.test(f.maturity)) problems["maturity"] = "Enter the maturity date.";
  else if (ISO_DATE.test(f.issue) && f.maturity <= f.issue) problems["maturity"] = "Maturity must be after the issue date.";
  const face = f.face.replace(/[,\s₹]/g, "");
  if (!DECIMAL.test(face) || Number(face) === 0) problems["face_value"] = "Enter the face value of one bond in rupees.";
  if (!ISO_DATE.test(f.quote.date)) problems["quote_date"] = "Enter the date the price or yield applies to.";
  let quoteValue: string | null = null;
  if (f.quote.mode === "clean_price") {
    if (!DECIMAL.test(f.quote.value.trim())) problems["clean_price"] = "Enter the clean price per ₹100 face, e.g. 99.85.";
    else quoteValue = f.quote.value.trim();
  } else {
    const y = percentToFraction(f.quote.value);
    if (y === null || y === "invalid") problems["ytm"] = "Enter the yield as a plain number of percent, e.g. 7.12.";
    else quoteValue = y;
  }
  const spread = percentToFraction(f.spreadPct);
  if (spread === "invalid") problems["transaction_spread"] = "Enter the spread as a plain number of percent, or leave it empty.";
  const body: Record<string, unknown> = {
    issuer: f.issuer.trim(),
    isin: f.isin.trim().toUpperCase(),
    coupon_rate: coupon,
    issue_date: f.issue,
    maturity: f.maturity,
    face_value: face,
    clean_price: f.quote.mode === "clean_price" ? quoteValue : null,
    ytm: f.quote.mode === "ytm" ? quoteValue : null,
    quote_date: f.quote.date,
    transaction_spread: spread === "invalid" ? null : spread,
    citation: citationBody(f.cite),
  };
  return { body, problems };
}

function TextField(props: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  err: string | undefined;
  hint?: ReactNode;
  type?: "text" | "date";
  wrap?: "pct" | "money";
  wide?: boolean;
  inputMode?: "decimal" | "numeric" | "text";
}) {
  const { id, label, value, onChange, err, hint, type = "text", wrap, wide, inputMode } = props;
  const input = (
    <input id={id} type={type} className={wide ? "input-wide" : undefined} value={value} inputMode={inputMode}
      onChange={(e) => onChange(e.target.value)} aria-invalid={Boolean(err)}
      aria-describedby={`${hint ? `${id}-hint ` : ""}${id}-err`} />
  );
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {wrap ? <span className={wrap}>{input}</span> : input}
      {hint ? (
        <div id={`${id}-hint`} className="hint">
          {hint}
        </div>
      ) : null}
      <FieldError id={`${id}-err`} msg={err} />
    </div>
  );
}

function QuoteFields({ prefix, quote, onChange, errs, ytmNote }: {
  prefix: string;
  quote: QuoteState;
  onChange: (q: QuoteState) => void;
  errs: Record<string, string>;
  ytmNote: ReactNode;
}) {
  return (
    <fieldset className="field bond-quote">
      <legend>Price or yield (enter exactly one)</legend>
      <div className="row-tight" role="radiogroup" aria-label="Quote type">
        <label>
          <input type="radio" name={`${prefix}-quote-mode`} checked={quote.mode === "clean_price"}
            onChange={() => onChange({ ...quote, mode: "clean_price", value: "" })} /> Clean price per ₹100
        </label>
        <label>
          <input type="radio" name={`${prefix}-quote-mode`} checked={quote.mode === "ytm"}
            onChange={() => onChange({ ...quote, mode: "ytm", value: "" })} /> Yield to maturity
        </label>
      </div>
      {quote.mode === "clean_price" ? (
        <TextField id={`${prefix}-price`} label="Clean price (per ₹100 face)" value={quote.value} inputMode="decimal"
          onChange={(v) => onChange({ ...quote, value: v })} err={errs["clean_price"]}
          hint="The quoted price without accrued interest. Accrued interest is added by the engine." />
      ) : (
        <TextField id={`${prefix}-ytm`} label="Yield to maturity (% a year)" value={quote.value} wrap="pct" inputMode="decimal"
          onChange={(v) => onChange({ ...quote, value: v })} err={errs["ytm"]} hint={ytmNote} />
      )}
      <TextField id={`${prefix}-qdate`} type="date" label="Date of this price or yield" value={quote.date}
        onChange={(v) => onChange({ ...quote, date: v })} err={errs["quote_date"]}
        hint={`Quotes older than ${BOND_QUOTE_STALE_DAYS} days are excluded as STALE_DATA.`} />
    </fieldset>
  );
}

const EMPTY_QUOTE: QuoteState = { mode: "clean_price", value: "", date: "" };
const BOND_SOURCE_NOTE = (
  <p className="callout small">
    Nothing about a bond is fetched. Copy every value from an official page — the RBI notification or RBI Retail Direct for
    a G-sec or SDL, the exchange or information memorandum for a corporate bond, and the rating agency&apos;s rationale
    for a rating. Each value is stored with its page URL and date, and shown as MANUAL ENTRY wherever it is used.
  </p>
);

function useSubmit(path: string, onSaved: () => void) {
  const [local, setLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const server = validationErrors(error);
  const errs = { ...(server ?? {}), ...local };
  async function send(body: unknown, problems: Record<string, string>, reset: () => void) {
    setOk(null);
    setLocal(problems);
    if (Object.keys(problems).length) return;
    setPending(true);
    setError(null);
    try {
      const out = await api<{ instrument_id: string }>(path, { method: "POST", body });
      setOk(`Saved as ${out.instrument_id}.`);
      reset();
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }
  return { errs, server, error, pending, ok, send };
}

function GsecForm({ onSaved }: { onSaved: () => void }) {
  const [kind, setKind] = useState<GsecIn["kind"]>("gsec");
  const [issuer, setIssuer] = useState("Government of India");
  const [isin, setIsin] = useState("");
  const [couponPct, setCouponPct] = useState("");
  const [issue, setIssue] = useState("");
  const [maturity, setMaturity] = useState("");
  const [face, setFace] = useState("100");
  const [quote, setQuote] = useState<QuoteState>(EMPTY_QUOTE);
  const [spreadPct, setSpreadPct] = useState("");
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const s = useSubmit("/api/instruments/gsec", onSaved);
  const errs = s.errs;

  function submit(e: FormEvent) {
    e.preventDefault();
    const { body, problems } = commonBondFields({ issuer, isin, couponPct, issue, maturity, face, quote, spreadPct, cite });
    const full = { ...body, kind, frequency: 2 } as unknown as GsecIn;
    void s.send(full, problems, () => {
      setIsin("");
      setCouponPct("");
      setIssue("");
      setMaturity("");
      setQuote(EMPTY_QUOTE);
      setSpreadPct("");
      setCite(EMPTY_CITATION);
    });
  }

  return (
    <form className="card bond-form" onSubmit={submit} noValidate aria-labelledby="gsec-form-title">
      <h2 id="gsec-form-title">Add a G-sec or SDL</h2>
      {BOND_SOURCE_NOTE}
      <div className="field">
        <label htmlFor="gs-kind">Type</label>
        <select id="gs-kind" value={kind} onChange={(e) => {
          const k = e.target.value as GsecIn["kind"];
          setKind(k);
          setIssuer(k === "gsec" ? "Government of India" : "");
        }}>
          <option value="gsec">Central Government security (G-sec)</option>
          <option value="sdl">State Development Loan (SDL)</option>
        </select>
        <div className="hint">Semi-annual coupons, 30E/360 (RBI). SDLs are state credit: ranked as T2, never as sovereign.</div>
      </div>
      <TextField id="gs-issuer" label="Issuer" value={issuer} onChange={setIssuer} err={errs["issuer"]} wide
        hint={kind === "sdl" ? "The state, e.g. as printed in the RBI auction notification." : undefined} />
      <TextField id="gs-isin" label="ISIN" value={isin} onChange={setIsin} err={errs["isin"]} />
      <TextField id="gs-coupon" label="Coupon (% a year)" value={couponPct} onChange={setCouponPct} err={errs["coupon_rate"]} wrap="pct" inputMode="decimal" />
      <div className="row">
        <TextField id="gs-issue" type="date" label="Issue date" value={issue} onChange={setIssue} err={errs["issue_date"]} />
        <TextField id="gs-maturity" type="date" label="Maturity date" value={maturity} onChange={setMaturity} err={errs["maturity"]} />
      </div>
      <TextField id="gs-face" label="Face value of one unit (₹)" value={face} onChange={setFace} err={errs["face_value"]} wrap="money" inputMode="decimal"
        hint="₹100 for G-secs and SDLs. Only whole units are bought; the remainder stays as cash." />
      <QuoteFields prefix="gs" quote={quote} onChange={setQuote} errs={errs}
        ytmNote="Semi-annual bond-equivalent yield, as RBI and CCIL quote G-secs." />
      <TextField id="gs-spread" label="Transaction spread (% of the clean price) — optional" value={spreadPct} onChange={setSpreadPct}
        err={errs["transaction_spread"]} wrap="pct" inputMode="decimal"
        hint="Leave empty if unknown: it is then flagged TRANSACTION_COST_UNKNOWN, never silently assumed to be 0." />
      <CitationFields prefix="gs" value={cite} onChange={setCite} errors={errs} />
      <SubmitFeedback error={s.error} ok={s.ok} fieldErrors={s.server} />
      <button type="submit" className="btn btn--primary" disabled={s.pending}>
        {s.pending ? "Saving…" : "Save G-sec / SDL"}
      </button>
    </form>
  );
}

function CorporateBondForm({ onSaved }: { onSaved: () => void }) {
  const [issuer, setIssuer] = useState("");
  const [isin, setIsin] = useState("");
  const [couponPct, setCouponPct] = useState("");
  const [frequency, setFrequency] = useState<CorporateBondIn["frequency"]>(1);
  const [issue, setIssue] = useState("");
  const [maturity, setMaturity] = useState("");
  const [face, setFace] = useState("");
  const [quote, setQuote] = useState<QuoteState>(EMPTY_QUOTE);
  const [compounding, setCompounding] = useState<YieldCompounding | "">("");
  const [spreadPct, setSpreadPct] = useState("");
  const [rating, setRating] = useState<CorporateRating | "">("");
  const [agency, setAgency] = useState<RatingAgency | "">("");
  const [ratingDate, setRatingDate] = useState("");
  const [ratingCite, setRatingCite] = useState<CitationState>(EMPTY_CITATION);
  const [listed, setListed] = useState(true);
  const [secured, setSecured] = useState<"" | "yes" | "no">("");
  const [recordDays, setRecordDays] = useState("");
  const [calls, setCalls] = useState<CallIn[]>([]);
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const s = useSubmit("/api/instruments/corp-bond", onSaved);
  // Rating-citation errors arrive as "rating_citation.url" from the server and locally; CitationFields reads "citation.*".
  const ratingCiteErrs = Object.fromEntries(
    Object.entries(s.errs)
      .filter(([k]) => k.startsWith("rating_citation."))
      .map(([k, v]) => [k.replace("rating_citation.", "citation."), v]),
  );
  const errs = s.errs;

  function submit(e: FormEvent) {
    e.preventDefault();
    const { body, problems } = commonBondFields({ issuer, isin, couponPct, issue, maturity, face, quote, spreadPct, cite });
    for (const [k, v] of Object.entries(citationProblems(ratingCite))) problems[k.replace("citation.", "rating_citation.")] = v;
    if (!rating) problems["rating"] = "Choose the rating from the agency's rationale.";
    if (!agency) problems["rating_agency"] = "Choose the rating agency.";
    if (!ISO_DATE.test(ratingDate)) problems["rating_date"] = "Enter the date of the rating action.";
    if (secured === "") problems["secured"] = "State whether the bond is secured (term sheet).";
    if (!/^\d+$/.test(recordDays.trim()) || Number(recordDays) > 30)
      problems["record_date_days"] = "Enter the record-date gap in days (0 to 30) from the term sheet.";
    if (quote.mode === "ytm" && !compounding) problems["ytm_compounding"] = "Choose how the quoted yield is compounded.";
    calls.forEach((c, i) => {
      if (!ISO_DATE.test(c.call_date)) problems[`call_schedule.${i}.call_date`] = "Enter the call date.";
      if (!DECIMAL.test(c.call_price.trim())) problems[`call_schedule.${i}.call_price`] = "Enter the call price per ₹100.";
    });
    const full = {
      ...body,
      frequency,
      ytm_compounding: quote.mode === "ytm" ? compounding || null : null,
      rating,
      rating_agency: agency,
      rating_date: ratingDate,
      rating_citation: citationBody(ratingCite),
      listed,
      secured: secured === "yes",
      record_date_days: Number.parseInt(recordDays.trim() || "0", 10),
      call_schedule: calls.map((c) => ({ call_date: c.call_date, call_price: c.call_price.trim() })),
    } as unknown as CorporateBondIn;
    void s.send(full, problems, () => {
      setIsin("");
      setCouponPct("");
      setQuote(EMPTY_QUOTE);
      setCalls([]);
      setCite(EMPTY_CITATION);
      setRatingCite(EMPTY_CITATION);
    });
  }

  return (
    <form className="card bond-form" onSubmit={submit} noValidate aria-labelledby="corp-form-title">
      <h2 id="corp-form-title">Add a corporate bond</h2>
      {BOND_SOURCE_NOTE}
      <TextField id="cb-issuer" label="Issuer" value={issuer} onChange={setIssuer} err={errs["issuer"]} wide />
      <TextField id="cb-isin" label="ISIN" value={isin} onChange={setIsin} err={errs["isin"]} />
      <div className="row">
        <TextField id="cb-coupon" label="Coupon (% a year)" value={couponPct} onChange={setCouponPct} err={errs["coupon_rate"]} wrap="pct" inputMode="decimal" />
        <div className="field">
          <label htmlFor="cb-frequency">Coupon frequency</label>
          <select id="cb-frequency" value={frequency} onChange={(e) => setFrequency(Number(e.target.value) as CorporateBondIn["frequency"])}>
            <option value={1}>Annual</option>
            <option value={2}>Semi-annual</option>
            <option value={4}>Quarterly</option>
            <option value={12}>Monthly</option>
          </select>
          <div className="hint">Day count: SEBI Actual/Actual.</div>
        </div>
      </div>
      <div className="row">
        <TextField id="cb-issue" type="date" label="Issue date" value={issue} onChange={setIssue} err={errs["issue_date"]} />
        <TextField id="cb-maturity" type="date" label="Maturity date" value={maturity} onChange={setMaturity} err={errs["maturity"]} />
      </div>
      <TextField id="cb-face" label="Face value of one bond (₹)" value={face} onChange={setFace} err={errs["face_value"]} wrap="money" inputMode="decimal"
        hint="From the term sheet, e.g. ₹1,000, ₹10,000 or ₹1,00,000. Only whole bonds are bought." />
      <QuoteFields prefix="cb" quote={quote} onChange={setQuote} errs={errs}
        ytmNote="Corporate yields are quoted with different compounding conventions; choose the one the page states." />
      {quote.mode === "ytm" ? (
        <div className="field">
          <label htmlFor="cb-comp">Yield compounding</label>
          <select id="cb-comp" value={compounding} onChange={(e) => setCompounding(e.target.value as YieldCompounding | "")}
            aria-invalid={Boolean(errs["ytm_compounding"])} aria-describedby="cb-comp-err">
            <option value="">Choose…</option>
            <option value="annual">Annual</option>
            <option value="semiannual">Semi-annual</option>
            <option value="quarterly">Quarterly</option>
            <option value="monthly">Monthly</option>
          </select>
          <FieldError id="cb-comp-err" msg={errs["ytm_compounding"]} />
        </div>
      ) : null}
      <TextField id="cb-spread" label="Transaction spread (% of the clean price) — optional" value={spreadPct} onChange={setSpreadPct}
        err={errs["transaction_spread"]} wrap="pct" inputMode="decimal"
        hint="Leave empty if unknown: it is then flagged TRANSACTION_COST_UNKNOWN, never silently assumed to be 0." />
      <fieldset className="field bond-rating-fields">
        <legend>Credit rating (required)</legend>
        <div className="row">
          <div className="field">
            <label htmlFor="cb-rating">Rating</label>
            <select id="cb-rating" value={rating} onChange={(e) => setRating(e.target.value as CorporateRating | "")}
              aria-invalid={Boolean(errs["rating"])} aria-describedby="cb-rating-err">
              <option value="">Choose…</option>
              {CORPORATE_RATINGS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <FieldError id="cb-rating-err" msg={errs["rating"]} />
          </div>
          <div className="field">
            <label htmlFor="cb-agency">Agency</label>
            <select id="cb-agency" value={agency} onChange={(e) => setAgency(e.target.value as RatingAgency | "")}
              aria-invalid={Boolean(errs["rating_agency"])} aria-describedby="cb-agency-err">
              <option value="">Choose…</option>
              {RATING_AGENCIES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <FieldError id="cb-agency-err" msg={errs["rating_agency"]} />
          </div>
          <TextField id="cb-rdate" type="date" label="Rating action date" value={ratingDate} onChange={setRatingDate} err={errs["rating_date"]}
            hint={`Ratings older than ${RATING_STALE_DAYS} days are excluded as STALE_RATING.`} />
        </div>
        <CitationFields prefix="cb-rating-cite" value={ratingCite} onChange={setRatingCite} errors={ratingCiteErrs} />
      </fieldset>
      <div className="row">
        <div className="field">
          <label htmlFor="cb-listed">
            <input id="cb-listed" type="checkbox" checked={listed} onChange={(e) => setListed(e.target.checked)} /> Listed on an exchange
          </label>
          <div className="hint">Unlisted bonds are only considered when held to maturity (no exchange exit).</div>
        </div>
        <div className="field">
          <label htmlFor="cb-secured">Secured?</label>
          <select id="cb-secured" value={secured} onChange={(e) => setSecured(e.target.value as "" | "yes" | "no")}
            aria-invalid={Boolean(errs["secured"])} aria-describedby="cb-secured-err">
            <option value="">Choose…</option>
            <option value="yes">Secured</option>
            <option value="no">Unsecured</option>
          </select>
          <FieldError id="cb-secured-err" msg={errs["secured"]} />
        </div>
        <TextField id="cb-record" label="Record date (days before each coupon)" value={recordDays} onChange={setRecordDays}
          err={errs["record_date_days"]} inputMode="numeric" />
      </div>
      <fieldset className="field bond-calls">
        <legend>Call schedule (optional)</legend>
        {calls.length === 0 ? <p className="small subtle">No call option entered.</p> : null}
        {calls.map((c, i) => (
          <div className="row bond-call-row" key={i}>
            <TextField id={`cb-call-${i}-date`} type="date" label={`Call ${i + 1} date`} value={c.call_date}
              onChange={(v) => setCalls(calls.map((x, j) => (j === i ? { ...x, call_date: v } : x)))}
              err={errs[`call_schedule.${i}.call_date`]} />
            <TextField id={`cb-call-${i}-price`} label={`Call ${i + 1} price (per ₹100)`} value={c.call_price} inputMode="decimal"
              onChange={(v) => setCalls(calls.map((x, j) => (j === i ? { ...x, call_price: v } : x)))}
              err={errs[`call_schedule.${i}.call_price`]} />
            <button type="button" className="btn btn--ghost" onClick={() => setCalls(calls.filter((_, j) => j !== i))}
              aria-label={`Remove call ${i + 1}`}>
              Remove
            </button>
          </div>
        ))}
        <button type="button" className="btn" onClick={() => setCalls([...calls, { call_date: "", call_price: "" }])}>
          Add a call date
        </button>
        <div className="hint">A callable bond is evaluated on the worst of its maturity and call paths (the issuer decides).</div>
      </fieldset>
      <CitationFields prefix="cb" value={cite} onChange={setCite} errors={errs} />
      <SubmitFeedback error={s.error} ok={s.ok} fieldErrors={s.server} />
      <button type="submit" className="btn btn--primary" disabled={s.pending}>
        {s.pending ? "Saving…" : "Save corporate bond"}
      </button>
    </form>
  );
}

function BondsPanel() {
  const list = useApi<BondList>("/api/bonds");
  const [notice, setNotice] = useState<string | null>(null);
  const onDeleted = (m: string) => {
    setNotice(m);
    list.reload();
  };
  const onSaved = () => {
    setNotice(null);
    list.reload();
  };
  let body: ReactNode;
  if (list.loading) body = <Loading label="Loading bonds" />;
  else if (list.error) body = <ErrorState error={list.error} retry={list.reload} />;
  else if (!list.data || list.data.items.length === 0)
    body = (
      <Empty title="No G-secs, SDLs or corporate bonds stored yet">
        <p>Nothing is fetched automatically for bonds. Add one below from an official page; Discovery will then consider it.</p>
      </Empty>
    );
  else
    body = (
      <ListTable
        kind="bonds"
        caption="Stored G-secs, SDLs and corporate bonds"
        head={["Bond", "Terms", "Price or yield", "Quote date", "Rating", "Citation", "Action"]}
        rows={list.data.items.map((it) => (
          <BondRow key={it.instrument_id} item={it} onDeleted={onDeleted} />
        ))}
      />
    );
  return (
    <div className="bonds-panel">
      {notice ? (
        <p className="callout" role="status">
          {notice}
        </p>
      ) : null}
      {list.data?.items.some((i) => i.fixture) ? (
        <p className="callout callout--warn fixture-zone" role="note">
          <strong>FIXTURE data present.</strong> Rows marked FIXTURE are synthetic development data, not market data.
        </p>
      ) : null}
      {body}
      <p className="small subtle">
        Held to maturity (maturity on or before your withdrawal date) a bond gives contractual proceeds: G-secs are tier T1,
        SDLs and AAA corporates T2, lower ratings T3. A bond that matures after your withdrawal date must be sold early: its
        outcome is a band of stress scenarios (yield +1 / 0 / −1 percentage point), tier T3, and it is never used for capital
        preservation.
      </p>
      <div className="grid grid--2 bond-forms">
        <GsecForm onSaved={onSaved} />
        <CorporateBondForm onSaved={onSaved} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ page

type Tab = "tbill" | "fd" | "bonds";
const TABS: [Tab, string][] = [
  ["tbill", "T-bills"],
  ["fd", "Fixed deposits"],
  ["bonds", "G-secs & bonds"],
];

function KindList({ kind }: { kind: "tbill" | "fd" }) {
  const list = useApi<InstrumentList>(`/api/instruments?kind=${kind}`);
  const [notice, setNotice] = useState<string | null>(null);
  const label = kind === "tbill" ? "T-bills" : "fixed deposits";
  const onDeleted = (m: string) => {
    setNotice(m);
    list.reload();
  };
  const onSaved = () => {
    setNotice(null);
    list.reload();
  };
  let body: ReactNode;
  if (list.loading) body = <Loading label={`Loading ${label}`} />;
  else if (list.error) body = <ErrorState error={list.error} retry={list.reload} />;
  else if (!list.data || list.data.items.length === 0)
    body = (
      <Empty title={`No ${label} stored yet`}>
        <p>
          Nothing is fetched automatically for {label}. Add one below from an official page; it will then appear here and be
          considered by Discovery.
        </p>
      </Empty>
    );
  else
    body =
      kind === "tbill" ? (
        <ListTable
          kind={kind}
          caption="Stored T-bills"
          head={["T-bill", "Yield", "Maturity", "As of", "Citation", "Action"]}
          rows={list.data.items.map((it) => (
            <TBillRow key={it.instrument_id} item={it} onDeleted={onDeleted} />
          ))}
        />
      ) : (
        <ListTable
          kind={kind}
          caption="Stored fixed deposits"
          head={["Deposit", "Rate", "Tenure", "Terms", "Rate as of", "Citation", "Action"]}
          rows={list.data.items.map((it) => (
            <FdRow key={it.instrument_id} item={it} onDeleted={onDeleted} />
          ))}
        />
      );
  return (
    <>
      {notice ? (
        <p className="callout" role="status">
          {notice}
        </p>
      ) : null}
      {list.data?.items.some((i) => i.fixture) ? (
        <p className="callout callout--warn fixture-zone" role="note">
          <strong>FIXTURE data present.</strong> Rows marked FIXTURE are synthetic development data, not market data.
        </p>
      ) : null}
      {body}
      {list.data?.truncated ? <p className="small subtle">Only the first 500 entries are shown.</p> : null}
      {kind === "tbill" ? <TBillForm onSaved={onSaved} /> : <FdForm onSaved={onSaved} />}
    </>
  );
}

export default function FixedIncome() {
  const [tab, setTab] = useState<Tab>("tbill");
  return (
    <section>
      <PageHeader
        title="Fixed income"
        purpose={
          <>
            T-bills, fixed deposits, G-secs, SDLs and corporate bonds you have entered from official pages, listed by name. This list is not ranked for you; see{" "} <Link to="/discover">Discovery</Link> for an ordering under your constraints.
          </>
        }
      />
      <div className="tabs" role="tablist" aria-label="Instrument type">
        {TABS.map(([t, l]) => (
          <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`panel-${t}`}
            onClick={() => setTab(t)}>
            {l}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "bonds" ? (
          <BondsPanel />
        ) : (
          <KindList key={tab} kind={tab} />
        )}
      </div>
    </section>
  );
}
