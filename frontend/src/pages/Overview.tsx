import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ExplainDrawer, ExplainedNumber } from "../components/ExplainDrawer";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { PageHeader } from "../components/PageHeader";
import { StartHere } from "../components/StartHere";
import { Empty, Loading } from "../components/States";
import { api, apiUpload } from "../lib/api";
import { dateLabel, inr, roundHalfUp, utcStamp } from "../lib/format";
import type {
  Allocation,
  Explained,
  Freshness,
  ImportApplied,
  ImportPreview,
  InstrumentListItem,
  PortfolioCreated,
  PortfolioExplained,
  PortfolioListItem,
  PortfolioNature,
  PortfolioSummary,
  SourceRef,
  SummaryHolding,
  TransactionIn,
  TransactionList,
  TransactionRow,
} from "../lib/types";
import { useApi } from "../lib/useApi";
import { CasImport } from "./CasImport";
import { FieldError, navLabel, todayIst, validationErrors } from "./FixedIncome";
import { apiCode, apiMessage, InstrumentSearch, safeFreshness } from "./Watchlist";

// ------------------------------------------------------------------ helpers

const DERIVED_NOTE: Record<string, string> = {
  DERIVED: "Data label from the engine: DERIVED — computed from your transactions and stored data (badge shows MANUAL ENTRY).",
  USER_DATA: "Data label from the engine: USER DATA — taken from your own transactions (badge shows MANUAL ENTRY).",
  UNAVAILABLE: "Data label from the engine: UNAVAILABLE — this value could not be computed.",
};

/** Adapt the portfolio service's Explained (partial sources, derived freshness labels) to the drawer's contract
 * without changing any number or display string. `plus` only prefixes "+" to a positive display. */
