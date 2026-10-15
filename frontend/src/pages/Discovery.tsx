import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { exitLoadHref } from "./MfExplorer";
import { AiWording } from "../components/AiWording";
import { ExplainDrawer, ExplainedNumber } from "../components/ExplainDrawer";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { CodeLabel, CodeText, InstName } from "../components/Code";
import { PageFooter, PageHeader } from "../components/PageHeader";
import { ErrorState, Loading } from "../components/States";
import { TierLabel } from "../components/Tier";
import { api } from "../lib/api";
import { dateLabel } from "../lib/format";
import { useProfile } from "../lib/profile";
import { splitCode } from "../lib/codes";
import type { DiscoveryResult, DiscoveryRow, Explained } from "../lib/types";

const FLAG_TEXT: Record<string, string> = {
  TAX_RULE_UNVERIFIED: "tax rule unverified",
  TAX_CLASS_INFERRED_FROM_CATEGORY: "tax class inferred from category",
  LOW_EVIDENCE: "low evidence",
  EXCEEDS_DICGC_LIMIT_AT_THIS_BANK: "partly outside DICGC cover",
  NOT_DICGC_INSURED: "not DICGC insured",
  PREMATURE_PENALTY_UNKNOWN: "early-exit penalty unknown",
  LTCG_EXEMPTION_ASSUMED_UNUSED: "assumes your ₹1.25 lakh equity-gain exemption is unused",
};
const flagText = (f: string) =>
  FLAG_TEXT[f] ?? (f.startsWith("TAX_RULES_ASSUMED_UNCHANGED") ? "tax rules assumed beyond legislated year" : f.toLowerCase());

function Band({ row, onExplain }: { row: DiscoveryRow; onExplain: (e: Explained) => void }) {
  if (!row.outcome) return <span className="subtle">—</span>;
  const o = row.outcome;
  if (row.contractual)
    return (
      <span>
        <ExplainedNumber item={o.q50} onExplain={onExplain} /> <span className="small subtle">contractual</span>
      </span>
    );
  return (
    <span className="band band--stackable">
      <span className="band__k">low</span>
      <ExplainedNumber item={o.q05} onExplain={onExplain} />
      <span className="band__sep" aria-hidden="true">–</span>
      <span className="band__k">mid</span>
      <ExplainedNumber item={o.q50} onExplain={onExplain} />
      <span className="band__sep" aria-hidden="true">–</span>
      <span className="band__k">high</span>
      <ExplainedNumber item={o.q95} onExplain={onExplain} />
    </span>
  );
}

