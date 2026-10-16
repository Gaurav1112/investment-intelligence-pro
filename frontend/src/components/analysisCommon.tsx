// Analysis helpers shared by Compare, Risk, Scenarios and Simulator (explain drawer wiring, refusals, context line,
// instrument pickers, amount/date inputs). Kept outside pages/ so no page module imports another page
// (audit-perf-frontend F4).
import { useCallback, useState, type ReactNode } from "react";
import { ExplainDrawer, ExplainedNumber } from "./ExplainDrawer";
import { FreshnessBadge } from "./FreshnessBadge";
import { useApi } from "../lib/useApi";
import { useFocusAfter } from "../lib/useFocusAfter";
import { api, ApiError, instrumentSummaryPath, type InstrumentSummaryResponse } from "../lib/api";
import { compareDecimals, dateLabel } from "../lib/format";
import type { AnalysisContext, AnalysisExplained, Band, Explained, InstrumentList, InstrumentListItem, Refusal, Which } from "../lib/types";


export const WHICH: readonly Which[] = ["q05", "q50", "q95"];

export function isRefusal(x: unknown): x is Refusal {
  return typeof x === "object" && x !== null && (x as { status?: unknown }).status === "refused" && (x as { value?: unknown }).value === null;
}

/** Engine text is rendered exactly as the API sends it (copy is fixed at the source, never rewritten in the UI). */
export function toDrawer(e: AnalysisExplained): Explained {
  return {
    ...e,
    label: (e.label),
    what: (e.what),
    assumptions: e.assumptions,
    limitations: e.limitations,
  };
}

export type OnExplain = (e: AnalysisExplained) => void;

/** One drawer per page: `open(x)` shows the explanation of any analysis value. */
export function useExplain(): { open: OnExplain; drawer: ReactNode } {
  const [item, setItem] = useState<Explained | null>(null);
  const open = useCallback((e: AnalysisExplained) => setItem(toDrawer(e)), []);
  return { open, drawer: <ExplainDrawer item={item} onClose={() => setItem(null)} /> };
}

/** An engine value (opens its explanation) or "—" when the API sent none. Never 0 in place of a missing value. */
export function Ex({ item, onExplain }: { item: AnalysisExplained | null | undefined; onExplain: OnExplain }) {
  if (!item) return <span className="subtle">—</span>;
  return <ExplainedNumber item={toDrawer(item)} onExplain={() => onExplain(item)} />;
}

/** A gated metric: words, never a number or 0. */
export function RefusalNote({ r }: { r: Refusal }) {
  return (
    <span className="refusal">
      Not shown: {(r.reason)} <span className="small subtle mono">({r.code})</span>
    </span>
  );
}

export function Metric({ value, onExplain }: { value: AnalysisExplained | Refusal | null | undefined; onExplain: OnExplain }) {
  if (isRefusal(value)) return <RefusalNote r={value} />;
  return <Ex item={value} onExplain={onExplain} />;
}

/** Message for a failed analysis request: `{detail: {code, message}}`, FastAPI 422 lists, or the generic text. */
export function analysisError(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = (e.detail as { detail?: unknown } | null | undefined)?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.message === "string") return `${d.message} (${typeof d.code === "string" ? d.code : `HTTP ${e.status}`})`;
    }
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((x: { loc?: unknown[]; msg?: unknown }) => {
          const loc = Array.isArray(x.loc) ? x.loc.filter((p) => p !== "body").join(".") : "";
          return typeof x.msg === "string" ? (loc ? `${loc}: ${x.msg}` : x.msg) : null;
        })
        .filter(Boolean);
      if (msgs.length) return `The request was rejected: ${msgs.join("; ")} (HTTP ${e.status}).`;
    }
    if (typeof detail === "string") return `${detail} (HTTP ${e.status})`;
    if (e.status === 401) return "Your session has expired. Re-open the app with `make open` to sign in again.";
    return `The request failed (HTTP ${e.status}, ${e.code}). No result is shown rather than a possibly wrong one.`;
  }
  return "The request failed (network error). No result is shown rather than a possibly wrong one.";
}

