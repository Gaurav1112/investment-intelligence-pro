import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { compareDecimal } from "../components/DataTable";
import { Disclosure } from "../components/Disclosures";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { FundFactsPanel } from "../components/FundFactsPanel";
import { Empty, ErrorState, Loading } from "../components/States";
import { ApiError } from "../lib/api";
import { dateLabel, inr, utcStamp } from "../lib/format";
import type { ExitLoad, Freshness, InstrumentDetailResponse, SeriesPoint } from "../lib/types";
import { useApi } from "../lib/useApi";
import { exitLoadHref, exitLoadText } from "./MfExplorer";
import { kindLabel } from "../lib/kinds";
import type { BondList } from "../lib/types-bonds";
import {
  CiteLink,
  errorText,
  FD_RATE_STALE_DAYS,
  ManualAge,
  navLabel,
  OriginBadge,
  QuoteAge,
  QuoteCell,
  ratePct,
  RatingCell,
  TBILL_FRESH_DAYS,
} from "./FixedIncome";

const MAX_ROWS = 50;

type SeriesKind = "nav" | "yield";
const fmtValue = (k: SeriesKind, v: string) => (k === "nav" ? navLabel(v) : ratePct(v));

function parseExitLoad(raw: string | null): ExitLoad | null | "unreadable" {
  if (!raw) return null;
  try {
    const x = JSON.parse(raw) as ExitLoad;
    return typeof x.days === "number" && typeof x.rate === "string" ? x : "unreadable";
  } catch {
    return "unreadable";
  }
}

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} className="kv__row">
          <dt>{k}</dt>
          <dd>{v ?? <span className="subtle">not stored</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

const orNot = (v: string | null | undefined) => (v ? v : <span className="subtle">not stored</span>);

function Terms({ d }: { d: InstrumentDetailResponse }) {
  const m = d.mf_schemes;
  const b = d.bond_terms;
  const t = d.deposit_terms;
  if (!m && !b && !t) return <p className="subtle">No terms are stored for this instrument.</p>;
  return (
    <>
      {m ? (
        <Kv
          rows={[
            ["AMC", m.amc],
            ["Category (as published)", m.category_raw],
            ["SEBI category", orNot(m.sebi_category)],
            ["Plan", orNot(m.plan)],
            ["Option", orNot(m.option_type)],
            ["Benchmark", orNot(m.benchmark)],
            ["Riskometer (AMC-reported)", orNot(m.riskometer)],
            ["Potential risk class", orNot(m.prc)],
            [
              "Exit load",
              (() => {
                const x = parseExitLoad(m.exit_load_json);
                if (x === null)
                  return (
                    <>
                      <span className="subtle">not entered</span> · <Link to={exitLoadHref(d.instrument.instrument_id, d.instrument.name)}>Enter exit load</Link>
                    </>
                  );
                if (x === "unreadable") return <span className="field-error">stored value is unreadable</span>;
                return (
                  <>
                    {exitLoadText(x)} <span className="small subtle">· as of {dateLabel(x.as_of)} · {x.citation}</span>
                  </>
                );
              })(),
            ],
            [
              "Expense ratio",
              m.expense_ratio ? (
                <>
                  {m.expense_ratio} <span className="small subtle">({m.expense_ratio_kind ?? "kind not stored"}, as stored{m.expense_as_of ? `, as of ${dateLabel(m.expense_as_of)}` : ""})</span>
                </>
              ) : (
                <span className="subtle">not stored</span>
              ),
            ],
          ]}
        />
      ) : null}
      {b ? (
        <Kv
          rows={[
            ["Face value", inr(b.face_value)],
            ["Coupon", b.coupon_freq === 0 ? "None (discount instrument)" : `${ratePct(b.coupon_rate)} a year, paid ${b.coupon_freq}× a year`],
            ["Issue date", b.issue_date ? dateLabel(b.issue_date) : <span className="subtle">not stored</span>],
            ["Maturity date", dateLabel(b.maturity_date)],
            ["Day count", b.daycount],
            ["Listed", b.listed ? "yes" : "no"],
            [
              "Credit rating",
              b.credit_rating ? `${b.credit_rating}${b.rating_agency ? ` (${b.rating_agency}${b.rating_date ? `, ${dateLabel(b.rating_date)}` : ""})` : ""}` : <span className="subtle">not stored</span>,
            ],
          ]}
        />
      ) : null}
      {t ? (
        <Kv
          rows={[
            ["Institution", t.institution],
            ["Rate", `${ratePct(t.rate)} a year, ${t.compounding} compounding`],
            ["Tenure", `${t.tenure_days} days`],
            ["Premature-withdrawal penalty", t.premature_penalty === null ? <span className="subtle">not entered (unknown)</span> : ratePct(t.premature_penalty)],
            ["DICGC-eligible institution type", t.dicgc_eligible ? "yes" : "no"],
            ["Rate as of", dateLabel(t.rate_as_of)],
            ["Citation", t.citation_url ?? <span className="subtle">none stored</span>],
          ]}
        />
      ) : null}
    </>
  );
}

function SeriesSection({ kind, points, fixture }: { kind: SeriesKind; points: SeriesPoint[]; fixture: boolean }) {
  const [asTable, setAsTable] = useState(false);
  const what = kind === "nav" ? "NAV" : "yield";
  const stats = useMemo(() => {
    if (!points.length) return null;
    let lo = points[0]!;
    let hi = points[0]!;
    for (const p of points) {
      if (compareDecimal(p.value, lo.value) < 0) lo = p;
      if (compareDecimal(p.value, hi.value) > 0) hi = p;
    }
    return { first: points[0]!, last: points[points.length - 1]!, lo, hi };
  }, [points]);
  // Number() is used for chart geometry only; every displayed value is formatted from the original string.
  const chartData = useMemo(
    () => points.map((p) => ({ date: p.observation_date, y: kind === "nav" ? Number(p.value) : Number(p.value) * 100, raw: p.value })),
    [points, kind],
  );
  const latestFirst = useMemo(() => [...points].reverse().slice(0, MAX_ROWS), [points]);

  if (!stats)
    return (
      <Empty title={`No ${what} observations stored`}>
        {kind === "nav" ? (
          <p>
            Use “Backfill history” on the <Link to="/mf">Mutual funds</Link> page to store this scheme&apos;s NAV history from AMFI.
          </p>
        ) : (
          <p>No dated values are stored for this instrument.</p>
        )}
      </Empty>
    );

  const summary =
    `${points.length} ${what} observation${points.length === 1 ? "" : "s"} from ${dateLabel(stats.first.observation_date)} to ` +
    `${dateLabel(stats.last.observation_date)}. Latest ${fmtValue(kind, stats.last.value)} on ${dateLabel(stats.last.observation_date)}; ` +
    `lowest ${fmtValue(kind, stats.lo.value)} on ${dateLabel(stats.lo.observation_date)}; ` +
    `highest ${fmtValue(kind, stats.hi.value)} on ${dateLabel(stats.hi.observation_date)}.`;

  return (
    <>
      <h2>{kind === "nav" ? "NAV history" : "Yield history"}</h2>
      <p id="series-summary">{summary}</p>
      {kind === "nav" ? <Disclosure kind="past_performance" /> : null}
      <div className="row">
        <button type="button" className="btn" aria-pressed={asTable} onClick={() => setAsTable((x) => !x)}>
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>
      <figure className={`chart${fixture ? " fixture-zone" : ""}`} aria-describedby="series-summary">
        {fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
        {asTable ? (
          <div className="table-wrap table-wrap--scroll">
            <table className="table table--compact">
              <caption className="sr-only">All {what} values in the chart, oldest first</caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col" className="num">
                    {kind === "nav" ? "NAV per unit" : "Yield"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.observation_date + p.source_id}>
                    <td className="nowrap">{dateLabel(p.observation_date)}</td>
                    <td className="num">{fmtValue(kind, p.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="chart-scroll" aria-hidden="true">
            <LineChart width={720} height={260} data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d: string) => dateLabel(d)} minTickGap={40} tick={{ fontSize: 11 }} />
              <YAxis
                domain={["auto", "auto"]}
                tick={{ fontSize: 11 }}
                width={72}
                tickFormatter={(v: number) => (kind === "nav" ? `₹${v}` : `${v} %`)}
              />
              <Tooltip
                formatter={(_v, _n, item) => [fmtValue(kind, (item.payload as { raw: string }).raw), kind === "nav" ? "NAV" : "Yield"]}
                labelFormatter={(d) => dateLabel(String(d))}
              />
              <Line type="linear" dataKey="y" stroke="var(--accent)" dot={points.length < 40} isAnimationActive={false} />
            </LineChart>
          </div>
        )}
        <figcaption className="small subtle">
          {kind === "nav" ? "NAV per unit as published (₹). The vertical axis does not start at zero." : "Yield as entered (% a year)."}
        </figcaption>
      </figure>

      <h2>Stored observations</h2>
      <p className="small muted">
        Showing {latestFirst.length} of {points.length} (latest first).
      </p>
      <div className="table-wrap table-wrap--tall">
        <table className="table table--compact">
          <caption className="sr-only">Stored observations, latest first</caption>
          <thead>
            <tr>
              <th scope="col">Observation date</th>
              <th scope="col" className="num">
                Value
              </th>
              <th scope="col">Quality</th>
              <th scope="col">Source</th>
              <th scope="col">Retrieved</th>
            </tr>
          </thead>
          <tbody>
            {latestFirst.map((p) => (
              <tr key={p.observation_date + p.source_id} className={p.quality_status === "fixture" ? "fixture-zone" : undefined}>
                <td className="nowrap">{dateLabel(p.observation_date)}</td>
                <td className="num">{fmtValue(kind, p.value)}</td>
                <td>
                  {p.quality_status === "fixture" ? (
                    <FreshnessBadge freshness="FIXTURE" />
                  ) : p.quality_status === "manual" ? (
                    <FreshnessBadge freshness="MANUAL" />
                  ) : (
                    <span className="small">{p.quality_status}</span>
                  )}
                </td>
                <td className="small">
                  {p.source_id}
                  <div className="subtle mono">{p.source_url}</div>
                </td>
                <td className="small">{safeStamp(p.retrieved_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const BOND_KINDS = new Set(["gsec", "sdl", "corp_bond"]);

/** Latest cited price or yield, its freshness, the rating and the stored terms, from the same list the Fixed income page
 * uses (GET /api/bonds). A new quote is recorded by entering the bond again with the same ISIN. */
function BondQuotePanel({ instrumentId }: { instrumentId: string }) {
  const res = useApi<BondList>("/api/bonds");
  let body: ReactNode;
  if (res.loading) body = <p className="small subtle">Loading the latest quote…</p>;
  else if (res.error) body = <p className="small field-error">The latest quote could not be loaded: {errorText(res.error)}</p>;
  else {
    const item = res.data?.items.find((b) => b.instrument_id === instrumentId);
    if (!item) body = <p className="small subtle">No stored terms or quote were found for this bond.</p>;
    else {
      const t = item.terms;
      body = (
        <Kv
          rows={[
            ["Price or yield", <QuoteCell key="q" item={item} />],
            ["Quote date and freshness", <QuoteAge key="a" item={item} />],
            ["Quote source", <CiteLink key="c" url={item.quote?.citation_url} />],
            ["Credit", <RatingCell key="r" item={item} />],
            ["Issuer", t?.issuer ?? <span className="subtle">not stored</span>],
            [
              "Trading spread",
              t?.transaction_spread ? ratePct(t.transaction_spread) : <span className="subtle">not entered (flagged as unknown)</span>,
            ],
            [
              "Call dates",
              t && t.calls.length ? (
                t.calls.map((c) => `${dateLabel(c.call_date)} at ${c.call_price} per ₹100`).join("; ")
              ) : (
                <span className="subtle">none</span>
              ),
            ],
          ]}
        />
      );
    }
  }
  return (
    <section aria-labelledby="bond-quote-h">
      <h2 id="bond-quote-h">Latest price or yield</h2>
      {body}
      <p className="small subtle">
        To record a newer price or yield, enter this bond again with the same ISIN on <Link to="/fi">Fixed income</Link> (Bonds tab) with
        the new quote and its citation. The latest quote dated on or before today is used; one older than{" "}
        {res.data?.quote_stale_after_days ?? 7} days is excluded.
      </p>
    </section>
  );
}

function safeStamp(iso: string): string {
  try {
    return utcStamp(iso);
  } catch {
    return iso;
  }
}

function HeaderFreshness({ d }: { d: InstrumentDetailResponse }) {
  const fixture = d.instrument.origin === "fixture";
  if (d.freshness) return <FreshnessBadge freshness={d.freshness.badge as Freshness} date={d.freshness.observed} />;
  if (d.deposit_terms) return <ManualAge asOf={d.deposit_terms.rate_as_of} staleAfter={FD_RATE_STALE_DAYS} fixture={fixture} />;
  const last = d.series.points[d.series.points.length - 1];
  if (last) return <ManualAge asOf={last.observation_date} staleAfter={TBILL_FRESH_DAYS} fixture={fixture} />;
  return <FreshnessBadge freshness="UNKNOWN" />;
}

export default function InstrumentDetail() {
  const { id = "" } = useParams();
  const res = useApi<InstrumentDetailResponse>(`/api/instruments/${encodeURIComponent(id)}`);
  if (res.loading) return <Loading label="Loading instrument" />;
  if (res.error instanceof ApiError && res.error.status === 404)
    return (
      <Empty title="No instrument with this id is stored">
        <p>
          <code>{id}</code> is not in the local store. Browse <Link to="/mf">Mutual funds</Link> or <Link to="/fi">Fixed income</Link>.
        </p>
      </Empty>
    );
  if (res.error) return <ErrorState error={res.error} retry={res.reload} />;
  if (!res.data) return null;
  const d = res.data;
  const i = d.instrument;
  const fixture = i.origin === "fixture";
  const kind: SeriesKind = d.series.series_id.startsWith("nav:") ? "nav" : "yield";
  return (
    <section className={fixture ? "fixture-zone" : undefined}>
      <header className="page-head">
        <div className="page-head__text">
          <h1>{i.name}</h1>
          <p className="small muted">
            {kindLabel(i.kind)}
            {i.amfi_code ? ` · AMFI code ${i.amfi_code}` : ""}
            {i.isin ? ` · ISIN ${i.isin}` : ""} · id <span className="mono">{i.instrument_id}</span>
          </p>
          <div className="page-head__meta">
            <OriginBadge origin={i.origin} />
            <HeaderFreshness d={d} />
          </div>
        </div>
        <div className="page-head__actions">
          <Link className="btn" to={`/compare?ids=${encodeURIComponent(i.instrument_id)}`}>
            Add to comparison
          </Link>
          <Link className="btn" to="/evidence">
            Evidence viewer
          </Link>
        </div>
        <nav className="row small" aria-label="Analyse this instrument">
          <span>Analyse:</span>
          <Link to={`/risk?id=${encodeURIComponent(i.instrument_id)}`}>Risk</Link>
          <Link to={`/scenarios?tab=feasibility&id=${encodeURIComponent(i.instrument_id)}`}>Return-target feasibility</Link>
          <Link to={`/compare?ids=${encodeURIComponent(i.instrument_id)}`}>Compare</Link>
        </nav>
      </header>
      {fixture ? (
        <p className="callout callout--warn" role="note">
          <strong>FIXTURE — not market data.</strong> This instrument is synthetic development data.
        </p>
      ) : null}
      <h2>Terms</h2>
      <Terms d={d} />
      {i.kind === "mf_scheme" ? <FundFactsPanel instrumentId={i.instrument_id} /> : null}
      {BOND_KINDS.has(i.kind) ? <BondQuotePanel instrumentId={i.instrument_id} /> : null}
      {d.deposit_terms && !d.series.points.length ? (
        <p className="small subtle">Fixed-deposit rates are stored as terms, not as a dated series; there is no history to chart.</p>
      ) : (
        <SeriesSection kind={kind} points={d.series.points} fixture={fixture} />
      )}
    </section>
  );
}
