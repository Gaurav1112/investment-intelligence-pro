import { Link } from "react-router-dom";
import { Empty, ErrorState, Loading } from "../components/States";
import { TierLabel } from "../components/Tier";
import { dateLabel } from "../lib/format";
import type { MethodologyResponse, TaxRuleRow } from "../lib/types";
import { useApi } from "../lib/useApi";

const VERSION_LABEL: Record<string, string> = {
  ranking_policy: "Ranking policy",
  candidates: "Candidate engine",
  compliance: "Compliance phrase rules",
  discovery: "Discovery service",
};

const DISCLOSURE_LABEL: Record<string, string> = {
  past_performance: "Past performance",
  ranking: "Ordering",
  projection: "Projections",
  footer: "Every page",
  ai_disclosure: "Generated wording",
};

function Verification({ v }: { v: TaxRuleRow["verification"] }) {
  if (v === "P") return <span>P · verified against a primary source</span>;
  if (v === "S") return <span>S · verified against a secondary source</span>;
  return (
    <strong className="field-error">
      <span aria-hidden="true">⚠ </span>NV · not verified — pending professional review
    </strong>
  );
}

function SourceLink({ url }: { url: string | null }) {
  if (!url) return <span className="subtle">none recorded</span>;
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

function TaxTable({ rules }: { rules: TaxRuleRow[] }) {
  return (
    <div className="table-wrap">
      <table className="table table--compact">
        <caption className="sr-only">Tax rules in force in the engine</caption>
        <thead>
          <tr>
            <th scope="col">Rule</th>
            <th scope="col">Instrument class</th>
            <th scope="col">Effective from</th>
            <th scope="col">Effective to</th>
            <th scope="col">Verification</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.rule_id} className={r.verification === "NV" ? "is-unverified" : undefined}>
              <td className="mono small">{r.rule_id}</td>
              <td className="small">{r.instrument_class}</td>
              <td>{dateLabel(r.effective_from)}</td>
              <td>{r.effective_to ? dateLabel(r.effective_to) : <span className="subtle">open-ended</span>}</td>
              <td className="small">
                <Verification v={r.verification} />
              </td>
              <td className="small">
                <SourceLink url={r.source_url} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Methodology() {
  const m = useApi<MethodologyResponse>("/api/methodology");
  if (m.loading) return <Loading label="Loading methodology" />;
  if (m.error) return <ErrorState error={m.error} retry={m.reload} />;
  if (!m.data) return null;
  const d = m.data;
  const nv = d.tax?.rules.filter((r) => r.verification === "NV").length ?? 0;
  return (
    <section>
      <h1>Methodology</h1>
      <p className="muted">
        How results are produced, which versions are running, and which tax rules are applied. Full derivations are in{" "}
        <code>docs/finance/calculation-methodology.md</code> and <code>docs/finance/risk-methodology.md</code>.
      </p>

      <h2>Versions in use</h2>
      {Object.keys(d.versions).length === 0 ? (
        <p className="subtle">No version information was returned.</p>
      ) : (
        <dl className="kv">
          {Object.entries(d.versions).map(([k, v]) => (
            <div key={k} className="kv__row">
              <dt>{VERSION_LABEL[k] ?? k}</dt>
              <dd className="mono">{v}</dd>
            </div>
          ))}
        </dl>
      )}

      <h2>How options are ordered</h2>
      <div className="card">
        <h3>1. Eligibility comes before any ordering</h3>
        <p>
          Every instrument is first checked against your hard constraints: horizon fit (maturity, lock-in and exit-load window
          against your date), the chance and size of a loss at your date, days to cash, credit floor, the DICGC limit and
          whether there is enough data. An instrument that fails any check is excluded and listed with its reason; nothing
          later can bring it back.
        </p>
        <h3>2. Certainty tiers</h3>
        <ul className="plain-list">
          <li>
            <TierLabel tier="T1" /> — T-bills and G-secs held to maturity.
          </li>
          <li>
            <TierLabel tier="T2" /> — fixed deposits within DICGC cover; AAA bonds held to maturity.
          </li>
          <li>
            <TierLabel tier="T3" /> — overnight, liquid and money-market funds; bonds sold before maturity.
          </li>
          <li>
            <TierLabel tier="T4" /> — duration and credit funds, hybrid, equity and gold.
          </li>
        </ul>
        <h3>3. No composite score</h3>
        <p>
          Metrics such as Sharpe ratio, yield and volatility are undefined or not comparable across deposits, T-bills, bonds
          and funds (a deposit has zero measured volatility). They are never blended into one number. Eligible options are
          ordered step by step instead. For capital preservation: by tier, then by the low end of the outcome range, then by
          liquidity and cost — a higher middle outcome never makes up for a worse low end. For growth objectives: only options
          whose low end stays within your stated loss budget are kept, then ordered by a middle outcome reduced in proportion
          to its downside.
        </p>
        <h3>4. “No suitable candidate” is a valid result</h3>
        <p>
          If nothing passes every constraint, the answer is that nothing qualifies, with the exclusion reasons. Keeping the
          money where it is remains an option.
        </p>
        <h3>5. ABSTAIN when context is missing</h3>
        <p>
          If required context is missing or stale — your amount, date or objective, fresh source data, or loaded tax rules —
          the engine stops and says what is missing instead of ordering anything. Without your details the app stays in
          exploration mode, where examples are illustrative and not ranked for you (<Link to="/onboarding">add details</Link>).
        </p>
        <p className="small subtle">
          Reference: <code>docs/finance/risk-methodology.md</code> §9 (ranking heterogeneous instruments), §8 (minimum data
          requirements); <code>docs/finance/calculation-methodology.md</code> §1 (money and precision), §3 (fixed deposits), §4
          (T-bills and bonds).
        </p>
      </div>

      <h2>Tax rules</h2>
      {d.tax === null ? (
        <p className="callout callout--stale" role="alert">
          The tax rule file failed to load. Results that depend on tax abstain instead of guessing.
        </p>
      ) : (
        <>
          <p>
            Rule snapshot of {dateLabel(d.tax.snapshot_date)}, covering events up to {dateLabel(d.tax.coverage_to)}. Beyond that
            date, after-tax figures are labelled as assuming the rules stay unchanged.
          </p>
          {nv > 0 ? (
            <p className="callout callout--warn" role="note">
              {nv} rule{nv === 1 ? " is" : "s are"} <strong>not verified — pending professional review</strong>. Results using{" "}
              {nv === 1 ? "it" : "them"} are flagged “tax rule unverified”.
            </p>
          ) : null}
          {d.tax.rules.length === 0 ? <Empty title="No tax rules are defined" /> : <TaxTable rules={d.tax.rules} />}
          <p className="small subtle">
            Background: <code>docs/research/indian-instruments-and-tax.md</code>. Verification: P = verified against a primary
            source, S = verified against a secondary source, NV = not verified.
          </p>
        </>
      )}

      <h2>Disclosures</h2>
      <p className="small muted">These exact texts are shown wherever the matching kind of content appears.</p>
      {Object.keys(d.disclosures).length === 0 ? (
        <p className="subtle">No disclosure texts were returned.</p>
      ) : (
        <dl className="kv">
          {Object.entries(d.disclosures).map(([k, text]) => (
            <div key={k} className="kv__row">
              <dt>{DISCLOSURE_LABEL[k] ?? k}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      )}

      <h2>Data sources</h2>
      <p>
        Source status, licences and freshness rules are on <Link to="/data-health">Data health</Link>; the registry is documented
        in <code>docs/data/source-registry.md</code>.
      </p>
    </section>
  );
}
