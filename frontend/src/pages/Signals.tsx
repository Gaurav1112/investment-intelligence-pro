import { Link } from "react-router-dom";
import { REQUIRED } from "../components/Disclosures";
import { AbstainBadge, earliestReviewText, FailingGate, isActionable, STATE_WORD } from "../components/GatePanel";
import { PageFooter, PageHeader } from "../components/PageHeader";
import { Empty, ErrorState, Loading } from "../components/States";
import { dateLabel } from "../lib/format";
import { ruleDetailRoute, signalsPath, type ShadowSummary, type SignalRuleSummary, type SignalsResponse } from "../lib/types-signals";
import { useApi } from "../lib/useApi";

// Signals registry (PLAN.md wave 2, C03; design-risk-first.md §6). Every pre-registered timing rule with its honest
// status: ABSTAIN plus the first gate it fails, the trial count (G8), the growing shadow record and the earliest month a
// review is even possible. One GET; nothing is computed here.

function shadowText(s: ShadowSummary): string {
  if (s.evaluations === 0 || !s.first_as_of) return "No shadow evaluations yet";
  const n = `${s.evaluations} daily evaluation${s.evaluations === 1 ? "" : "s"} since ${dateLabel(s.first_as_of)}`;
  const scored = s.outcomes_scored + s.outcomes_unscorable;
  return scored > 0 ? `${n}; ${s.outcomes_scored} outcome${s.outcomes_scored === 1 ? "" : "s"} scored` : n;
}

function SignalCell({ rule }: { rule: SignalRuleSummary }) {
  if (isActionable(rule)) return <span className="badge badge--neutral">Active — open the rule for today's condition</span>;
  return <AbstainBadge />;
}

function RuleRow({ rule }: { rule: SignalRuleSummary }) {
  return (
    <tr>
      <th scope="row">
        <Link to={ruleDetailRoute(rule.rule_id, rule.version)}>
          {rule.rule_id} v{rule.version} — {rule.title}
        </Link>
        <div className="small subtle">{rule.family}</div>
      </th>
      <td>
        <SignalCell rule={rule} />
      </td>
      <td>{isActionable(rule) ? <span className="small subtle">All gates passed</span> : <FailingGate gate={rule.failing_gate} />}</td>
      <td>{STATE_WORD[rule.state] ?? rule.state}</td>
      <td className="num">{rule.trial_count}</td>
      <td className="small">{shadowText(rule.shadow)}</td>
      <td className="small">{earliestReviewText(rule.earliest_review)}</td>
    </tr>
  );
}

/** Families deliberately kept out of the registry, each with its abstention reason (design-risk-first.md §6.1, §6.6). */
const NOT_REGISTERED: [string, string][] = [
  ["Single-stock signals", "ABSTAIN (no_lawful_survivorship_free_data): no stock data is used (decision U-10)."],
  ["Valuation bands", "BLOCKED: the P/E data comes from NSE Indices, whose terms do not allow it here."],
  ["Factor timing, category rotation, past-winner funds", "Not registered: no evidence that would survive the gates."],
];

export default function Signals() {
  const { data, error, loading, reload } = useApi<SignalsResponse>(signalsPath);
  return (
    <div className="stack">
      <PageHeader
        title="Signals"
        purpose="Pre-registered timing rules and the evidence gates they must pass. Every rule starts as ABSTAIN; that is the expected result, not an error."
        meta={data?.as_of ? <span className="small subtle">Shadow record as of {dateLabel(data.as_of)}</span> : null}
      />
      {loading ? <Loading label="Loading the signal registry" /> : null}
      {error ? <ErrorState error={error} retry={reload} /> : null}
      {data && !error ? (
        data.rules.length === 0 ? (
          <Empty title="No rules are registered yet">
            <p>Rules are registered from the committed specs before any backtest runs.</p>
          </Empty>
        ) : (
          <section aria-labelledby="registry-title">
            <h2 id="registry-title" className="sr-only">
              Registered rules
            </h2>
            <div className="table-wrap">
              <table className="table">
                <caption>Registered rules (ABSTAIN until every gate passes)</caption>
                <thead>
                  <tr>
                    <th scope="col">Rule</th>
                    <th scope="col">Signal</th>
                    <th scope="col">First failing gate</th>
                    <th scope="col">Registry state</th>
                    <th scope="col" className="num">
                      Trials logged
                    </th>
                    <th scope="col">Shadow record</th>
                    <th scope="col">Review</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rules.map((r) => (
                    <RuleRow key={`${r.rule_id}@${r.version}`} rule={r} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )
      ) : null}
      <section aria-labelledby="power-title" className="card card--quiet">
        <h2 id="power-title">Why everything abstains</h2>
        <p>
          The gates (out-of-sample length, deflated Sharpe, HAC t ≥ 3, costs and tax, a sealed vault) are close to
          unpassable on the available Indian Direct-plan history. This is intended: a rule that passes weaker gates is
          more likely to be luck. Each rule's page shows how many months of evidence it needs and the earliest month a
          review is possible.
        </p>
        <p className="small">
          The shadow record is written every day for research only. It is never shown as an action.
        </p>
      </section>
      <section aria-labelledby="not-registered-title" className="card card--quiet">
        <h2 id="not-registered-title">Not in the registry</h2>
        <ul>
          {NOT_REGISTERED.map(([what, why]) => (
            <li key={what}>
              <strong>{what}:</strong> {why}
            </li>
          ))}
        </ul>
      </section>
      <PageFooter>{REQUIRED.footer}</PageFooter>
    </div>
  );
}
