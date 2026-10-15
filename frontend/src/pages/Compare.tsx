import { scaleLinear } from "d3-scale";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ExplainDrawer, ExplainedNumber } from "../components/ExplainDrawer";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { CodeText, InstName } from "../components/Code";
import { PageFooter, PageHeader } from "../components/PageHeader";
import { Empty, Loading } from "../components/States";
import { TierLabel } from "../components/Tier";
import { useApi } from "../lib/useApi";
import { api, ApiError } from "../lib/api";
import { compareDecimals, dateLabel, inrCompact } from "../lib/format";
import type {
  AnalysisContext,
  AnalysisExplained,
  Band,
  CompareIn,
  CompareResponse,
  CompareRow,
  Explained,
  InstrumentList,
  InstrumentListItem,
  Refusal,
  Which,
} from "../lib/types";

// ------------------------------------------------------------------ shared analysis helpers (also used by Scenarios / Simulator / Risk)

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
  // A selection that arrives from the URL (?id=) carries only the id: resolve its name for display.
  const needsName = selected !== null && !selected.name;
  const detail = useApi<{ instrument: { name: string; origin: string } }>(
    needsName ? `/api/instruments/${encodeURIComponent(selected.instrument_id)}` : null,
  );
  const name = selected?.name || detail.data?.instrument.name || null;
  const fixture = selected?.fixture || detail.data?.instrument.origin === "fixture";
  if (!selected) return <InstrumentPicker idPrefix={idPrefix} onPick={onChange} />;
  return (
    <div className="field">
      <span className="label-like">Instrument</span>
      <div className="row-tight" role="status">
        <span>
          Selected: {name ? <strong>{name}</strong> : null} <span className="mono small">{selected.instrument_id}</span>
        </span>
        {fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
        <button type="button" className="btn btn--ghost" onClick={() => onChange(null)}>
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

// ------------------------------------------------------------------ compare page

const MAX = 4;

export function parseIds(raw: string | null): string[] {
  const out: string[] = [];
  for (const part of (raw ?? "").split(",")) {
    const id = part.trim();
    if (id && !out.includes(id) && out.length < MAX) out.push(id);
  }
  return out;
}

type RowDef = { label: ReactNode; cell: (r: CompareRow) => ReactNode; key: string };

function rowsFor(res: CompareResponse, onExplain: OnExplain): RowDef[] {
  const anyAnnualised = res.rows.some((r) => r.returns && WHICH.some((w) => r.returns?.[w].annualised));
  const net = (w: Which) => (r: CompareRow) => <Ex item={r.net_proceeds?.[w]} onExplain={onExplain} />;
  const days = res.context.horizon_days;
  const defs: RowDef[] = [
    { key: "tier", label: "Certainty tier", cell: (r) => (r.tier ? <TierLabel tier={r.tier} /> : <span className="subtle">—</span>) },
    {
      key: "elig",
      label: "Eligibility",
      cell: (r) => (
        <div>
          {r.evaluable ? (
            <span className="chip">
              <span aria-hidden="true">✓</span> Evaluated
            </span>
          ) : (
            <strong>
              <span aria-hidden="true">⚠ </span>Not evaluated
            </strong>
          )}
          {r.eligibility_reasons.length ? (
            <ul className="small plain-list">
              {r.eligibility_reasons.map((x) => (
                <li key={x}>
                  <CodeText raw={x} />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ),
    },
    { key: "inv", label: "Initial investment", cell: (r) => <Ex item={r.initial_investment} onExplain={onExplain} /> },
    {
      key: "gross",
      label: (
        <>
          Gross proceeds<div className="small subtle">low – middle – high, before exit costs and tax</div>
        </>
      ),
      cell: (r) => <BandCell band={r.gross_proceeds} contractual={r.contractual} onExplain={onExplain} />,
    },
    {
      key: "costs",
      label: (
        <>
          Costs<div className="small subtle">exit load in ₹ (low – middle – high); stamp duty</div>
        </>
      ),
      cell: (r) =>
        r.costs ? (
          <div>
            <BandCell band={r.costs.exit_load} contractual={r.contractual} onExplain={onExplain} />
            {r.costs.stamp_duty ? (
              <div className="small">
                Stamp duty <Ex item={r.costs.stamp_duty} onExplain={onExplain} />
              </div>
            ) : null}
            {r.costs.note ? <div className="small subtle">{r.costs.note}</div> : null}
          </div>
        ) : (
          <span className="subtle">—</span>
        ),
    },
    {
      key: "tax",
      label: (
        <>
          Assumed tax<div className="small subtle">low – middle – high, with basis</div>
        </>
      ),
      cell: (r) =>
        r.tax ? (
          <div>
            <BandCell band={r.tax.values} contractual={r.contractual} onExplain={onExplain} />
            <div className="small subtle">
              Basis: {r.tax.basis.replace(/_/g, " ")} · rules {r.tax.rule_ids.join(", ")}
              {r.tax.unverified ? " · rule pending CA review" : ""}
            </div>
          </div>
        ) : (
          <span className="subtle">—</span>
        ),
    },
    {
      key: "q05",
      label: (
        <>
          Illustrative downside scenario<div className="small subtle">net proceeds, low end (q05), after costs and assumed tax</div>
        </>
      ),
      cell: net("q05"),
    },
    { key: "q50", label: <>Middle outcome<div className="small subtle">net proceeds (q50)</div></>, cell: net("q50") },
    { key: "q95", label: <>High-end outcome<div className="small subtle">net proceeds (q95)</div></>, cell: net("q95") },
    {
      key: "pnl",
      label: (
        <>
          Net profit or loss<div className="small subtle">low – middle – high</div>
        </>
      ),
      cell: (r) => <BandCell band={r.net_pnl} contractual={r.contractual} onExplain={onExplain} />,
    },
    {
      key: "ret",
      label: (
        <>
          Absolute return over {days} days<div className="small subtle">low – middle – high; the whole period, not annualised</div>
        </>
      ),
      cell: (r) =>
        r.returns ? (
          <div>
            <BandCell
              band={{ q05: r.returns.q05.absolute, q50: r.returns.q50.absolute, q95: r.returns.q95.absolute }}
              contractual={r.contractual}
              onExplain={onExplain}
            />
            <div className="small subtle">{r.returns.q50.annualisation_note}</div>
          </div>
        ) : (
          <span className="subtle">—</span>
        ),
    },
  ];
  if (anyAnnualised)
    defs.push({
      key: "ann",
      label: (
        <>
          Annualised equivalent (secondary)<div className="small subtle">shown only because the horizon is at least 365 days</div>
        </>
      ),
      cell: (r) => {
        const a = r.returns;
        if (!a || !a.q05.annualised || !a.q50.annualised || !a.q95.annualised) return <span className="subtle">—</span>;
        return <BandCell band={{ q05: a.q05.annualised, q50: a.q50.annualised, q95: a.q95.annualised }} contractual={r.contractual} onExplain={onExplain} />;
      },
    });
  defs.push(
    {
      key: "liq",
      label: "Liquidity",
      cell: (r) =>
        r.liquidity ? (
          <span>
            cash within {r.liquidity.days_to_cash} day(s)
            {r.liquidity.lock_in_days ? ` · lock-in ${r.liquidity.lock_in_days} days` : ""}
          </span>
        ) : (
          <span className="subtle">—</span>
        ),
    },
    { key: "exit", label: "Exit cost (ranking measure)", cell: (r) => <Metric value={r.exit_cost} onExplain={onExplain} /> },
    { key: "loss", label: "Loss history", cell: (r) => (r.loss_frequency ? (r.loss_frequency.display) : <span className="subtle">—</span>) },
    {
      key: "flags",
      label: "Flags",
      cell: (r) =>
        r.flags.length ? (
          <span className="small">
            <span aria-hidden="true">⚠ </span>
            {r.flags.map(flagText).join(" · ")}
          </span>
        ) : (
          <span className="subtle">none</span>
        ),
    },
  );
  return defs;
}

const CHART_W = 640;
const LEFT = 16;
const RIGHT = 16;

/** Net-proceeds bands on one shared ₹ axis (one hue, direct labels). Strings → Number for geometry only. */
export function CompareBands({ rows }: { rows: CompareRow[] }) {
  const shown = rows.filter((r): r is CompareRow & { net_proceeds: Band<AnalysisExplained> } => Boolean(r.net_proceeds));
  if (shown.length === 0) return null;
  const all = shown.flatMap((r) => WHICH.map((w) => Number(r.net_proceeds[w].value)));
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.06;
  const x = scaleLinear().domain([lo - pad, hi + pad]).range([LEFT, CHART_W - RIGHT]);
  const rowH = 44;
  const height = shown.length * rowH + 36;
  const ticks = x.ticks(4);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${CHART_W} ${height}`} width="100%" role="img" aria-label="Net proceeds bands on a shared rupee axis: illustrative downside scenario, middle and high-end outcome per instrument.">
        {shown.map((r, i) => {
          const y = i * rowH + 28;
          const a = x(Number(r.net_proceeds.q05.value));
          const m = x(Number(r.net_proceeds.q50.value));
          const b = x(Number(r.net_proceeds.q95.value));
          return (
            <g key={r.instrument_id}>
              <text x={LEFT} y={y - 10} className="tick">
                {r.name} — {r.net_proceeds.q05.display} · {r.net_proceeds.q50.display} · {r.net_proceeds.q95.display}
              </text>
              <line x1={a} x2={b} y1={y} y2={y} className="range-bar" />
              <line x1={a} x2={a} y1={y - 5} y2={y + 5} className="range-bar" />
              <line x1={b} x2={b} y1={y - 5} y2={y + 5} className="range-bar" />
              <circle cx={m} cy={y} r={4.5} className="dot" />
            </g>
          );
        })}
        <line x1={LEFT} x2={CHART_W - RIGHT} y1={height - 24} y2={height - 24} className="axis" />
        {ticks.map((t) => (
          <text key={t} x={x(t)} y={height - 8} className="tick" textAnchor="middle">
            {inrCompact(String(Math.round(t)))}
          </text>
        ))}
      </svg>
      <figcaption className="small">
        Line = illustrative downside scenario (q05) to high-end outcome (q95); dot = middle outcome (q50). Net of costs and assumed tax. Historical
        ranges, not a forecast.
      </figcaption>
    </figure>
  );
}

export default function Compare() {
  const [params, setParams] = useSearchParams();
  const ids = parseIds(params.get("ids"));
  const urlAmount = params.get("amount") ?? "";
  const urlDate = params.get("date") ?? "";
  const [names, setNames] = useState<Record<string, Picked>>({});
  const [amount, setAmount] = useState(urlAmount);
  const [date, setDate] = useState(urlDate);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const { open, drawer } = useExplain();
  const seq = useRef(0);
  const key = `${ids.join(",")}|${urlAmount}|${urlDate}`;

  const setUrl = (nextIds: string[], a: string, d: string) => {
    const p = new URLSearchParams();
    if (nextIds.length) p.set("ids", nextIds.join(","));
    if (a) p.set("amount", a);
    if (d) p.set("date", d);
    setParams(p);
  };

  const run = useCallback(async () => {
    const mine = ++seq.current;
    if (ids.length < 2) {
      setResult(null);
      setError(null);
      return;
    }
    const body: CompareIn = { instrument_ids: ids };
    if (urlAmount) body.amount = urlAmount;
    if (urlDate) body.withdrawal_date = urlDate;
    setPending(true);
    setError(null);
    try {
      const out = await api<CompareResponse>("/api/compare", { method: "POST", body });
      if (mine === seq.current) setResult(out);
    } catch (e) {
      if (mine === seq.current) {
        setResult(null);
        setError(e);
      }
    } finally {
      if (mine === seq.current) setPending(false);
    }
  }, [key]);

  useEffect(() => {
    void run();
  }, [run]);

  function apply(e: FormEvent) {
    e.preventDefault();
    const probs = amountDateProblems(amount, date);
    setErrors(probs);
    if (Object.keys(probs).length) return;
    if (amount.trim() === urlAmount && date === urlDate) void run();
    else setUrl(ids, amount.trim(), date);
  }

  const label = (id: string) => result?.rows.find((r) => r.instrument_id === id)?.name ?? names[id]?.name ?? id;

  return (
    <section>
      <PageHeader
        title="Compare"
        purpose="2–4 instruments side by side, for one amount and withdrawal date. Every number comes from the engine; select a number to see how it was computed. Not a recommendation."
      />

      <div className="card">
        <h2 className="h-inline">Instruments ({ids.length} of {MAX})</h2>
        {ids.length ? (
          <ul className="plain-list" aria-label="Instruments to compare">
            {ids.map((id) => (
              <li key={id} className="row-tight">
                <span className="inst-name" title={label(id)}>
                  {label(id)}
                </span>
                <span className="small subtle mono">{id}</span>
                <button type="button" className="btn btn--ghost" onClick={() => setUrl(ids.filter((x) => x !== id), urlAmount, urlDate)} aria-label={`Remove ${label(id)}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {ids.length < MAX ? (
          <InstrumentPicker
            idPrefix="cmp"
            label="Add an instrument"
            exclude={ids}
            onPick={(p) => {
              setNames((n) => ({ ...n, [p.instrument_id]: p }));
              setUrl([...ids, p.instrument_id], urlAmount, urlDate);
            }}
          />
        ) : (
          <p className="small subtle">Four is the maximum; remove one to add another.</p>
        )}
        <form onSubmit={apply} noValidate>
          <AmountDateFields idPrefix="cmp" amount={amount} date={date} onAmount={setAmount} onDate={setDate} errors={errors} />
          <button type="submit" className="btn btn--primary" disabled={ids.length < 2 || pending}>
            {pending ? "Comparing…" : "Compare"}
          </button>
        </form>
      </div>

      {ids.length < 2 ? (
        <Empty title="Pick at least two instruments">
          <p>Search the local store above, or start from an instrument page and use “Add to comparison”. The selection is kept in the address, so the view can be reloaded or shared.</p>
        </Empty>
      ) : pending && !result ? (
        <Loading label="Comparing" />
      ) : error ? (
        <AnalysisErrorState error={error} retry={() => void run()} />
      ) : result ? (
        <CompareResult res={result} onExplain={open} />
      ) : null}
      {drawer}
    </section>
  );
}

function CompareResult({ res, onExplain }: { res: CompareResponse; onExplain: OnExplain }) {
  const defs = rowsFor(res, onExplain);
  const byId = new Map(res.rows.map((r) => [r.instrument_id, r] as const));
  return (
    <div className={res.fixture ? "fixture-zone" : undefined}>
      <FixtureCallout fixture={res.fixture} />
      <ContextLine ctx={res.context} />
      <div className="table-wrap">
        <table className="table compare-table table--sticky-first">
          <caption className="sr-only">Comparison of {res.rows.length} instruments</caption>
          <thead>
            <tr>
              <th scope="col">Row</th>
              {res.rows.map((r) => (
                <th scope="col" key={r.instrument_id}>
                  <Link to={`/i/${encodeURIComponent(r.instrument_id)}`}>
                    <InstName name={r.name} />
                  </Link>
                  <span className="inst-code">{r.instrument_id}</span>
                  <div className="row-tight small">
                    <FreshnessBadge freshness={r.freshness} date={r.observed} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {defs.map((d) => (
              <tr key={d.key}>
                <th scope="row">{d.label}</th>
                {res.rows.map((r) => (
                  <td key={r.instrument_id} className="num">
                    {d.cell(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Net proceeds on one axis</h2>
      <CompareBands rows={res.rows} />

      <h2>What would change the order</h2>
      <p className="small">{(res.order_basis)}</p>
      {res.what_would_change_order.length === 0 ? (
        <p className="small subtle">Fewer than two instruments could be evaluated, so there is no order to change.</p>
      ) : (
        <ul>
          {res.what_would_change_order.map((c) => (
            <li key={`${c.above}>${c.below}`}>
              {(c.text)} <span className="small subtle">Gap:</span> <Ex item={c.gap} onExplain={onExplain} />
            </li>
          ))}
        </ul>
      )}
      {res.order.length < res.rows.length ? (
        <p className="small subtle">
          Not in the order (not evaluated): {res.rows.filter((r) => !res.order.includes(r.instrument_id)).map((r) => byId.get(r.instrument_id)?.name).join(", ")}.
        </p>
      ) : null}
      <PageFooter>
        <p className="disclosure">{res.disclaimer}</p>
        <p className="mono">
          as of {dateLabel(res.as_of)} · result {res.run.result_hash.slice(0, 12)}… · {Object.entries(res.run.versions).map(([k, v]) => `${k} ${v}`).join(" · ")}
        </p>
      </PageFooter>
    </div>
  );
}