function ResultsTable({ rows, ranked, onExplain }: { rows: DiscoveryRow[]; ranked: boolean; onExplain: (e: Explained) => void }) {
  return (
    <div className="table-wrap">
      <table className={`table table--results${ranked ? "" : " table--sticky-first"}`}>
        <caption className="sr-only">{ranked ? "Options ordered by your criteria" : "Illustrative examples, not ranked"}</caption>
        <thead>
          <tr>
            {ranked ? <th scope="col" className="num rank">#</th> : null}
            <th scope="col" className="cell-name">Instrument</th>
            <th scope="col">Certainty</th>
            <th scope="col" className="num">
              Proceeds at your date
              <div className="small subtle">low – middle – high</div>
            </th>
            <th scope="col" className="num">
              Middle gain
              <div className="small subtle">over the period, not annualised</div>
            </th>
            <th scope="col">Loss history</th>
            <th scope="col" className="num">
              Days to cash
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.instrument_id} className={r.fixture ? "fixture-zone" : undefined}>
              {ranked ? <td className="num rank">{r.rank}</td> : null}
              <td className="cell-name">
                <Link to={`/i/${encodeURIComponent(r.instrument_id)}`}>
                  <InstName name={r.name} />
                </Link>
                <span className="inst-code">{r.instrument_id}</span>
                <div className="row small">
                  {r.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
                  {r.observed ? <span className="subtle">data as of {dateLabel(r.observed)}</span> : null}
                </div>
                {r.flags.length ? (
                  <details className="caveats">
                    <summary>
                      <span aria-hidden="true">⚠</span> {r.flags.length} caveat{r.flags.length === 1 ? "" : "s"}
                    </summary>
                    <ul className="small">
                      {r.flags.map((f) => (
                        <li key={f}>{flagText(f)}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </td>
              <td>
                <TierLabel tier={r.tier} />
              </td>
              <td className="num">
                <Band row={r} onExplain={onExplain} />
              </td>
              <td className="num">
                {r.outcome ? (
                  <span className={r.outcome.gain_q50.value.startsWith("-") ? "down" : "up"}>
                    {r.outcome.gain_q50.value.startsWith("-") ? "▼ " : "▲ "}
                    {r.outcome.gain_q50.pct}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="small">{r.loss_frequency?.display ?? "unknown"}</td>
              <td className="num">{r.days_to_cash}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Reason codes of one excluded row (bare codes or "CODE: detail"); free-text reasons are grouped as "other". */
function rowCodes(r: DiscoveryRow): string[] {
  const raw = r.exclusion_codes.length ? r.exclusion_codes : r.reasons;
  return raw.map((x) => splitCode(x).code ?? "OTHER");
}

/** Count of excluded instruments per reason code, most common first (an instrument can fail more than one constraint). */
export function ledgerCounts(rows: DiscoveryRow[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const r of rows) for (const c of new Set(rowCodes(r))) counts.set(c, (counts.get(c) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function AnswerCard({ data, onExplain }: { data: DiscoveryResult; onExplain: (e: Explained) => void }) {
  const first = data.ranked[0];
  const low = first?.outcome ? (first.contractual ? first.outcome.q50 : first.outcome.q05) : null;
  return (
    <div className="card answer" aria-live="polite">
      <p className="answer__eyebrow">Result under your constraints</p>
      <p className="answer__lead">
        {data.ranked.length === 1 ? "1 option passes" : `${data.ranked.length} options pass`} every constraint; {data.excluded.length} did not.
      </p>
      <dl className="answer__facts">
        {first ? (
          <div>
            <dt>First in the order</dt>
            <dd>
              <Link to={`/i/${encodeURIComponent(first.instrument_id)}`}>
                <InstName name={first.name} />
              </Link>
            </dd>
          </div>
        ) : null}
        {low ? (
          <div>
            <dt>{first?.contractual ? "Its proceeds on your date (contractual)" : "Its low-end proceeds on your date"}</dt>
            <dd>
              <ExplainedNumber item={low} onExplain={onExplain} />
            </dd>
          </div>
        ) : null}
        <div>
          <dt>Pass every constraint</dt>
          <dd>{data.ranked.length}</dd>
        </div>
        <div>
          <dt>Excluded</dt>
          <dd>
            {data.excluded.length} <span className="small subtle">see the ledger below</span>
          </dd>
        </div>
        {data.skipped_no_history > 0 ? (
          <div>
            <dt>Not evaluated (no NAV history)</dt>
            <dd className="num-dd">{data.skipped_no_history.toLocaleString("en-IN")}</dd>
          </div>
        ) : null}
      </dl>
      <p className="small subtle">
        Low end = the 5th-percentile outcome after costs and assumed tax. Past outcomes are not a forecast. Select a number to see how it was
        computed.
      </p>
    </div>
  );
}

function NextSteps({ data }: { data: DiscoveryResult }) {
  const codes = new Set(ledgerCounts(data.excluded).map(([c]) => c));
  const stale = [...codes].some((c) => c.startsWith("STALE") || c === "INSUFFICIENT_OR_STALE_DATA");
  return (
    <>
      <h3>What you can do next</h3>
      <ul className="next-steps">
        <li>
          Open the <strong>exclusion ledger</strong> below to see which constraint each instrument failed.
        </li>
        <li>
          <Link to="/onboarding">Review your objectives and constraints</Link>. Any change is yours to make; nothing is relaxed automatically.
        </li>
        {data.skipped_no_history > 0 ? (
          <li>
            {data.skipped_no_history.toLocaleString("en-IN")} scheme(s) were not evaluated for lack of NAV history.{" "}
            <Link to="/mf">Backfill history in Mutual funds</Link>.
          </li>
        ) : null}
        {stale ? (
          <li>
            Some instruments failed because data is missing or out of date — <Link to="/data-health">check Data health</Link>.
          </li>
        ) : null}
        <li>
          <Link to="/fi">Add T-bills or FDs</Link> from official pages.
        </li>
      </ul>
    </>
  );
}

const OBJECTIVE_LABEL: Record<string, string> = {
  A_capital_preservation: "A · Capital preservation",
  B_income: "B · Predictable proceeds",
  C_liquidity: "C · Liquidity",
  D_growth: "D · Risk-adjusted growth",
  E_aggressive_growth: "E · Aggressive growth",
};
const WORKER_LABEL: Record<string, string> = { quant: "ordering", skeptic: "skeptic review", portfolio_risk: "risk review" };
const workerOf = (ref: string) => WORKER_LABEL[ref.split(":")[0] ?? ""] ?? ref.split(":")[0];
const friendlyCriterion = (c: string) =>
  c.replace(/^Objective: (\w+)/, (_, k: string) => `Objective: ${OBJECTIVE_LABEL[k] ?? k}`);

export default function Discovery() {
  const { status } = useProfile();
  const [includeFixtures, setIncludeFixtures] = useState(false);
  const [data, setData] = useState<DiscoveryResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [explain, setExplain] = useState<Explained | null>(null);

  // Each run aborts the previous one, so a slower stale response (e.g. the fixtures toggle flipped twice) can never
  // overwrite a newer result; only the current request touches state.
  const inflight = useRef<AbortController | null>(null);
  const run = useCallback(() => {
    inflight.current?.abort();
    const ctl = new AbortController();
    inflight.current = ctl;
    setLoading(true);
    setError(null);
    api<DiscoveryResult>("/api/discover", {
      method: "POST",
      body: { include_fixtures: includeFixtures },
      signal: ctl.signal,
    })
      .then((d) => {
        if (!ctl.signal.aborted) setData(d);
      })
      .catch((e: unknown) => {
        if (!ctl.signal.aborted) setError(e);
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
  }, [includeFixtures]);
  useEffect(() => {
    run();
  }, [run, status]);
  useEffect(() => () => inflight.current?.abort(), []);

  if (loading && !data) return <Loading label="Evaluating instruments under your constraints" />;
  if (error) return <ErrorState error={error} retry={run} />;
  if (!data) return null;

  const ranked = data.status === "RANKED";
  const counts = ledgerCounts(data.excluded);
  return (
    <section aria-busy={loading}>
      <PageHeader
        title="Discovery"
        purpose="Which instruments fit this amount, date and objective, evaluated under your own constraints."
        meta={
          <span>
            {data.context.illustrative ? "Illustrative: " : "For "}
            <strong>{data.context.amount}</strong> until <strong>{dateLabel(data.context.withdrawal_date)}</strong> (
            {data.context.horizon_days} days) · after costs and tax ({data.context.tax_basis}) · analysis date{" "}
            {dateLabel(data.as_of)}
          </span>
        }
      />

      {data.contains_fixtures ? (
        <div className="callout callout--warn fixture-zone" role="note">
          <p>
            <FreshnessBadge freshness="FIXTURE" /> <strong>FIXTURE data present.</strong> Some instruments are synthetic development fixtures,
            not market data.
          </p>
          {data.mode === "PERSONALISED" ? (
            <label className="choice">
              <input type="checkbox" checked={includeFixtures} onChange={(e) => setIncludeFixtures(e.target.checked)} />
              <span>Include fixtures in the ordering (demonstration only)</span>
            </label>
          ) : null}
        </div>
      ) : null}

      {data.status === "ABSTAIN" ? (
        <div className="state" role="status">
          <h2>Not enough verified context to answer</h2>
          <p>The supervisor stopped before ordering anything because required context is missing or stale:</p>
          <ul>
            {data.abstain_reasons.map((r) => (
              <li key={r}>
                <CodeText raw={r} />
              </li>
            ))}
          </ul>
          <h3>What you can do next</h3>
          <ul className="next-steps">
            <li>
              <Link to="/onboarding">Review objectives</Link> — fill in any missing amount, date, objective or loss tolerance.
            </li>
            <li>
              <Link to="/data-health">Data health</Link> — check that the latest NAVs were fetched.
            </li>
            <li>
              <Link to="/fi">Add T-bills / FDs</Link> — enter them from official pages.
            </li>
          </ul>
        </div>
      ) : null}

      {data.status === "NO_SUITABLE_CANDIDATE" ? (
        <div className="state" role="status">
          <h2>{data.message}</h2>
          <p>
            This is a valid result, not an error. {data.excluded.length} instrument(s) were checked; each failed at least one
            of your constraints (see the ledger below). Keeping the money where it is remains an option.
          </p>
          <NextSteps data={data} />
        </div>
      ) : null}

      {data.status === "EXPLORATION" ? (
        <p className="callout callout--warn">
          Exploration mode: these are illustrative examples for ₹1,00,000 over {data.context.horizon_days} days, grouped by
          type and <strong>not ranked for you</strong>. <Link to="/onboarding">Add your details</Link> to see an ordering under
          your own constraints.
        </p>
      ) : null}

      {ranked ? <AnswerCard data={data} onExplain={setExplain} /> : null}

      {ranked ? (
        <details className="card card--quiet">
          <summary>
            <strong>How the order was decided</strong> <span className="small subtle">({data.criteria.length} criteria)</span>
          </summary>
          <p className="small">{data.report?.disclosures.find((d) => d.startsWith("Ordered by")) ?? ""}</p>
          <ul className="small">
            {data.criteria.map((c) => (
              <li key={c}>{friendlyCriterion(c)}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {data.ranked.length ? (
        <>
          <h2>{ranked ? "Options that pass every constraint" : "Examples"}</h2>
          <ResultsTable rows={data.ranked} ranked={ranked} onExplain={setExplain} />
        </>
      ) : null}

      {data.report ? (
        <div className="grid grid--2">
          <div className="card">
            <h3>What the analysis found</h3>
            <AiWording report={data.report}>
              {data.report.sections.map((s) => (
                <p key={`${s.worker}-${s.text}`} className={s.stance === "challenges" ? "callout callout--warn" : undefined}>
                  {s.text} <span className="small subtle">({WORKER_LABEL[s.worker] ?? s.worker})</span>
                </p>
              ))}
            </AiWording>
          </div>
          <div className="card">
            <h3>Disagreements</h3>
            {data.conflicts.length === 0 ? (
              <p className="subtle">None between the deterministic reviewers.</p>
            ) : (
              data.conflicts.map((c) => {
                const name = [...data.ranked, ...data.excluded].find((r) => r.instrument_id === c.subject)?.name ?? c.subject;
                return (
                  <p key={c.subject + c.topic} className="small">
                    On the <strong>{c.topic}</strong> for <strong>{name}</strong>, the {[...new Set(c.supporting.map(workerOf))].join(", ")}{" "}
                    supports it while the {[...new Set(c.challenging.map(workerOf))].join(", ")} raises{" "}
                    {c.challenging.length} challenge(s) above. {c.material ? "This is material — weigh it yourself." : ""}
                  </p>
                );
              })
            )}
          </div>
        </div>
      ) : null}

      {data.excluded.length ? (
        <details className="card" open={data.status === "NO_SUITABLE_CANDIDATE"}>
          <summary>
            <strong>Exclusion ledger</strong> ({data.excluded.length}) <span className="sr-only">by reason:</span>
            {counts.map(([code, n]) => (
              <span key={code} className="chip">
                {n} × {code === "OTHER" ? "Other reason" : <CodeLabel code={code} />}
              </span>
            ))}
          </summary>
          <div className="table-wrap table-wrap--tall">
            <table className="table table--sticky-first">
              <caption className="sr-only">Instruments that did not qualify and why</caption>
              <thead>
                <tr>
                  <th scope="col">Instrument</th>
                  <th scope="col">Why it did not qualify</th>
                </tr>
              </thead>
              <tbody>
                {data.excluded.map((r) => (
                  <tr key={r.instrument_id} className={`is-excluded${r.fixture ? " fixture-zone" : ""}`}>
                    <td className="cell-name">
                      <InstName name={r.name} code={r.instrument_id} />
                      {r.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
                    </td>
                    <td className="small">
                      <ul className="plain-list">
                        {(r.exclusion_codes.length ? r.exclusion_codes : r.reasons).map((x) => (
                          <li key={x}>
                            <CodeText raw={x} />
                            {x.startsWith("EXIT_LOAD_UNKNOWN") && !r.fixture ? (
                              <>
                                {" "}
                                <Link to={exitLoadHref(r.instrument_id, r.name)}>Enter exit load</Link>
                              </>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}

      <PageFooter>
        {data.skipped_no_history > 0 ? (
          <p>
            {data.skipped_no_history} scheme(s) were not evaluated because their NAV history has not been backfilled. Open a scheme
            to backfill its history from AMFI.
          </p>
        ) : null}
        {data.report?.disclosures.filter((d) => !d.startsWith("Personal research tool")).map((d) => (
          <p key={d}>{d}</p>
        ))}
        <p className="mono">
          run {data.run.run_id ?? "—"} · result hash {data.run.result_hash.slice(0, 16)}… · {Object.values(data.run.versions).join(" · ")}
        </p>
      </PageFooter>
      <ExplainDrawer item={explain} onClose={() => setExplain(null)} />
    </section>
  );
}
