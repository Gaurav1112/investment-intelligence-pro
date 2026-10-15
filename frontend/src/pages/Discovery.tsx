import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ExplainDrawer, ExplainedNumber } from "../components/ExplainDrawer";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { ErrorState, Loading } from "../components/States";
import { TierLabel } from "../components/Tier";
import { api } from "../lib/api";
import { dateLabel } from "../lib/format";
import { useProfile } from "../lib/profile";
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
    <span className="band">
      <ExplainedNumber item={o.q05} onExplain={onExplain} />
      <span className="subtle"> – </span>
      <ExplainedNumber item={o.q50} onExplain={onExplain} />
      <span className="subtle"> – </span>
      <ExplainedNumber item={o.q95} onExplain={onExplain} />
    </span>
  );
}

function ResultsTable({ rows, ranked, onExplain }: { rows: DiscoveryRow[]; ranked: boolean; onExplain: (e: Explained) => void }) {
  return (
    <div className="table-wrap">
      <table className="table table--results">
        <caption className="sr-only">{ranked ? "Options ordered by your criteria" : "Illustrative examples, not ranked"}</caption>
        <thead>
          <tr>
            {ranked ? <th scope="col">#</th> : null}
            <th scope="col">Instrument</th>
            <th scope="col">Certainty</th>
            <th scope="col" className="num">
              Proceeds at your date
              <div className="small subtle">low · middle · high</div>
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
              {ranked ? <td className="num">{r.rank}</td> : null}
              <td className="cell-name">
                <Link to={`/i/${encodeURIComponent(r.instrument_id)}`}>{r.name}</Link>
                <div className="row small">
                  {r.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
                  {r.observed ? <span className="subtle">data as of {dateLabel(r.observed)}</span> : null}
                </div>
                {r.flags.length ? <div className="small subtle caveats">⚠ {r.flags.map(flagText).join(" · ")}</div> : null}
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

  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    api<DiscoveryResult>("/api/discover", { method: "POST", body: { include_fixtures: includeFixtures } })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [includeFixtures]);
  useEffect(run, [run, status]);

  if (loading && !data) return <Loading label="Evaluating instruments under your constraints" />;
  if (error) return <ErrorState error={error} retry={run} />;
  if (!data) return null;

  const ranked = data.status === "RANKED";
  return (
    <section aria-busy={loading}>
      <h1>Discovery</h1>
      <p className="muted">
        {data.context.illustrative ? "Illustrative: " : "For "}
        <strong>{data.context.amount}</strong> until <strong>{dateLabel(data.context.withdrawal_date)}</strong> (
        {data.context.horizon_days} days) · after costs and tax ({data.context.tax_basis}) · analysis date{" "}
        {dateLabel(data.as_of)}
      </p>

      {data.contains_fixtures ? (
        <div className="callout callout--warn fixture-zone" role="note">
          <strong>FIXTURE data present.</strong> Some instruments are synthetic development fixtures, not market data.
          {data.mode === "PERSONALISED" ? (
            <label className="choice">
              <input type="checkbox" checked={includeFixtures} onChange={(e) => setIncludeFixtures(e.target.checked)} /> Include
              fixtures in the ordering (demonstration only)
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
              <li key={r}>{r}</li>
            ))}
          </ul>
          <div className="row">
            <Link className="btn" to="/onboarding">
              Review objectives
            </Link>
            <Link className="btn" to="/data-health">
              Data health
            </Link>
            <Link className="btn" to="/fi">
              Add T-bills / FDs
            </Link>
          </div>
        </div>
      ) : null}

      {data.status === "NO_SUITABLE_CANDIDATE" ? (
        <div className="state" role="status">
          <h2>{data.message}</h2>
          <p>
            This is a valid result, not an error. {data.excluded.length} instrument(s) were checked; each failed at least one
            of your constraints (see the ledger below). Keeping the money where it is remains an option.
          </p>
        </div>
      ) : null}

      {data.status === "EXPLORATION" ? (
        <p className="callout callout--warn">
          Exploration mode: these are illustrative examples for ₹1,00,000 over {data.context.horizon_days} days, grouped by
          type and <strong>not ranked for you</strong>. <Link to="/onboarding">Add your details</Link> to see an ordering under
          your own constraints.
        </p>
      ) : null}

      {ranked ? (
        <div className="card">
          <h2>Ordered by your criteria</h2>
          <p className="small">{data.report?.disclosures.find((d) => d.startsWith("Ordered by")) ?? ""}</p>
          <ul className="small">
            {data.criteria.map((c) => (
              <li key={c}>{friendlyCriterion(c)}</li>
            ))}
          </ul>
        </div>
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
            {data.report.sections.map((s) => (
              <p key={`${s.worker}-${s.text}`} className={s.stance === "challenges" ? "callout callout--warn" : undefined}>
                {s.text} <span className="small subtle">({s.worker})</span>
              </p>
            ))}
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
            <strong>Exclusion ledger</strong> ({data.excluded.length})
          </summary>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Instrument</th>
                  <th scope="col">Why it did not qualify</th>
                </tr>
              </thead>
              <tbody>
                {data.excluded.map((r) => (
                  <tr key={r.instrument_id} className={`is-excluded${r.fixture ? " fixture-zone" : ""}`}>
                    <td>{r.name}</td>
                    <td className="small">{(r.exclusion_codes.length ? r.exclusion_codes : r.reasons).join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}

      {data.skipped_no_history > 0 ? (
        <p className="small subtle">
          {data.skipped_no_history} scheme(s) were not evaluated because their NAV history has not been backfilled. Open a scheme
          to backfill its history from AMFI.
        </p>
      ) : null}

      {data.report?.disclosures.filter((d) => !d.startsWith("Personal research tool")).map((d) => (
        <p key={d} className="small subtle">
          {d}
        </p>
      ))}
      <p className="small subtle mono">
        run {data.run.run_id ?? "—"} · result hash {data.run.result_hash.slice(0, 16)}… · {Object.values(data.run.versions).join(" · ")}
      </p>
      <ExplainDrawer item={explain} onClose={() => setExplain(null)} />
    </section>
  );
}
