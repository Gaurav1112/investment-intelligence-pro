import { useState, type FormEvent, type ReactNode } from "react";
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
import { useApi } from "../lib/useApi";

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

function DeleteButton({ item, onDeleted }: { item: InstrumentListItem; onDeleted: (msg: string) => void }) {
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
      <h3 id="tbill-form-title">Add a T-bill</h3>
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
        <input id="tb-yield" inputMode="decimal" value={yieldPct} onChange={(e) => setYieldPct(e.target.value)}
          aria-invalid={Boolean(errs["yield_fraction"])} aria-describedby="tb-yield-hint tb-yield-err" />
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
      <h3 id="fd-form-title">Add a fixed deposit</h3>
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
        <input id="fd-rate" inputMode="decimal" value={ratePctText} onChange={(e) => setRatePct(e.target.value)}
          aria-invalid={Boolean(errs["rate"])} aria-describedby="fd-rate-hint fd-rate-err" />
        <div id="fd-rate-hint" className="hint">
          The card rate for this exact tenure from the bank&apos;s rate page. Stored with quarterly compounding. Below 30 %.
        </div>
        <FieldError id="fd-rate-err" msg={errs["rate"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-tenure">Tenure (days)</label>
        <input id="fd-tenure" inputMode="numeric" value={tenure} onChange={(e) => setTenure(e.target.value)}
          aria-invalid={Boolean(errs["tenure_days"])} aria-describedby="fd-tenure-err" />
        <FieldError id="fd-tenure-err" msg={errs["tenure_days"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-penalty">Premature-withdrawal penalty (percentage points) — optional</label>
        <input id="fd-penalty" inputMode="decimal" value={penaltyPct} onChange={(e) => setPenaltyPct(e.target.value)}
          aria-invalid={Boolean(errs["premature_penalty"])} aria-describedby="fd-penalty-hint fd-penalty-err" />
        <div id="fd-penalty-hint" className="hint">Leave empty if the bank page does not state it; it is then shown as unknown. Below 10.</div>
        <FieldError id="fd-penalty-err" msg={errs["premature_penalty"]} />
      </div>
      <div className="field">
        <label htmlFor="fd-existing">Deposits you already hold at this institution (₹)</label>
        <input id="fd-existing" inputMode="decimal" value={existing} onChange={(e) => setExisting(e.target.value)}
          aria-invalid={Boolean(errs["existing_deposits_at_institution"])} aria-describedby="fd-existing-hint fd-existing-err" />
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
      <h1>Fixed income</h1>
      <p className="muted">
        T-bills and fixed deposits you have entered from official pages, listed by name. This list is not ranked for you; see{" "}
        <Link to="/discover">Discovery</Link> for an ordering under your constraints.
      </p>
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
          <Empty title="Manual entry of G-secs, SDLs and corporate bonds is not yet supported">
            <p>
              No bond data is shown rather than an incomplete record. T-bills and fixed deposits can be entered on the other
              tabs.
            </p>
          </Empty>
        ) : (
          <KindList key={tab} kind={tab} />
        )}
      </div>
    </section>
  );
}
