import { useState } from "react";
import { ActionCard, KIND_TITLE, LAYER_LABEL } from "../components/ActionCard";
import { ExplainDrawer } from "../components/ExplainDrawer";
import { NeedsList } from "../components/NeedsList";
import { PageFooter, PageHeader } from "../components/PageHeader";
import { Empty, ErrorState, Loading } from "../components/States";
import { dateLabel, utcStamp } from "../lib/format";
import type { Explained } from "../lib/types";
import { TODAY_PATH, type SuppressedView, type TodayResponse } from "../lib/types-actions";
import { useApi } from "../lib/useApi";

/** Today (`/`): what the user's own rules say, read from the stored daily snapshot in ONE request. The engine never
 * runs on page load; "No action needed" and ABSTAIN are first-class results, not errors (design-risk-first.md §11;
 * design-judgement.md grafts 7–9). */
export default function Today() {
  const { data, error, loading, reload } = useApi<TodayResponse>(TODAY_PATH);
  const [explain, setExplain] = useState<Explained | null>(null);
  const [showAll, setShowAll] = useState(false);

  const meta = data?.snapshot_id ? (
    <span className="small subtle">
      Data as of {data.as_of ? dateLabel(data.as_of) : "—"} · computed {data.computed_at ? utcStamp(data.computed_at) : "—"} · snapshot{" "}
      <span className="mono">{data.snapshot_id.slice(0, 12)}</span>
    </span>
  ) : null;

  return (
    <>
      <PageHeader
        title="Today"
        purpose="What your own rules say needs doing, highest-protection layer first. Every number opens its formula and source."
        meta={meta}
      />
      {loading && !data ? <Loading label="Loading today's cards" /> : null}
      {error ? <ErrorState error={error} retry={reload} /> : null}
      {data && !error ? <TodayBody data={data} showAll={showAll} onShowAll={() => setShowAll(true)} onExplain={setExplain} /> : null}
      <PageFooter>
        Output of rules you configured. Personal decision-support tool; not investment advice or research.
        {data?.engine_version ? (
          <span className="mono">
            {" "}
            · engine {data.engine_version} · rules {data.rules_version ?? "—"}
          </span>
        ) : null}
      </PageFooter>
      <ExplainDrawer item={explain} onClose={() => setExplain(null)} />
    </>
  );
}

function StateHeading({ data }: { data: TodayResponse }) {
  if (data.state === "NOTHING_NEEDED")
    return (
      <div className="state state--empty" role="status">
        <h2 className="state__title">No action needed</h2>
        <p>Every rule you set is within its limits on the latest data.</p>
      </div>
    );
  if (data.state === "ABSTAINED_ONLY")
    return (
      <div className="state state--empty" role="status">
        <h2 className="state__title">No action today: the engine abstained</h2>
        <p>
          Some inputs are missing, so the engine did not decide rather than guess. This is the expected result, not an error. Add the
          inputs under “Needs from you” to unlock the cards.
        </p>
      </div>
    );
  return null;
}

function Suppressed({ items }: { items: readonly SuppressedView[] }) {
  if (items.length === 0) return null;
  return (
    <details className="card card--quiet">
      <summary>
        {items.length} lower-layer card{items.length === 1 ? " is" : "s are"} held back until the higher-layer breach above is resolved
      </summary>
      <ul>
        {items.map((s) => (
          <li key={s.card_id}>
            {KIND_TITLE[s.kind]} <span className="small subtle">({s.layer} · {LAYER_LABEL[s.layer]})</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function TodayBody({
  data,
  showAll,
  onShowAll,
  onExplain,
}: {
  data: TodayResponse;
  showAll: boolean;
  onShowAll: () => void;
  onExplain: (e: Explained) => void;
}) {
  if (data.state === "NO_SNAPSHOT" || data.snapshot_id === null)
    return (
      <Empty title="No snapshot yet">
        <p>
          Today’s cards are computed once a day by the scheduled job, never on page load. Locally, run <code>make run</code>; hosted, the
          morning job fills this page. Nothing is shown until then rather than a guess.
        </p>
      </Empty>
    );
  const limit = Math.max(1, data.top_n);
  const visible = showAll ? data.cards : data.cards.slice(0, limit);
  const more = data.cards.length - visible.length;
  return (
    <>
      <StateHeading data={data} />
      <section aria-labelledby="today-cards">
        <h2 id="today-cards">What your rules say today</h2>
        {visible.map((c) => (
          <ActionCard key={c.card_id} card={c} snapshotId={data.snapshot_id} onExplain={onExplain} />
        ))}
        {more > 0 ? (
          <button type="button" className="btn btn--ghost" onClick={onShowAll}>
            Show {more} more
          </button>
        ) : null}
        <Suppressed items={data.suppressed} />
      </section>
      <section aria-labelledby="today-needs">
        <h2 id="today-needs">Needs from you</h2>
        <NeedsList needs={data.needs} onExplain={onExplain} />
      </section>
    </>
  );
}
