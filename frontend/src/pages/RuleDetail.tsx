import { Link, useParams } from "react-router-dom";
import { REQUIRED } from "../components/Disclosures";
import {
  AbstainBadge,
  conditionWords,
  earliestReviewText,
  FailingGate,
  GatePanel,
  isActionable,
  STATE_WORD,
} from "../components/GatePanel";
import { PageFooter, PageHeader } from "../components/PageHeader";
import { ErrorState, Loading } from "../components/States";
import { dateLabel, pct, roundHalfUp, utcStamp } from "../lib/format";
import {
  ruleDetailPath,
  type ExpectedExcess,
  type PowerInfo,
  type PublicationTag,
  type RuleDetailResponse,
  type ShadowRow,
} from "../lib/types-signals";
import { useApi } from "../lib/useApi";

// Rule detail (PLAN.md wave 2, C03; design-judgement.md §2.2 #12): status with the failing gate, the rule as committed,
// MinTRL next to the 80 %-power length, the earliest possible review, the post-publication tag, the ×0.5 decay haircut,
// the trial count, every gate, and the shadow forward ledger. Every number is a backend string; nothing is computed.

const PUBLICATION_WORD: Record<PublicationTag, string> = {
  POST_PUBLICATION: "Post-publication out-of-sample",
  PRE_PUBLICATION: "Pre-publication (in-sample for the literature)",
  MIXED: "Mixed: partly before publication",
  UNKNOWN: "Publication timing unknown",
};

const months = (v: string | null) => (v === null ? "not computed" : `${roundHalfUp(v, 1)} months`);

function StatusSection({ d }: { d: RuleDetailResponse }) {
  const live = isActionable(d.rule, d.gates);
  const cond = live && d.latest ? conditionWords(d.latest.condition_met, d.latest.direction, d.vocabulary) : null;
  return (
    <section aria-labelledby="status-title" className="card">
      <h2 id="status-title">Status</h2>
      <p>
        {live ? (
          <span className="badge badge--neutral">{cond?.text ?? "No entry or exit condition met"}</span>
        ) : (
          <AbstainBadge />
        )}{" "}
        {cond?.badge ? (
          <span className="badge badge--neutral" title="Shown because you opted in to BUY/SELL wording">
            {cond.badge}
          </span>
        ) : null}
      </p>
      {live ? (
        d.latest ? (
          <p className="small subtle">Condition as of {dateLabel(d.latest.as_of_date)}.</p>
        ) : null
      ) : (
        <p>
          First failing gate: <FailingGate gate={d.rule.failing_gate ?? d.gates.find((g) => !(g.status === "pass" && g.passed)) ?? null} />
        </p>
      )}
      <p className="small">
        Registry state: {STATE_WORD[d.rule.state] ?? d.rule.state}
        {d.rule.state_reason ? ` (${d.rule.state_reason})` : ""}, since {utcStamp(d.rule.state_changed_at)}. Registered{" "}
        {utcStamp(d.rule.registered_at)}.
      </p>
    </section>
  );
}

function PowerSection({ p }: { p: PowerInfo }) {
  return (
    <section aria-labelledby="power-title" className="card">
      <h2 id="power-title">How much evidence is needed</h2>
      <dl className="kv">
        <dt>Out-of-sample months available</dt>
        <dd>{p.n_oos_periods === null ? "not computed" : `${p.n_oos_periods} of ${p.min_oos_periods} needed`}</dd>
        <dt>Minimum track record length (MinTRL, 95 %)</dt>
        <dd>{months(p.min_trl_months)}</dd>
        <dt>Length for 80 % power</dt>
        <dd>{months(p.power80_months)}</dd>
      </dl>
      <p>
        <strong>{earliestReviewText(p.earliest_review)}</strong>
      </p>
      <p className="small subtle">
        MinTRL is the length at which a true edge of this size would just reach significance about half the time; the
        80 %-power length is how long it takes to find it reliably. Review date = registration + max(30, MinTRL) months.
        {p.formula_ids.length > 0 ? ` Formulas: ${p.formula_ids.join(", ")}.` : ""}
      </p>
    </section>
  );
}

/** The backend stores the mean edge per decision period; it is shown in that unit, never annualised here. */
function perPeriod(e: ExpectedExcess): string {
  if (e.period_months === 1) return "per month";
  if (e.period_months !== null && e.period_months > 1) return `per ${e.period_months}-month period`;
  return "per decision period";
}

