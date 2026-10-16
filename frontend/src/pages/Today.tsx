import { useEffect, useState } from "react";
import { ActionCard, cardTitleId, KIND_TITLE, LAYER_LABEL } from "../components/ActionCard";
import { ExplainDrawer } from "../components/ExplainDrawer";
import { NeedsList } from "../components/NeedsList";
import { PageFooter, PageHeader } from "../components/PageHeader";
import { Empty, ErrorState, Loading } from "../components/States";
import { ApiError } from "../lib/api";
import { dateLabel, utcStamp } from "../lib/format";
import type { Explained } from "../lib/types";
import {
  localIsoDate,
  NAV_MAX_BUSINESS_DAYS,
  NAV_MAX_CALENDAR_DAYS,
  snapshotIsStale,
  SNAPSHOT_PATH,
  TODAY_PATH,
  type SnapshotComputed,
  type SuppressedView,
  type TodayResponse,
} from "../lib/types-actions";
import { useApi, useMutation } from "../lib/useApi";

/** Today (`/`): what the user's own rules say, read from the stored daily snapshot in ONE request. The engine never
 * runs on page load; "No action needed" and ABSTAIN are first-class results, not errors (design-risk-first.md §11;
 * design-judgement.md grafts 7–9). A snapshot is computed by the hosted morning job or, on the user's explicit request,
 * by "Compute today's cards" (POST /api/today/snapshot; local mode has no scheduler). */
export default function Today() {
  const { data, error, loading, reload } = useApi<TodayResponse>(TODAY_PATH);
  const [explain, setExplain] = useState<Explained | null>(null);
  const [showAll, setShowAll] = useState(false);
  const compute = useMutation<Record<string, never>, SnapshotComputed>("POST", SNAPSHOT_PATH);
  const [computed, setComputed] = useState<SnapshotComputed | null>(null);
  // The viewer's calendar date, only to judge the snapshot's age (the snapshot itself is never recomputed here).
  const today = localIsoDate(new Date());
  const stale = Boolean(data?.snapshot_id && data.as_of && snapshotIsStale(data.as_of, today));

  async function runCompute() {
    setComputed(null);
    const out = await compute.run({});
    if (out) {
      setComputed(out);
      setShowAll(false);
      reload();
    }
  }

  const meta = data?.snapshot_id ? (
    <span className="small subtle">
      Data as of {data.as_of ? dateLabel(data.as_of) : "—"} · computed {data.computed_at ? utcStamp(data.computed_at) : "—"} · snapshot{" "}
      <span className="mono">{data.snapshot_id.slice(0, 12)}</span>
    </span>
  ) : null;

  // In the header so it stays mounted (and keeps focus) while the page reloads after a compute.
  const actions = (
    <div>
      <button type="button" className="btn" disabled={compute.pending} onClick={() => void runCompute()}>
        Compute today&apos;s cards
      </button>
      {/* aria-live rather than role=status: the page's first status is the result heading below. */}
      <div className="small subtle" aria-live="polite">
        {compute.pending ? "Computing from your current data…" : computed ? `Computed from data as of ${dateLabel(computed.as_of)}.` : null}
      </div>
      {compute.error ? (
        <p className="field-error" role="alert">
          Not computed ({compute.error instanceof ApiError ? compute.error.code : "REQUEST_FAILED"}). Nothing is shown rather than a guess.
        </p>
      ) : null}
    </div>
  );

  return (
    <>
      <PageHeader
        title="Today"
        purpose="What your own rules say needs doing, highest-protection layer first. Every number opens its formula and source."
        meta={meta}
        actions={actions}
      />
      {loading && !data ? <Loading label="Loading today's cards" /> : null}
      {error ? <ErrorState error={error} retry={reload} /> : null}
      {data && !error ? (
        <TodayBody data={data} stale={stale} showAll={showAll} onShowAll={() => setShowAll(true)} onExplain={setExplain} />
      ) : null}
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

function StaleNotice({ data }: { data: TodayResponse }) {
  return (
    <div className="callout callout--stale">
      <h2 className="state__title">These cards may be out of date</h2>
      <p>
        They were computed {data.computed_at ? utcStamp(data.computed_at) : "at an unknown time"} from data as of{" "}
        {data.as_of ? dateLabel(data.as_of) : "an unknown date"}, which is more than {NAV_MAX_BUSINESS_DAYS} business days or{" "}
        {NAV_MAX_CALENDAR_DAYS} calendar days ago. What they say may no longer hold. Use “Compute today&apos;s cards” to recompute
        them from your current data before acting on them.
      </p>
    </div>
  );
}

function StateHeading({ data, stale }: { data: TodayResponse; stale: boolean }) {
  const asOf = data.as_of ? dateLabel(data.as_of) : "an unknown date";
  if (data.state === "NOTHING_NEEDED")
    return (
      <div className="state state--empty" role="status">
        <h2 className="state__title">{stale ? `No action needed on data as of ${asOf}` : "No action needed"}</h2>
        <p>
          {stale
            ? `Every rule you set was within its limits on data as of ${asOf}. That data is out of date, so this may no longer hold.`
            : `Every rule you set is within its limits on data as of ${asOf}.`}
        </p>
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
  stale,
  showAll,
  onShowAll,
  onExplain,
}: {
  data: TodayResponse;
  stale: boolean;
  showAll: boolean;
  onShowAll: () => void;
  onExplain: (e: Explained) => void;
}) {
  const limit = Math.max(1, data.top_n);
  const firstHidden = data.cards[limit];
  // "Show N more" removes itself: move focus to the first card it revealed (WCAG 2.4.3). Keyed on showAll only, so a
  // data change never moves focus by itself.
  useEffect(() => {
    if (showAll && firstHidden) document.getElementById(cardTitleId(firstHidden))?.focus();
  }, [showAll]);
  if (data.state === "NO_SNAPSHOT" || data.snapshot_id === null)
    return (
      <Empty title="No snapshot yet">
        <p>
          Today’s cards are computed from a stored snapshot, never on page load. Use “Compute today&apos;s cards” above to compute
          one now from your current data; hosted, the morning job also fills this page. Nothing is shown until then rather than a
          guess.
        </p>
      </Empty>
    );
  const visible = showAll ? data.cards : data.cards.slice(0, limit);
  const more = data.cards.length - visible.length;
  return (
    <>
      {stale ? <StaleNotice data={data} /> : null}
      <StateHeading data={data} stale={stale} />
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
