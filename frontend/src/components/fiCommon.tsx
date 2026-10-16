// Fixed-income display helpers shared by several pages (FixedIncome, Overview, Watchlist, InstrumentDetail, MfExplorer
// and input panels). They live outside pages/ so no page module has to import another page (audit-perf-frontend F4).
import { FreshnessBadge } from "./FreshnessBadge";
import { ApiError } from "../lib/api";
import { dateLabel, groupIndian, roundHalfUp, shiftPoint } from "../lib/format";
import type { CitationIn, ValidationErrorBody } from "../lib/types";
import type { BondListItem } from "../lib/types-bonds";


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
    if (e.code === "NAVALL_IN_PROGRESS") return `The AMFI latest-NAV fetch is already running. Try again ${later}.`;
    if (e.code === "RATE_LIMITED") return `This was fetched recently; to be polite to the source, try again ${later}.`;
    const d = (e.detail as { detail?: unknown } | undefined)?.detail;
    if (typeof d === "string") return `${d} (HTTP ${e.status})`;
    // Structured refusals, e.g. the batch backfill's {code: "UNKNOWN_SCHEMES", unknown: [...], message}.
    const o = d as { message?: unknown; unknown?: unknown } | undefined;
    if (o && typeof o.message === "string") {
      const list = Array.isArray(o.unknown) && o.unknown.length ? ` (${o.unknown.join(", ")})` : "";
      return `${o.message}${list} (HTTP ${e.status})`;
    }
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

export function CiteLink({ url }: { url: string | null | undefined }) {
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

// ------------------------------------------------------------------ bond cells

export const BOND_QUOTE_STALE_DAYS = 7; // backend services/instruments.py BOND_QUOTE_STALE_DAYS
export const RATING_STALE_DAYS = 365; // backend services/instruments.py RATING_STALE_DAYS

export function QuoteCell({ item }: { item: BondListItem }) {
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

export function QuoteAge({ item }: { item: BondListItem }) {
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

export function RatingCell({ item }: { item: BondListItem }) {
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