export function AnalysisErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <p>{analysisError(error)}</p>
      {retry ? (
        <button type="button" className="btn" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function FixtureCallout({ fixture }: { fixture: boolean }) {
  if (!fixture) return null;
  return (
    <p className="callout callout--warn" role="note">
      <FreshnessBadge freshness="FIXTURE" /> <strong>FIXTURE — not market data.</strong> At least one input is synthetic development
      data. Do not use these results for a real decision.
    </p>
  );
}

const BASIS: Record<string, string> = { request: "entered here", profile: "from your profile", illustrative: "ILLUSTRATIVE" };

/** The amount / date / tax basis the engine actually used, as the API echoed them. */
export function ContextLine({ ctx }: { ctx: AnalysisContext }) {
  return (
    <div className="card context-line">
      <p className="small">
        <strong>{ctx.amount}</strong> ({BASIS[ctx.amount_basis] ?? ctx.amount_basis}) · withdraw {dateLabel(ctx.withdrawal_date)} (
        {BASIS[ctx.date_basis] ?? ctx.date_basis}) · {ctx.horizon_days} days · tax: {ctx.tax_basis}
      </p>
      {ctx.illustrative_label ? (
        <p className="small" role="note">
          <span className="badge badge--neutral">Illustrative</span> {ctx.illustrative_label}
        </p>
      ) : null}
    </div>
  );
}

const FLAG_TEXT: Record<string, string> = {
  TAX_RULE_UNVERIFIED: "tax rule unverified",
  TAX_CLASS_INFERRED_FROM_CATEGORY: "tax class inferred from category",
  LOW_EVIDENCE: "low evidence",
  EXCEEDS_DICGC_LIMIT_AT_THIS_BANK: "partly outside DICGC cover",
  NOT_DICGC_INSURED: "not DICGC insured",
  PREMATURE_PENALTY_UNKNOWN: "early-exit penalty unknown",
};
export const flagText = (f: string) =>
  FLAG_TEXT[f] ?? (f.startsWith("TAX_RULES_ASSUMED_UNCHANGED") ? "tax rules assumed beyond legislated year" : f.toLowerCase().replace(/_/g, " "));

/** An instrument chosen in a picker or read from the URL (name/fixture unknown until the API answers). */
export interface Picked {
  instrument_id: string;
  name: string | null;
  fixture: boolean | null;
}

export const pickedFrom = (it: InstrumentListItem): Picked => ({ instrument_id: it.instrument_id, name: it.name, fixture: it.fixture });

/** Search the local store (GET /api/instruments?q=) and pick an instrument. No nested <form>, so usable inside forms. */
export function InstrumentPicker({
  idPrefix,
  label = "Find instrument by name",
  onPick,
  exclude = [],
  disabled = false,
}: {
  idPrefix: string;
  label?: string;
  onPick: (p: Picked) => void;
  exclude?: readonly string[];
  disabled?: boolean;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<InstrumentList | null>(null);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const focusAfter = useFocusAfter();

  async function search() {
    const term = q.trim();
    if (term.length < 2) {
      setErr("Type at least 2 characters of the instrument name.");
      return;
    }
    setPending(true);
    setErr(null);
    try {
      setResults(await api<InstrumentList>(`/api/instruments?q=${encodeURIComponent(term)}`));
    } catch (e) {
      setResults(null);
      setErr(analysisError(e));
    } finally {
      setPending(false);
    }
  }
  const items = (results?.items ?? []).filter((it) => !exclude.includes(it.instrument_id)).slice(0, 25);
  return (
    <div className="field">
      <label htmlFor={`${idPrefix}-q`}>{label}</label>
      <div className="row-tight">
        <input
          id={`${idPrefix}-q`}
          className="input-wide"
          value={q}
          maxLength={80}
          disabled={disabled}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void search();
            }
          }}
        />
        <button type="button" className="btn" onClick={() => void search()} disabled={pending || disabled}>
          {pending ? "Searching…" : "Search"}
        </button>
      </div>
      {err ? (
        <div className="field-error" role="alert">
          {err}
        </div>
      ) : null}
      {results ? (
        <div role="status" className="small">
          {items.length === 0 ? "No stored instrument matches that name." : `${items.length}${results.truncated ? "+" : ""} match(es).`}
        </div>
      ) : null}
      {items.length ? (
        <ul className="plain-list search-results" aria-label="Matching instruments">
          {items.map((it) => (
            <li key={it.instrument_id} className="row-tight">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  onPick(pickedFrom(it));
                  setResults(null);
                  setQ("");
                  // The Select button disappears with the results: return focus to the search box (when the picker
                  // itself is replaced, e.g. SinglePicker, it unmounts and the parent moves focus instead).
                  focusAfter(`${idPrefix}-q`);
                }}
                aria-label={`Select ${it.name}`}
              >
                Select
              </button>
              <span>{it.name}</span>
              <span className="small subtle mono">{it.instrument_id}</span>
              {it.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** A single selected instrument with a "change" button, or the picker. */
export function SinglePicker({ idPrefix, selected, onChange }: { idPrefix: string; selected: Picked | null; onChange: (p: Picked | null) => void }) {
  // A selection that arrives from the URL (?id=) carries only the id: resolve its name for display. If the summary is
  // unavailable the id alone is shown; the full-history detail endpoint is never used for a name.
  const needsName = selected !== null && !selected.name;
  // The summary endpoint carries no observation series (the full history is about 0.73 MB for a 10-year fund).
  const detail = useApi<InstrumentSummaryResponse>(needsName ? instrumentSummaryPath(selected.instrument_id) : null);
  const name = selected?.name || detail.data?.instrument.name || null;
  const fixture = selected?.fixture || detail.data?.instrument.origin === "fixture";
  const focusAfter = useFocusAfter();
  if (!selected)
    return (
      <InstrumentPicker
        idPrefix={idPrefix}
        onPick={(p) => {
          onChange(p);
          focusAfter(`${idPrefix}-change`); // the picker is replaced by the Selected view
        }}
      />
    );
  return (
    <div className="field">
      <span className="label-like">Instrument</span>
      <div className="row-tight" role="status">
        <span>
          Selected: {name ? <strong>{name}</strong> : null} <span className="mono small">{selected.instrument_id}</span>
        </span>
        {fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
        <button
          type="button"
          id={`${idPrefix}-change`}
          className="btn btn--ghost"
          onClick={() => {
            onChange(null);
            focusAfter(`${idPrefix}-q`); // the button is replaced by the search box
          }}
        >
          Change instrument
        </button>
      </div>
    </div>
  );
}

const AMOUNT_RE = /^\d{1,13}(\.\d{1,2})?$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Problems with the optional amount / withdrawal-date inputs (empty = let the engine use profile or illustrative values). */
export function amountDateProblems(amount: string, date: string): Record<string, string> {
  const out: Record<string, string> = {};
  const a = amount.trim();
  if (a && (!AMOUNT_RE.test(a) || compareDecimals(a, "0") <= 0))
    out.amount = "Enter a positive amount in rupees, digits only, at most 2 decimals (e.g. 500000 or 250000.50).";
  if (date && !DATE_RE.test(date)) out.withdrawal_date = "Enter the withdrawal date as a calendar date.";
  return out;
}

export function AmountDateFields({
  idPrefix,
  amount,
  date,
  onAmount,
  onDate,
  errors,
}: {
  idPrefix: string;
  amount: string;
  date: string;
  onAmount: (v: string) => void;
  onDate: (v: string) => void;
  errors: Record<string, string>;
}) {
  return (
    <div className="row">
      <div className="field">
        <label htmlFor={`${idPrefix}-amount`}>Amount in ₹ (optional)</label>
        <span className="money">
          <input
            id={`${idPrefix}-amount`}
            inputMode="decimal"
            value={amount}
            onChange={(e) => onAmount(e.target.value)}
            aria-invalid={Boolean(errors.amount)}
            aria-describedby={`${idPrefix}-amount-hint${errors.amount ? ` ${idPrefix}-amount-err` : ""}`}
          />
        </span>
        <div id={`${idPrefix}-amount-hint`} className="hint">
          Empty: your profile amount, else the labelled illustrative ₹1,00,000.
        </div>
        {errors.amount ? (
          <div className="field-error" id={`${idPrefix}-amount-err`} role="alert">
            {errors.amount}
          </div>
        ) : null}
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-date`}>Withdrawal date (optional)</label>
        <input id={`${idPrefix}-date`} type="date" value={date} onChange={(e) => onDate(e.target.value)} aria-invalid={Boolean(errors.withdrawal_date)} />
        <div className="hint">Empty: your profile date, else the labelled illustrative 182 days.</div>
        {errors.withdrawal_date ? (
          <div className="field-error" role="alert">
            {errors.withdrawal_date}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function BandCell({ band, onExplain, contractual }: { band: Band<AnalysisExplained> | null | undefined; onExplain: OnExplain; contractual?: boolean }) {
  if (!band) return <span className="subtle">—</span>;
  if (contractual)
    return (
      <span>
        <Ex item={band.q50} onExplain={onExplain} /> <span className="small subtle">contractual</span>
      </span>
    );
  return (
    <span className="band band--stackable">
      <span className="band__k">low</span>
      <Ex item={band.q05} onExplain={onExplain} />
      <span className="band__sep" aria-hidden="true">–</span>
      <span className="band__k">mid</span>
      <Ex item={band.q50} onExplain={onExplain} />
      <span className="band__sep" aria-hidden="true">–</span>
      <span className="band__k">high</span>
      <Ex item={band.q95} onExplain={onExplain} />
    </span>
  );
}

/** CPI-adjusted band, or the engine's refusal in words (the backend refuses all three points together, e.g. CPI_STALE). */
export function RealReturnCell({
  band,
  onExplain,
  contractual,
}: {
  band: Band<AnalysisExplained | Refusal> | undefined;
  onExplain: OnExplain;
  contractual?: boolean;
}) {
  if (!band) return <span className="subtle">—</span>;
  const refused = WHICH.map((w) => band[w]).find(isRefusal);
  if (refused) return <RefusalNote r={refused} />;
  const { q05, q50, q95 } = band as Band<AnalysisExplained>;
  return <BandCell band={{ q05, q50, q95 }} contractual={contractual} onExplain={onExplain} />;
}