function ExcessSection({ e }: { e: ExpectedExcess | null }) {
  return (
    <section aria-labelledby="excess-title" className="card">
      <h2 id="excess-title">Expected excess</h2>
      {e === null || e.raw === null ? (
        <p>Not available: no out-of-sample result yet.</p>
      ) : e.after_haircut === null ? (
        <p>Not shown: the ×{e.haircut_factor} decay haircut was not applied, so no figure is displayed.</p>
      ) : (
        <>
          <p>
            After the ×{e.haircut_factor} decay haircut: <strong>{`${pct(e.after_haircut)} ${perPeriod(e)}`}</strong>
          </p>
          <p className="small subtle">
            Out-of-sample backtest mean before the haircut: {`${pct(e.raw)} ${perPeriod(e)}`}. Published edges shrink once known, so
            any figure shown is halved. A backtest statistic, not a forecast. Formula: {e.formula_id}.
          </p>
        </>
      )}
    </section>
  );
}

function outcomeText(r: ShadowRow): string {
  if (r.outcome_status === "scored" && r.edge_after_cost_tax !== null) return `Scored: ${pct(r.edge_after_cost_tax)}`;
  if (r.outcome_status === "unscorable") return `Unscorable: ${r.unscorable_reason ?? "reason not reported"}`;
  return "Not yet due";
}

function ShadowSection({ d }: { d: RuleDetailResponse }) {
  const s = d.rule.shadow;
  return (
    <section aria-labelledby="shadow-title">
      <h2 id="shadow-title">Shadow record</h2>
      <p className="small">
        {s.evaluations > 0 && s.first_as_of
          ? `${s.evaluations} daily evaluations since ${dateLabel(s.first_as_of)}; ${s.outcomes_scored} scored, ${s.outcomes_unscorable} unscorable.`
          : "No shadow evaluations yet."}{" "}
        Recorded daily for research and scored at the rule's horizon. Never an action.
      </p>
      {d.shadow.length > 0 ? (
        <div className="table-wrap">
          <table className="table table--compact">
            <caption className="sr-only">Shadow evaluations, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Data date</th>
                <th scope="col">Scope</th>
                <th scope="col">Condition (recorded only)</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {d.shadow.map((r) => (
                <tr key={`${r.as_of_date}|${r.scope_id}`}>
                  <td>{dateLabel(r.as_of_date)}</td>
                  <td className="small">{r.scope_id}</td>
                  {/* Always neutral words here, whatever the vocabulary: a shadow row is never an action. */}
                  <td>{r.condition_met === null ? "Not evaluated" : conditionWords(r.condition_met, r.direction, "neutral").text}</td>
                  <td className="small">{outcomeText(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function Detail({ d }: { d: RuleDetailResponse }) {
  return (
    <>
      <StatusSection d={d} />
      <section aria-labelledby="rule-title" className="card">
        <h2 id="rule-title">The rule as registered</h2>
        <p>
          <code>{d.rule_text}</code>
        </p>
        <p className="small">Roles (bound to your funds in your own data, never in the public repo):</p>
        <ul className="small">
          {d.roles.map((r) => (
            <li key={r}>
              <code>{r}</code>
            </li>
          ))}
        </ul>
        <p className="small">
          <span className="chip">{PUBLICATION_WORD[d.publication.tag] ?? d.publication.tag}</span>
          {d.publication.source ? ` Source: ${d.publication.source}` : ""}
          {d.publication.published_on ? `, published ${dateLabel(d.publication.published_on)}.` : ""}
        </p>
        <p className="small">
          {d.rule.trial_count} trial{d.rule.trial_count === 1 ? "" : "s"} logged in family {d.rule.family}. Every
          configuration ever tested is counted, so trying many variants raises the bar (gate G8).
        </p>
        <p className="small subtle">Spec hash: {d.spec_hash}</p>
      </section>
      <PowerSection p={d.power} />
      <ExcessSection e={d.expected_excess} />
      <div className="card">
        <GatePanel gates={d.gates} />
      </div>
      <ShadowSection d={d} />
    </>
  );
}

export default function RuleDetail() {
  const { ruleId = "", version = "" } = useParams();
  const { data, error, loading, reload } = useApi<RuleDetailResponse>(ruleId && version ? ruleDetailPath(ruleId, version) : null);
  return (
    <div className="stack">
      <p className="small">
        <Link to="/signals">← All signals</Link>
      </p>
      <PageHeader
        title={data ? `${data.rule.rule_id} v${data.rule.version} — ${data.rule.title}` : `Rule ${ruleId}, version ${version}`}
        purpose="A pre-registered rule, the evidence it still needs, and its daily shadow record."
      />
      {loading ? <Loading label="Loading the rule" /> : null}
      {error ? <ErrorState error={error} retry={reload} /> : null}
      {data && !error ? <Detail d={data} /> : null}
      <PageFooter>{REQUIRED.footer}</PageFooter>
    </div>
  );
}