export function toExplained(p: PortfolioExplained, opts: { plus?: boolean } = {}): Explained {
  const seen = new Set<string>();
  const sources: SourceRef[] = [];
  for (const s of p.sources) {
    const key = `${s.source_id}-${s.observation_date ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const user = s.source_id.startsWith("user.") || s.source_id.startsWith("deposit_terms");
    sources.push({
      source_id: s.source_id,
      source_name: s.source_name ?? (user ? `${s.source_id} (your own records)` : `${s.source_id} (official status: see Data health)`),
      url: s.url ?? "",
      retrieved_at: s.retrieved_at ?? null,
      observation_date: s.observation_date ?? null,
      quality_status: s.quality_status ?? (user ? "user data" : "not stated"),
      // The drawer prints "(UNOFFICIAL)" when false; the source name above states the real status instead.
      official: s.official ?? true,
    });
  }
  const known = safeFreshness(p.freshness);
  const derived = p.freshness === "DERIVED" || p.freshness === "USER_DATA";
  const freshness: Freshness = derived ? "MANUAL" : known;
  const note = DERIVED_NOTE[p.freshness];
  const observedRange = p.observed && p.observed.includes("→") ? [`Observed range: ${p.observed}`] : [];
  const positive = p.value !== null && !p.value.startsWith("-") && !/^0*(\.0*)?$/.test(p.value);
  return {
    ...p,
    display: opts.plus && positive && !p.display.startsWith("+") ? `+${p.display}` : p.display,
    sources,
    freshness,
    inputs: [...p.inputs, ...observedRange],
    limitations: note ? [note, ...p.limitations] : p.limitations,
  };
}

/** Units: at most 6 dp (the engine's unit precision), trailing zeros removed. */
export function unitsLabel(u: string): string {
  const r = roundHalfUp(u, 6);
  return r.includes(".") ? r.replace(/0+$/, "").replace(/\.$/, "") : r;
}

function direction(value: string | null): "up" | "down" | "flat" {
  if (value === null || /^-?0*(\.0*)?$/.test(value)) return "flat";
  return value.startsWith("-") ? "down" : "up";
}

function Direction({ value }: { value: string | null }) {
  const d = direction(value);
  if (d === "flat") return <span className="small subtle">no change</span>;
  return (
    <span className={d}>
      <span aria-hidden="true">{d === "up" ? "▲" : "▼"}</span> {d === "up" ? "gain" : "loss"}
    </span>
  );
}

function SignedInr({ value }: { value: string }) {
  const d = direction(value);
  return (
    <span className={d === "flat" ? undefined : d}>
      {d === "flat" ? null : <span aria-hidden="true">{d === "up" ? "▲ " : "▼ "}</span>}
      {d === "up" ? "+" : ""}
      {inr(value)}
    </span>
  );
}

const NATURE_TEXT: Record<PortfolioNature, string> = {
  actual: "ACTUAL — your real holdings",
  hypothetical: "HYPOTHETICAL — what-if, not your holdings",
};

export function NatureTag({ nature }: { nature: PortfolioNature }) {
  return (
    <span className={`badge nature nature--${nature}`}>
      <span aria-hidden="true">{nature === "actual" ? "●" : "◇"}</span> {nature === "actual" ? "ACTUAL" : "HYPOTHETICAL"}
    </span>
  );
}

function HoldingBadge({ h }: { h: SummaryHolding }) {
  if (h.badge === "NOT_VALUED") return <span className="badge badge--neutral">At cost · not valued</span>;
  return <FreshnessBadge freshness={safeFreshness(h.badge)} date={h.nav?.observation_date ?? null} />;
}

function Status({ msg, kind = "status", focusRef }: { msg: string | null; kind?: "status" | "alert"; focusRef?: RefObject<HTMLParagraphElement | null> }) {
  if (!msg) return null;
  return (
    <p ref={focusRef} tabIndex={-1} className={kind === "alert" ? "callout callout--stale" : "callout"} role={kind}>
      {msg}
    </p>
  );
}

function RequestError({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <p>{apiMessage(error)} No result is shown rather than a possibly wrong one.</p>
      {retry ? (
        <button type="button" className="btn" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ portfolio picker & creation

function PortfolioPicker({ items, value, onChange }: { items: PortfolioListItem[]; value: string; onChange: (id: string) => void }) {
  const actual = items.filter((p) => p.nature === "actual");
  const hypo = items.filter((p) => p.nature === "hypothetical");
  const opt = (p: PortfolioListItem) => (
    <option key={p.portfolio_id} value={p.portfolio_id}>
      [{p.nature === "actual" ? "ACTUAL" : "HYPOTHETICAL"}] {p.name} — {p.transactions} transaction{p.transactions === 1 ? "" : "s"}
    </option>
  );
  return (
    <div className="field">
      <label htmlFor="pf-pick">Portfolio</label>
      <select id="pf-pick" value={value} onChange={(e) => onChange(e.target.value)}>
        {actual.length ? <optgroup label="Actual portfolios (your real holdings)">{actual.map(opt)}</optgroup> : null}
        {hypo.length ? <optgroup label="Hypothetical portfolios (what-if, never mixed with actual)">{hypo.map(opt)}</optgroup> : null}
      </select>
      <div className="hint">Actual and hypothetical portfolios are never added together.</div>
    </div>
  );
}

function CreatePortfolioForm({ onCreated }: { onCreated: (p: PortfolioCreated) => void }) {
  const [name, setName] = useState("");
  const [nature, setNature] = useState<PortfolioNature>("actual");
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setErr("Enter a name for the portfolio.");
      return;
    }
    setPending(true);
    setErr(null);
    try {
      const p = await api<PortfolioCreated>("/api/portfolios", { method: "POST", body: { name: name.trim(), nature } });
      setName("");
      onCreated(p);
    } catch (ex) {
      setErr(`Not created: ${apiMessage(ex)}`);
    } finally {
      setPending(false);
    }
  }
  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="pf-new-title">
      <h2 id="pf-new-title">Create a portfolio</h2>
      <div className="field">
        <label htmlFor="pf-name">Portfolio name</label>
        <input id="pf-name" className="input-wide" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <fieldset className="field">
        <legend>Kind of portfolio</legend>
        <label className="choice">
          <input type="radio" name="pf-nature" value="actual" checked={nature === "actual"} onChange={() => setNature("actual")} />
          Actual — what you really hold
        </label>
        <label className="choice">
          <input type="radio" name="pf-nature" value="hypothetical" checked={nature === "hypothetical"} onChange={() => setNature("hypothetical")} />
          Hypothetical — a what-if; never added to your actual holdings
        </label>
      </fieldset>
      {err ? (
        <p className="callout callout--stale" role="alert">
          {err}
        </p>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={pending}>
        {pending ? "Creating…" : "Create portfolio"}
      </button>
    </form>
  );
}

// ------------------------------------------------------------------ summary sections

type OnExplain = (e: Explained) => void;

function HoldingsTable({ rows, onExplain }: { rows: SummaryHolding[]; onExplain: OnExplain }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Holdings</caption>
        <thead>
          <tr>
            <th scope="col">Holding</th>
            <th scope="col">Data</th>
            <th scope="col" className="num">Units</th>
            <th scope="col" className="num">Latest NAV</th>
            <th scope="col" className="num">Invested (FIFO cost)</th>
            <th scope="col" className="num">Market value</th>
            <th scope="col" className="num">Unrealised P/L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => (
            <tr
              key={h.instrument_id}
              className={[h.included_in_totals ? "" : "is-excluded", h.badge === "FIXTURE" ? "fixture-zone" : ""].join(" ").trim() || undefined}
              data-testid={`holding-${h.instrument_id}`}
            >
              <td>
                <Link to={`/i/${encodeURIComponent(h.instrument_id)}`}>{h.name}</Link>
                <div className="small subtle">
                  {h.kind} · {h.category} · {h.lots} open lot{h.lots === 1 ? "" : "s"}
                </div>
                {h.exclusion ? (
                  <div className="small exclusion-note">
                    <strong>Excluded from totals:</strong> {h.exclusion.text}
                  </div>
                ) : null}
              </td>
              <td>
                <HoldingBadge h={h} />
                {h.nav ? (
                  <div className="small">
                    <Link to={`/evidence/${h.nav.obs_id}`}>NAV evidence</Link>
                  </div>
                ) : null}
              </td>
              <td className="num">{unitsLabel(h.units)}</td>
              <td className="num">
                {h.nav ? (
                  <>
                    {navLabel(h.nav.value)}
                    <div className="small subtle">{dateLabel(h.nav.observation_date)}</div>
                  </>
                ) : (
                  <span className="subtle">—</span>
                )}
              </td>
              <td className="num">
                <ExplainedNumber item={toExplained(h.invested)} onExplain={onExplain} />
              </td>
              <td className="num">
                {h.market_value ? <ExplainedNumber item={toExplained(h.market_value)} onExplain={onExplain} /> : <span className="subtle">not valued</span>}
              </td>
              <td className="num">
                {h.unrealised_pl ? (
                  <>
                    <ExplainedNumber item={toExplained(h.unrealised_pl, { plus: true })} onExplain={onExplain} />
                    <div className="small">
                      <Direction value={h.unrealised_pl.value} />
                    </div>
                  </>
                ) : (
                  <span className="subtle">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Totals({ s, onExplain }: { s: PortfolioSummary; onExplain: OnExplain }) {
  const t = s.totals;
  const x = s.xirr;
  return (
    <div className="grid grid--3">
      <div className="card">
        <h3>Market value</h3>
        <ExplainedNumber item={toExplained(t.market_value)} onExplain={onExplain} />
        <p className="small subtle">Valued holdings only (units × latest NAV).</p>
      </div>
      <div className="card">
        <h3>Invested</h3>
        <ExplainedNumber item={toExplained(t.invested)} onExplain={onExplain} />
        <p className="small subtle">
          Valued holdings, FIFO cost. All holdings at cost, including excluded ones: {inr(t.invested_all_holdings)}.
        </p>
      </div>
      <div className="card">
        <h3>Unrealised P/L</h3>
        <ExplainedNumber item={toExplained(t.unrealised_pl, { plus: true })} onExplain={onExplain} />{" "}
        <Direction value={t.unrealised_pl.value} />
        <p className="small subtle">
          Before tax and exit loads. Realised P/L on units already sold: <SignedInr value={t.realised_pl} />.
        </p>
      </div>
      <div className="card">
        <h3>XIRR</h3>
        {x.headline_allowed ? (
          <>
            <ExplainedNumber item={toExplained(x.explain)} onExplain={onExplain} />
            <p className="small subtle">Money-weighted, a year. Scope: {x.scope}.</p>
          </>
        ) : x.annualised_detail ? (
          <div>
            <p className="small">
              <ExplainedNumber item={toExplained(x.explain)} onExplain={onExplain} />
            </p>
            <p className="small">
              Absolute change instead (valued holdings): <ExplainedNumber item={toExplained(t.unrealised_pl, { plus: true })} onExplain={onExplain} />{" "}
              <Direction value={t.unrealised_pl.value} />
            </p>
            <p className="small subtle">{x.annualised_detail.warning}. Scope: {x.scope}.</p>
          </div>
        ) : (
          <p className="small">
            Not available: {x.explain.what} <span className="subtle">Scope: {x.scope}.</span>
          </p>
        )}
      </div>
    </div>
  );
}

function AllocationTable({ a, title }: { a: Allocation; title: string }) {
  if (a.items.length === 0) return <p className="small subtle">{title}: no valued holdings.</p>;
  return (
    <div className="table-wrap">
      <table className="table table--compact">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col" className="num">Market value</th>
            <th scope="col" className="num">Share</th>
            <th scope="col">
              <span className="sr-only">Share as a bar</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {a.items.map((it) => (
            <tr key={it.key}>
              <td>{it.key}</td>
              <td className="num">{inr(it.market_value)}</td>
              <td className="num">{it.share}</td>
              <td className="bar-cell" aria-hidden="true">
                <span className="bar" style={{ width: it.share }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Concentration({ s, onExplain }: { s: PortfolioSummary; onExplain: OnExplain }) {
  const c = s.concentration;
  return (
    <div className="card">
      <h3>Concentration</h3>
      {c.band === null ? (
        <p className="small">Not available: {c.explain.what}.</p>
      ) : (
        <>
          <p>
            HHI <ExplainedNumber item={toExplained(c.explain)} onExplain={onExplain} />
            {c.effective_count ? <> · about {c.effective_count} equally-sized holdings&apos; worth of spread</> : null}
          </p>
        </>
      )}
      <p className="small subtle">
        HHI adds up the square of each holding&apos;s share of market value. It is 1 when everything is in one holding and 1/N when
        money is split equally across N holdings, so a higher number means more of the money depends on fewer holdings. It
        looks at schemes, not the companies inside them, and counts valued holdings only.
      </p>
    </div>
  );
}

function Ladder({ s, onExplain }: { s: PortfolioSummary; onExplain: OnExplain }) {
  const l = s.liquidity_ladder;
  return (
    <div>
      <h3>
        Liquidity ladder <ExplainedNumber item={toExplained(l.explain)} onExplain={onExplain} />
      </h3>
      <div className="table-wrap">
        <table className="table table--compact">
          <caption className="sr-only">Money by days until it could be in your account</caption>
          <thead>
            <tr>
              <th scope="col">Days to cash</th>
              <th scope="col" className="num">Market value</th>
              <th scope="col" className="num">Share</th>
              <th scope="col" className="num">At cost (not valued)</th>
            </tr>
          </thead>
          <tbody>
            {l.buckets.map((b) => (
              <tr key={b.bucket}>
                <td>{b.bucket}</td>
                <td className="num">{inr(b.market_value)}</td>
                <td className="num">{b.share}</td>
                <td className="num">{inr(b.at_cost_not_valued)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const MATURITY_FLAG: Record<string, string> = { MATURED_NOT_RECORDED: "past its maturity date — redemption not yet recorded" };

function Maturities({ s }: { s: PortfolioSummary }) {
  const m = s.upcoming_maturities;
  return (
    <div>
      <h3>Upcoming maturities (next {m.within_days} days)</h3>
      {m.items.length === 0 ? (
        <p className="small subtle">Nothing matures within {m.within_days} days.</p>
      ) : (
        <div className="table-wrap">
          <table className="table table--compact">
            <caption className="sr-only">Upcoming maturities</caption>
            <thead>
              <tr>
                <th scope="col">Instrument</th>
                <th scope="col">Maturity date</th>
                <th scope="col" className="num">Days</th>
                <th scope="col" className="num">Invested at cost</th>
                <th scope="col">Basis</th>
              </tr>
            </thead>
            <tbody>
              {m.items.map((x) => (
                <tr key={`${x.instrument_id}-${x.maturity_date}`}>
                  <td>
                    {x.name}
                    {x.flags.map((f) => (
                      <div key={f} className="small field-error">
                        {MATURITY_FLAG[f] ?? f}
                      </div>
                    ))}
                  </td>
                  <td>{dateLabel(x.maturity_date)}</td>
                  <td className="num">{x.days_until}</td>
                  <td className="num">{inr(x.invested_at_cost)}</td>
                  <td className="small">{x.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Dicgc({ s, onExplain }: { s: PortfolioSummary; onExplain: OnExplain }) {
  const d = s.dicgc;
  return (
    <div>
      <h3>Deposit insurance (DICGC) exposure</h3>
      <p className="small subtle">Scope: {d.scope}.</p>
      {d.banks.length === 0 ? (
        <p className="small subtle">{d.note ?? "No fixed deposits held."}</p>
      ) : (
        <>
          {d.explain ? (
            <p>
              Total above the cover: <ExplainedNumber item={toExplained(d.explain)} onExplain={onExplain} />
            </p>
          ) : null}
          <div className="table-wrap">
            <table className="table table--compact">
              <caption className="sr-only">DICGC exposure per bank</caption>
              <thead>
                <tr>
                  <th scope="col">Institution</th>
                  <th scope="col" className="num">Principal at cost</th>
                  <th scope="col" className="num">Insured</th>
                  <th scope="col" className="num">Not insured</th>
                  <th scope="col">Notes</th>
                </tr>
              </thead>
              <tbody>
                {d.banks.map((b) => (
                  <tr key={b.institution}>
                    <td>{b.institution}</td>
                    <td className="num">{inr(b.principal_at_cost)}</td>
                    <td className="num">{inr(b.insured)}</td>
                    <td className="num">{inr(b.uninsured)}</td>
                    <td className="small">{b.flags.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small subtle">Principal at cost only; accrued interest is not included and would raise the exposure.</p>
        </>
      )}
    </div>
  );
}

const TEMPLATE_COLUMNS = "instrument_name, isin, amfi_code, units, cost_basis_inr, purchase_date";

function TemplateHelp() {
  return (
    <div className="small">
      <p>
        CSV or XLSX (up to 5 MiB, 20,000 rows) with this header row: <code>{TEMPLATE_COLUMNS}</code>.
      </p>
      <ul>
        <li>
          <code>instrument_name</code> and <code>units</code> are required to read a row; a row is stored only if it also has{" "}
          <code>cost_basis_inr</code>, a <code>purchase_date</code> that is not in the future, and an <code>amfi_code</code> or{" "}
          <code>isin</code> that matches an instrument already stored. Names are never used for matching.
        </li>
        <li>Dates: 2025-01-10, 10-01-2025 or 10-Jan-2025 (slash dates are refused as ambiguous).</li>
        <li>Amounts: plain or grouped (1,00,000.50 or 100,000.50); no currency symbols. Units up to 6 decimals, cost up to 2.</li>
        <li>Every row is imported as a buy. Other columns are ignored with a warning.</li>
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ transactions

const TXN_ERRORS: Record<string, string> = {
  OVERSELL:
    "This sale is for more units than you held on that date. Sales cannot exceed the units bought on or before the sale date. Nothing was stored.",
  WOULD_OVERSELL:
    "This purchase cannot be deleted: a later sale depends on its units, and without it that sale would exceed the units held. Delete the later sale first. Nothing was changed.",
  FUTURE_DATE: "The transaction date is in the future. Nothing was stored.",
  UNKNOWN_INSTRUMENT: "That instrument is not in the local store. Nothing was stored.",
};

export function txnErrorText(e: unknown): string {
  const code = apiCode(e);
  const plain = code ? TXN_ERRORS[code] : undefined;
  return plain ? `${plain} (${apiMessage(e)})` : `Not saved: ${apiMessage(e)}`;
}

const UNITS_RE = /^[0-9]{1,15}(\.[0-9]{1,6})?$/;
const AMOUNT_RE = /^[0-9]{1,15}(\.[0-9]{1,2})?$/;
const positive = (s: string) => /[1-9]/.test(s);

function AddTransactionForm({ portfolioId, onSaved }: { portfolioId: string; onSaved: (msg: string) => void }) {
  const [instrument, setInstrument] = useState<InstrumentListItem | null>(null);
  const [type, setType] = useState<"buy" | "sell">("buy");
  const [date, setDate] = useState("");
  const [units, setUnits] = useState("");
  const [amount, setAmount] = useState("");
  const [local, setLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const fieldErrs = validationErrors(error);
  const server = fieldErrs && Object.keys(fieldErrs).length ? fieldErrs : null; // a 422 refusal with a code is not a field error
  const errs = { ...(server ?? {}), ...local };
  const amountClean = amount.replace(/[,\s₹]/g, "");
  const unitsClean = units.trim();
  const today = todayIst();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const p: Record<string, string> = {};
    if (!instrument) p["instrument_id"] = "Search for and select the instrument.";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) p["txn_date"] = "Enter the transaction date.";
    else if (date > today) p["txn_date"] = "The date cannot be in the future.";
    if (!UNITS_RE.test(unitsClean) || !positive(unitsClean)) p["units"] = "Enter units above zero, digits with up to 6 decimals (e.g. 125.5).";
    if (!AMOUNT_RE.test(amountClean) || !positive(amountClean)) p["amount"] = "Enter the amount in rupees above zero, with up to 2 decimals (e.g. 10000.50).";
    setLocal(p);
    if (Object.keys(p).length || !instrument) return;
    const body: TransactionIn = { instrument_id: instrument.instrument_id, txn_date: date, txn_type: type, units: unitsClean, amount: amountClean };
    setPending(true);
    setError(null);
    try {
      await api(`/api/portfolios/${encodeURIComponent(portfolioId)}/transactions`, { method: "POST", body });
      onSaved(`Stored: ${type} of ${unitsClean} units of ${instrument.name} on ${dateLabel(date)} for ${inr(amountClean)}.`);
      setUnits("");
      setAmount("");
      setDate("");
      setInstrument(null);
    } catch (ex) {
      setError(ex);
    } finally {
      setPending(false);
    }
  }
  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="txn-title">
      <h3 id="txn-title">Add a transaction</h3>
      <InstrumentSearch idPrefix="txn" selected={instrument} onSelect={setInstrument} />
      <FieldError id="txn-inst-err" msg={errs["instrument_id"]} />
      <div className="field">
        <label htmlFor="txn-type">Transaction type</label>
        <select id="txn-type" value={type} onChange={(e) => setType(e.target.value as "buy" | "sell")}>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="txn-date">Date</label>
        <input id="txn-date" type="date" max={today} value={date} onChange={(e) => setDate(e.target.value)}
          aria-invalid={Boolean(errs["txn_date"])} aria-describedby="txn-date-err" />
        <FieldError id="txn-date-err" msg={errs["txn_date"]} />
      </div>
      <div className="field">
        <label htmlFor="txn-units">Units</label>
        <input id="txn-units" className="input-amount" inputMode="decimal" value={units} onChange={(e) => setUnits(e.target.value)}
          aria-invalid={Boolean(errs["units"])} aria-describedby="txn-units-err" />
        <FieldError id="txn-units-err" msg={errs["units"]} />
      </div>
      <div className="field">
        <label htmlFor="txn-amount">Amount (₹, total for this transaction)</label>
        <span className="money">
          <input id="txn-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)}
            aria-invalid={Boolean(errs["amount"])} aria-describedby="txn-amount-hint txn-amount-err" />
        </span>
        <div id="txn-amount-hint" className="hint">
          {AMOUNT_RE.test(amountClean) ? inr(amountClean) : "Digits only, up to 2 decimals."} Paid for a buy; received for a sale.
        </div>
        <FieldError id="txn-amount-err" msg={errs["amount"]} />
      </div>
      {error && !server ? (
        <p className="callout callout--stale" role="alert">
          {txnErrorText(error)}
        </p>
      ) : server ? (
        <p className="callout callout--stale" role="alert">
          Not saved: the server rejected {Object.keys(server).length} field(s) (marked above).
        </p>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={pending}>
        {pending ? "Saving…" : "Save transaction"}
      </button>
    </form>
  );
}

function DeleteTxn({ portfolioId, t, onDone }: { portfolioId: string; t: TransactionRow; onDone: (msg: string) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const label = `${t.txn_type} of ${t.instrument_name} on ${dateLabel(t.txn_date)}`;
  async function go() {
    setPending(true);
    setErr(null);
    try {
      await api(`/api/portfolios/${encodeURIComponent(portfolioId)}/transactions/${encodeURIComponent(t.txn_id)}`, { method: "DELETE" });
      onDone(`Deleted the ${label}.`);
    } catch (e) {
      setErr(txnErrorText(e));
      setPending(false);
      setConfirming(false);
    }
  }
  return (
    <span className="row-tight">
      {confirming ? (
        <>
          <button type="button" className="btn btn--danger" onClick={go} disabled={pending} aria-label={`Confirm delete ${label}`}>
            {pending ? "Deleting…" : "Confirm delete"}
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => setConfirming(false)} disabled={pending}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" className="btn" onClick={() => setConfirming(true)} aria-label={`Delete ${label}`}>
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

/** Reload `reload` whenever `tick` changes after the first render (shared refresh signal after a change). */
function useReloadOn(tick: number, reload: () => void) {
  const first = useRef(tick);
  useEffect(() => {
    if (tick !== first.current) reload();
  }, [tick, reload]);
}

function Transactions({ portfolioId, tick, onChanged }: { portfolioId: string; tick: number; onChanged: (msg: string) => void }) {
  const list = useApi<TransactionList>(`/api/portfolios/${encodeURIComponent(portfolioId)}/transactions`);
  useReloadOn(tick, list.reload);
  let body: ReactNode;
  if (list.loading) body = <Loading label="Loading transactions" />;
  else if (list.error) body = <RequestError error={list.error} retry={list.reload} />;
  else if (!list.data || list.data.items.length === 0) body = <p className="small subtle">No transactions recorded in this portfolio.</p>;
  else
    body = (
      <div className="table-wrap table-wrap--scroll">
        <table className="table table--compact">
          <caption className="sr-only">Transactions</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Type</th>
              <th scope="col">Instrument</th>
              <th scope="col" className="num">Units</th>
              <th scope="col" className="num">Amount</th>
              <th scope="col">Entered via</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            {list.data.items.map((t) => (
              <tr key={t.txn_id}>
                <td>{dateLabel(t.txn_date)}</td>
                <td>{t.txn_type}</td>
                <td>{t.instrument_name}</td>
                <td className="num">{t.units ? unitsLabel(t.units) : "—"}</td>
                <td className="num">{inr(t.amount)}</td>
                <td className="small">{t.source === "csv_import" ? "file import (CSV/XLSX/CAS)" : "manual entry"}</td>
                <td>
                  <DeleteTxn portfolioId={portfolioId} t={t} onDone={onChanged} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  return (
    <details>
      <summary>Transactions{list.data ? ` (${list.data.items.length})` : ""}</summary>
      {body}
    </details>
  );
}

// ------------------------------------------------------------------ import (upload → preview → confirm → apply)

const REJECT_TEXT: Record<string, string> = {
  MISSING_NAME: "instrument name is empty",
  BAD_AMFI_CODE: "AMFI code is not a positive whole number",
  BAD_NUMBER: "a number is not in an accepted format",
  MISSING_UNITS: "units are missing",
  UNITS_NOT_POSITIVE: "units are zero or negative",
  COST_NEGATIVE: "cost is negative",
  BAD_DATE: "date format not accepted (use 2025-01-10, 10-01-2025 or 10-Jan-2025)",
  UNKNOWN_AMFI_CODE: "no stored instrument has this AMFI code",
  UNKNOWN_ISIN: "no stored instrument has this ISIN",
  AMBIGUOUS_ISIN: "more than one stored instrument has this ISIN",
  CONFLICTING_IDENTIFIERS: "the AMFI code and ISIN point to different instruments",
  UNIDENTIFIED: "no AMFI code or ISIN to match on (names are never matched)",
  MISSING_COST_BASIS: "cost_basis_inr is missing",
  COST_NOT_POSITIVE: "cost is zero",
  MISSING_PURCHASE_DATE: "purchase_date is missing",
  FUTURE_DATE: "purchase date is in the future",
  UNITS_PRECISION: "units have more than 6 decimals",
  AMOUNT_PRECISION: "cost has more than 2 decimals",
};

function ImportFlow({ portfolioId, nature, onApplied }: { portfolioId: string; nature: PortfolioNature; onApplied: (msg: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [encoding, setEncoding] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<{ kind: "status" | "alert"; msg: string } | null>(null);
  const [pending, setPending] = useState<"preview" | "apply" | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const resultRef = useRef<HTMLParagraphElement>(null);
  const previewHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);
  useEffect(() => {
    if (preview) previewHeading.current?.focus();
  }, [preview]);

  async function doPreview(e: FormEvent) {
    e.preventDefault();
    setResult(null);
    setPreview(null);
    if (!file) {
      setResult({ kind: "alert", msg: "Choose a .csv or .xlsx file first." });
      return;
    }
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("portfolio_id", portfolioId);
    if (encoding) form.append("encoding", encoding);
    setPending("preview");
    try {
      setPreview(await apiUpload<ImportPreview>("/api/holdings/import", form));
    } catch (ex) {
      setResult({ kind: "alert", msg: `The file was refused; nothing was stored. ${apiMessage(ex)}` });
    } finally {
      setPending(null);
    }
  }

  async function apply() {
    if (!preview) return;
    setPending("apply");
    try {
      const out = await api<ImportApplied>(`/api/holdings/import/${encodeURIComponent(preview.batch_id)}/apply`, {
        method: "POST",
        body: { sha256: preview.confirm_with.sha256 },
      });
      if (out.applied === true) {
        const msg = `Import applied: ${out.transactions_created} transaction(s) stored at ${utcStamp(out.applied_at)}; ${out.rows_rejected} row(s) were rejected and not stored. A backup was taken before the change.`;
        setPreview(null);
        setFile(null);
        setInputKey((k) => k + 1);
        setResult({ kind: "status", msg });
        onApplied(msg);
      } else {
        setResult({ kind: "alert", msg: "The server did not confirm that the import was applied. Do not assume anything was stored; check the transactions list." });
      }
    } catch (ex) {
      setResult({ kind: "alert", msg: `Not applied; nothing was stored. ${apiMessage(ex)}` });
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="card">
      <h3>Import holdings from a file</h3>
      <TemplateHelp />
      <form onSubmit={doPreview} noValidate>
        <div className="field">
          <label htmlFor="imp-file">Holdings file (.csv or .xlsx)</label>
          <input key={inputKey} id="imp-file" type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="field">
          <label htmlFor="imp-enc">Text encoding (CSV only)</label>
          <select id="imp-enc" value={encoding} onChange={(e) => setEncoding(e.target.value)}>
            <option value="">Automatic (UTF-8)</option>
            <option value="utf-8">UTF-8</option>
            <option value="cp1252">Windows-1252 (cp1252)</option>
            <option value="utf-16">UTF-16</option>
          </select>
        </div>
        <button type="submit" className="btn" disabled={pending !== null}>
          {pending === "preview" ? "Reading file…" : "Preview import"}
        </button>
      </form>
      {result ? (
        <p ref={resultRef} tabIndex={-1} className={result.kind === "alert" ? "callout callout--stale" : "callout"} role={result.kind}>
          {result.msg}
        </p>
      ) : null}
      {preview ? (
        <section aria-labelledby="imp-prev-title" className="import-preview">
          <h4 id="imp-prev-title" ref={previewHeading} tabIndex={-1}>
            Preview of {preview.label} — nothing stored yet
          </h4>
          <p className="small">
            {preview.note} Into: <NatureTag nature={nature} />
          </p>
          <p className="small mono break">SHA-256 {preview.file_sha256}</p>
          {preview.already_applied ? (
            <p className="callout callout--warn" role="alert">
              This exact file has already been imported into this portfolio; applying it again will be refused.
            </p>
          ) : null}
          {preview.warnings.length ? (
            <div className="callout callout--warn">
              <strong>Warnings</strong>
              <ul className="small">
                {preview.warnings.map((w, i) => (
                  <li key={`${i}-${w}`}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <h4>Rows that will be stored ({preview.will_store.length})</h4>
          {preview.will_store.length === 0 ? (
            <p className="small">No row can be stored from this file.</p>
          ) : (
            <div className="table-wrap table-wrap--scroll">
              <table className="table table--compact">
                <caption className="sr-only">Rows that will be stored</caption>
                <thead>
                  <tr>
                    <th scope="col" className="num">Row</th>
                    <th scope="col">Name in file</th>
                    <th scope="col">Matched instrument</th>
                    <th scope="col">Type</th>
                    <th scope="col">Date</th>
                    <th scope="col" className="num">Units</th>
                    <th scope="col" className="num">Cost</th>
                    <th scope="col">Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.will_store.map((r) => (
                    <tr key={r.row}>
                      <td className="num">{r.row}</td>
                      <td>{r.file_instrument_name}</td>
                      <td>
                        {r.instrument_name} <span className="mono small subtle">{r.instrument_id}</span>
                      </td>
                      <td>{r.txn_type}</td>
                      <td>{dateLabel(r.txn_date)}</td>
                      <td className="num">{r.units}</td>
                      <td className="num">{inr(r.amount)}</td>
                      <td className="small">{r.flags.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h4>Rows rejected ({preview.rejected.length})</h4>
          {preview.rejected.length === 0 ? (
            <p className="small">None.</p>
          ) : (
            <ul className="plain-list small" aria-label="Rejected rows">
              {preview.rejected.map((r, i) => (
                <li key={`${r.stage}-${r.line ?? r.row ?? i}-${i}`}>
                  {r.line !== undefined ? `File line ${r.line}` : `Data row ${r.row ?? "?"}`}: {REJECT_TEXT[r.reason] ?? r.reason}{" "}
                  <span className="mono subtle">({r.reason})</span>
                </li>
              ))}
            </ul>
          )}
          <div className="row">
            <button type="button" className="btn btn--primary" onClick={apply}
              disabled={pending !== null || preview.will_store.length === 0 || preview.already_applied}>
              {pending === "apply" ? "Applying…" : `Confirm and store ${preview.will_store.length} row(s)`}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setPreview(null)} disabled={pending !== null}>
              Discard preview
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ page

function SummaryView({ portfolioId, tick }: { portfolioId: string; tick: number }) {
  const sum = useApi<PortfolioSummary>(`/api/portfolios/${encodeURIComponent(portfolioId)}/summary`);
  useReloadOn(tick, sum.reload);
  const [explain, setExplain] = useState<Explained | null>(null);
  if (sum.loading) return <Loading label="Loading portfolio summary" />;
  if (sum.error || !sum.data) return <RequestError error={sum.error} retry={sum.reload} />;
  const s = sum.data;
  const nature = s.portfolio.nature;
  const fixture = s.flags.includes("CONTAINS_FIXTURE_DATA");
  return (
    <div className={`portfolio portfolio--${nature}`}>
      <div className={`portfolio-banner portfolio-banner--${nature}`} role="region" aria-label="Portfolio kind">
        <NatureTag nature={nature} /> <strong>{s.label}</strong> · {s.portfolio.name} · as of {dateLabel(s.as_of)}
      </div>
      {fixture ? (
        <p className="callout callout--warn fixture-zone" role="note">
          <FreshnessBadge freshness="FIXTURE" /> This summary uses FIXTURE (synthetic) prices for some holdings. These are not
          market data.
        </p>
      ) : null}
      {s.notes.length ? (
        <div className="callout callout--stale" role="note">
          <strong>Excluded from totals</strong>
          <ul className="small">
            {s.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {s.holdings.length === 0 ? (
        <Empty title="No holdings in this portfolio yet">
          <p>
            Next step: add a transaction below (search the instrument, then enter the date, units and amount as written on your
            statement), or import a CSV file of your holdings.
          </p>
          <TemplateHelp />
        </Empty>
      ) : (
        <>
          <Totals s={s} onExplain={setExplain} />
          <h2>Holdings</h2>
          <HoldingsTable rows={s.holdings} onExplain={setExplain} />
          <h2>Allocation</h2>
          <div className="grid grid--2">
            <AllocationTable a={s.allocation.by_kind} title="By instrument type" />
            <AllocationTable a={s.allocation.by_category} title="By category" />
          </div>
          <p className="small subtle">Valued holdings only; shares are rounded so they add up to exactly 100.00%.</p>
          <Concentration s={s} onExplain={setExplain} />
          <Ladder s={s} onExplain={setExplain} />
          <Maturities s={s} />
          <Dicgc s={s} onExplain={setExplain} />
        </>
      )}
      <p className="small subtle mono">{s.engine_version}</p>
      <ExplainDrawer item={explain} onClose={() => setExplain(null)} />
    </div>
  );
}

function PortfolioView({ p, tick, onChanged }: { p: PortfolioListItem; tick: number; onChanged: (msg: string) => void }) {
  return (
    <>
      <SummaryView portfolioId={p.portfolio_id} tick={tick} />
      <h2>Record changes</h2>
      <p className="small">
        Changes below go into <NatureTag nature={p.nature} /> {p.name}.
      </p>
      <Transactions portfolioId={p.portfolio_id} tick={tick} onChanged={onChanged} />
      <div className="grid grid--2">
        <AddTransactionForm portfolioId={p.portfolio_id} onSaved={onChanged} />
        <ImportFlow portfolioId={p.portfolio_id} nature={p.nature} onApplied={onChanged} />
        <CasImport portfolioId={p.portfolio_id} natureTag={<NatureTag nature={p.nature} />} onApplied={onChanged} />
      </div>
    </>
  );
}

export default function Overview() {
  const list = useApi<{ items: PortfolioListItem[] }>("/api/portfolios");
  const [params, setParams] = useSearchParams();
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  // Keep the last good list while it reloads after a change, so the open portfolio (and its forms) is not unmounted.
  const [kept, setKept] = useState<PortfolioListItem[] | null>(null);
  useEffect(() => {
    if (list.data) setKept(list.data.items);
  }, [list.data]);
  const items = list.data?.items ?? kept ?? [];
  const firstLoad = list.loading && kept === null;
  const wanted = params.get("p");
  const selected = items.find((p) => p.portfolio_id === wanted) ?? items.find((p) => p.nature === "actual") ?? items[0] ?? null;

  const choose = (id: string) => setParams({ p: id }, { replace: true });
  const changed = (msg: string) => {
    setNotice(msg);
    setTick((t) => t + 1);
    list.reload();
    setTimeout(() => noticeRef.current?.focus(), 0);
  };

  return (
    <section>
      <PageHeader
        title="Portfolio overview"
        purpose="What you hold, valued from stored NAVs only. Holdings without a fresh value are listed but kept out of every total."
      />
      {firstLoad ? null : <StartHere key={items.length === 0 ? "first-run" : "returning"} defaultOpen={items.length === 0} />}
      <Status msg={notice} focusRef={noticeRef} />
      {firstLoad ? (
        <Loading label="Loading portfolios" />
      ) : list.error ? (
        <RequestError error={list.error} retry={list.reload} />
      ) : items.length === 0 ? (
        <Empty title="No portfolio yet">
          <p>
            Create a portfolio first: <strong>actual</strong> for what you really hold, or <strong>hypothetical</strong> for a what-if.
            Then add transactions or import a CSV of your holdings.
          </p>
        </Empty>
      ) : selected ? (
        <>
          <PortfolioPicker items={items} value={selected.portfolio_id} onChange={choose} />
          <PortfolioView key={selected.portfolio_id} p={selected} tick={tick} onChanged={changed} />
        </>
      ) : null}
      <CreatePortfolioForm
        onCreated={(p) => {
          choose(p.portfolio_id);
          changed(`Created ${p.nature} portfolio “${p.name}”. It is now selected.`);
        }}
      />
      <p className="small subtle">
        Settings for your profile and data are on the <Link to="/settings">Settings</Link> page.
      </p>
    </section>
  );
}
