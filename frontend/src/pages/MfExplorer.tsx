import { useState, type FormEvent } from "react";
import { InstName } from "../components/Code";
import { PageHeader } from "../components/PageHeader";
import { Link } from "react-router-dom";
import { DataTable, type Column } from "../components/DataTable";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { Empty, ErrorState, Loading } from "../components/States";
import { api } from "../lib/api";
import { dateLabel, percentToFraction } from "../lib/format";
import type { ExitLoad, ExitLoadIn, InstrumentList, InstrumentListItem, RunSummary } from "../lib/types";
import { useApi } from "../lib/useApi";
import { useFocusAfter } from "../lib/useFocusAfter";
import {
  citationBody,
  CitationFields,
  citationProblems,
  daysBetween,
  EMPTY_CITATION,
  errorText,
  FieldError,
  navLabel,
  ratePct,
  todayIst,
  validationErrors,
  type CitationState,
} from "./FixedIncome";

/** "1.00 % if redeemed within 365 days" / "Nil" — with the date the user cited. */
export function exitLoadText(x: ExitLoad): string {
  const nil = /^0+(\.0+)?$/.test(x.rate) || x.days === 0;
  return nil ? "Nil" : `${ratePct(x.rate)} if redeemed within ${x.days} day${x.days === 1 ? "" : "s"}`;
}

/**
 * NAV freshness on the list. The authoritative check (AMFI SLO in business days, registry amfi.navall) runs on the
 * scheme page. Here only what is certain from calendar days is claimed: ≤ 1 day is end-of-day, > 5 days is stale
 * (the SLO's calendar cap). Anything between is not labelled either way.
 */
function NavFreshness({ row, today }: { row: InstrumentListItem; today: string }) {
  if (row.fixture) return <FreshnessBadge freshness="FIXTURE" date={row.last_nav_date} />;
  if (!row.last_nav_date) return <FreshnessBadge freshness="UNKNOWN" />;
  const age = daysBetween(row.last_nav_date, today);
  if (age <= 1) return <FreshnessBadge freshness="END_OF_DAY" date={row.last_nav_date} />;
  if (age > 5) return <FreshnessBadge freshness="STALE" date={row.last_nav_date} />;
  return (
    <span className="small">
      {dateLabel(row.last_nav_date)} <span className="subtle">({age} days; freshness checked on the scheme page)</span>
    </span>
  );
}

type Activity = { key: string; tone: "ok" | "warn"; text: string };

function jobErrorText(e: unknown): string {
  return e instanceof Error && e.message === "JOB_DID_NOT_FINISH"
    ? "the job did not finish after many steps; its progress is saved, so starting it again continues where it stopped."
    : errorText(e);
}

function runText(what: string, s: RunSummary): Activity {
  const ok = s.status === "ok";
  return {
    key: s.run_id,
    tone: ok ? "ok" : "warn",
    text:
      `${what}: status ${s.status.toUpperCase()} · rows ok ${s.rows_ok} · rows rejected ${s.rows_rejected} · stored ${s.stored}` +
      (s.detail ? ` · ${s.detail}` : "") +
      (s.status === "partial"
        ? /failed/i.test(s.detail ?? "")
          ? ` — some requests failed, so part of the data is missing; running it again fills the gaps.`
          : ` — everything that passed validation was stored; the rejected rows are ones AMFI publishes without a usable value (for example a NAV of 0 or "N.A.", or a malformed ISIN). Details in Data health.`
        : ok
          ? ""
          : ` — the run failed; nothing from the failed part was stored.`) +
      ` (run ${s.run_id})`,
  };
}

/** Hosted mode (ADR-0013) answers long jobs in bounded steps: `done: false` plus progress counts from the server.
 * Locally the server answers once with the run summary (no `done` field), so the loop ends after one call. */
export type JobStep = Partial<RunSummary> & {
  done?: boolean;
  phase?: "discovering" | "fetching" | "storing" | "complete";
  windows_done?: number;
  windows_total?: number;
  schemes_done?: number;
  schemes_total?: number;
};

export const MAX_JOB_STEPS = 200;

/** Plain-English progress for one step (counts are the server's; nothing is computed here). */
export function stepText(s: JobStep): string {
  if (s.phase === "discovering") return "finding AMFI's fund-house id…";
  if (s.phase === "storing") return `stored ${s.schemes_done ?? 0} of ${s.schemes_total ?? 0} schemes…`;
  return `fetched ${s.windows_done ?? 0} of ${s.windows_total ?? 0} date windows…`;
}

/** Call `step` until the server says the job is done; report each unfinished step. Bounded, never endless. */
export async function runUntilDone(step: () => Promise<JobStep>, onProgress: (s: JobStep) => void): Promise<RunSummary> {
  for (let i = 0; i < MAX_JOB_STEPS; i++) {
    const s = await step();
    if (s.done !== false) return s as RunSummary;
    onProgress(s);
  }
  throw new Error("JOB_DID_NOT_FINISH");
}

function ExitLoadForm({ row, onDone, onCancel }: { row: InstrumentListItem; onDone: (msg: string) => void; onCancel: () => void }) {
  const [days, setDays] = useState(row.exit_load ? String(row.exit_load.days) : "");
  const [rate, setRate] = useState("");
  const [cite, setCite] = useState<CitationState>(EMPTY_CITATION);
  const [local, setLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const server = validationErrors(error);
  const errs = { ...(server ?? {}), ...local };

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problems: Record<string, string> = { ...citationProblems(cite) };
    if (!/^\d+$/.test(days.trim())) problems["days"] = "Enter a whole number of days (0 to 3650).";
    const fr = percentToFraction(rate);
    if (fr === null || fr === "invalid") problems["rate"] = "Enter the exit load as a plain number of percent, e.g. 1.";
    setLocal(problems);
    if (Object.keys(problems).length || fr === null || fr === "invalid") return;
    const body: ExitLoadIn = { days: Number.parseInt(days.trim(), 10), rate: fr, citation: citationBody(cite) };
    setPending(true);
    setError(null);
    try {
      await api(`/api/instruments/${encodeURIComponent(row.instrument_id)}/exit-load`, { method: "PUT", body });
      onDone(`Exit load saved for ${row.name}.`);
    } catch (err) {
      setError(err);
      setPending(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="el-title">
      <h3 id="el-title">Exit load for {row.name}</h3>
      <p className="small">
        Copy the exit load from the scheme&apos;s Scheme Information Document or Key Information Memorandum on the AMC or AMFI
        website. The page URL and date are stored as the citation.
      </p>
      <div className="field">
        <label htmlFor="el-days">Applies if redeemed within (days)</label>
        <input id="el-days" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)}
          aria-invalid={Boolean(errs["days"])} aria-describedby="el-days-err" />
        <FieldError id="el-days-err" msg={errs["days"]} />
      </div>
      <div className="field">
        <label htmlFor="el-rate">Exit load (% of redemption value)</label>
        <input id="el-rate" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)}
          aria-invalid={Boolean(errs["rate"])} aria-describedby="el-rate-hint el-rate-err" />
        <div id="el-rate-hint" className="hint">0 to 5 %. A graded load (different rates by day) cannot be entered yet; enter the highest step.</div>
        <FieldError id="el-rate-err" msg={errs["rate"]} />
      </div>
      <CitationFields prefix="el" value={cite} onChange={setCite} errors={errs} />
      {error ? (
        <p className="callout callout--stale" role="alert">
          Not saved: {server ? "the server rejected the values marked above." : errorText(error)}
        </p>
      ) : null}
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={pending}>
          {pending ? "Saving…" : "Save exit load"}
        </button>
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={pending}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function MfExplorer() {
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const list = useApi<InstrumentList>(`/api/instruments?kind=mf_scheme${q ? `&q=${encodeURIComponent(q)}` : ""}`);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [navPending, setNavPending] = useState(false);
  const [progress, setProgress] = useState("");
  const [editing, setEditing] = useState<InstrumentListItem | null>(null);
  const today = todayIst();

  const focusAfter = useFocusAfter();
  // Reloading the list replaces the table (and the focused Backfill button) with a loading state, so focus moves to the
  // result in the activity log instead of falling back to the page body (WCAG 2.4.3).
  const log = (a: Activity) => {
    setActivity((xs) => [a, ...xs].slice(0, 10));
    focusAfter("mf-activity");
  };

  async function fetchNavAll() {
    setNavPending(true);
    try {
      const s = await runUntilDone(
        () => api<JobStep>("/api/ingestion/amfi-navall", { method: "POST" }),
        (p) => setProgress(`AMFI latest NAV fetch: ${stepText(p)}`),
      );
      log(runText("AMFI latest NAV fetch", s));
      list.reload();
    } catch (e) {
      log({ key: `navall-${Date.now()}`, tone: "warn", text: `AMFI latest NAV fetch failed: ${jobErrorText(e)}` });
    } finally {
      setNavPending(false);
      setProgress("");
    }
  }

  async function backfill(row: InstrumentListItem) {
    if (!row.amfi_code) return;
    const code = row.amfi_code;
    setBusy((b) => ({ ...b, [row.instrument_id]: true }));
    try {
      const s = await runUntilDone(
        () => api<JobStep>(`/api/ingestion/backfill/${encodeURIComponent(code)}`, { method: "POST", body: {} }),
        (p) => setProgress(`History backfill for ${row.name}: ${stepText(p)}`),
      );
      log(runText(`History backfill for ${row.name}`, s));
      list.reload();
    } catch (e) {
      log({ key: `bf-${row.instrument_id}-${Date.now()}`, tone: "warn", text: `History backfill for ${row.name} failed: ${jobErrorText(e)}` });
    } finally {
      setBusy((b) => ({ ...b, [row.instrument_id]: false }));
      setProgress("");
    }
  }

  const columns: Column<InstrumentListItem>[] = [
    {
      key: "name",
      header: "Scheme",
      sortValue: (r) => r.name,
      render: (r) => (
        <>
          <Link to={`/i/${encodeURIComponent(r.instrument_id)}`}>
            <InstName name={r.name} />
          </Link>
          <span className="inst-code">{r.amfi_code ? `AMFI ${r.amfi_code}` : r.instrument_id}</span>
          {r.fixture ? (
            <div>
              <FreshnessBadge freshness="FIXTURE" />
            </div>
          ) : null}
        </>
      ),
    },
    { key: "cat", header: "Category", sortValue: (r) => r.category_raw, render: (r) => r.category_raw ?? <span className="subtle">—</span> },
    { key: "plan", header: "Plan", sortValue: (r) => r.plan, render: (r) => (r.plan ? r.plan[0]?.toUpperCase() + r.plan.slice(1) : "—") },
    {
      key: "nav",
      header: "Latest NAV",
      numeric: true,
      sortValue: (r) => r.last_nav,
      render: (r) => (r.last_nav ? navLabel(r.last_nav) : <span className="subtle">none stored</span>),
    },
    { key: "date", header: "NAV date", sortValue: (r) => r.last_nav_date, render: (r) => <NavFreshness row={r} today={today} /> },
    { key: "points", header: "NAV points stored", numeric: true, sortValue: (r) => r.nav_points, render: (r) => r.nav_points },
    {
      key: "exit",
      header: "Exit load",
      render: (r) =>
        r.exit_load ? (
          <span className="small">
            {exitLoadText(r.exit_load)}
            <span className="subtle"> · as of {dateLabel(r.exit_load.as_of)}</span>
          </span>
        ) : (
          <span className="subtle">not entered</span>
        ),
    },
    {
      key: "actions",
      header: "Actions",
      render: (r) => (
        <div className="row-tight">
          <button type="button" className="btn" disabled={busy[r.instrument_id] || r.fixture || !r.amfi_code}
            onClick={() => void backfill(r)} aria-label={`Backfill history for ${r.name}`}
            title={r.fixture ? "Fixture schemes have no AMFI history" : undefined}>
            {busy[r.instrument_id] ? "Backfilling…" : "Backfill history"}
          </button>
          <button type="button" className="btn" disabled={r.fixture} onClick={() => setEditing(r)} aria-label={`Enter exit load for ${r.name}`}>
            Enter exit load
          </button>
        </div>
      ),
    },
  ];

  const fetchButton = (
    <button type="button" className="btn btn--primary" onClick={() => void fetchNavAll()} disabled={navPending}>
      {navPending ? "Fetching NAVAll.txt from AMFI…" : "Fetch latest AMFI NAVs"}
    </button>
  );

  let body;
  if (list.loading) body = <Loading label="Loading stored schemes" />;
  else if (list.error) body = <ErrorState error={list.error} retry={list.reload} />;
  else if (!list.data || list.data.items.length === 0)
    body = q ? (
      <Empty title={`No stored scheme name contains “${q}”`}>
        <p>Search matches scheme names only. Clear the search to see every stored scheme.</p>
      </Empty>
    ) : (
      <Empty title="No mutual fund schemes are stored yet">
        <p>
          Nothing has been ingested. Fetching the latest AMFI NAV file stores direct-plan, growth-option, open-ended schemes
          (plus any you hold or watch) with today&apos;s NAV. Price history is then backfilled one scheme at a time.
        </p>
        {fetchButton}
      </Empty>
    );
  else {
    const items = list.data.items;
    body = (
      <>
        {items.some((r) => r.fixture) ? (
          <p className="callout callout--warn fixture-zone" role="note">
            <strong>FIXTURE data present.</strong> Rows marked FIXTURE are synthetic development data, not market data.
          </p>
        ) : null}
        <p className="small muted">
          {items.length} scheme{items.length === 1 ? "" : "s"}
          {list.data.truncated ? " (only the first 500 matches are shown — refine the search)" : ""}. Sorted by scheme name, not
          ranked for you. Select a column heading to sort by it.
        </p>
        <DataTable rows={items} columns={columns} rowKey={(r) => r.instrument_id} caption="Stored mutual fund schemes, sorted by name" initialSort={{ key: "name", dir: "ascending" }} tall stickyFirst />
      </>
    );
  }

  return (
    <section>
      <PageHeader
        title="Mutual funds"
        purpose={
          <>
            Schemes stored locally from AMFI&apos;s official NAV file. Sorted by name, not ranked for you.
          </>
        }
      />
      <div className="row">
        <form className="row" role="search" onSubmit={(e) => { e.preventDefault(); setQ(query.trim()); }}>
          <label htmlFor="mf-q" className="sr-only">Search scheme names</label>
          <input id="mf-q" className="input-wide" type="search" placeholder="Search scheme names" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button type="submit" className="btn">Search</button>
        </form>
        <span className="topbar__spacer" />
        {list.data && list.data.items.length > 0 ? fetchButton : null}
      </div>
      <p role="status" className="small muted" hidden={!progress}>
        {progress ? `In progress — ${progress} Keep this page open; each step continues where the last one stopped.` : ""}
      </p>
      <div id="mf-activity" tabIndex={-1} aria-live="polite" aria-label="Recent actions">
        {activity.length ? (
          <ul className="activity">
            {activity.map((a) => (
              <li key={a.key} className={a.tone === "ok" ? "callout small" : "callout callout--warn small"}>
                {a.text}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {editing ? (
        <ExitLoadForm
          key={editing.instrument_id}
          row={editing}
          onCancel={() => setEditing(null)}
          onDone={(m) => {
            setEditing(null);
            log({ key: `el-${Date.now()}`, tone: "ok", text: m });
            list.reload();
          }}
        />
      ) : null}
      {body}
      <p className="small subtle">
        AMFI data is for personal, non-commercial use only (AMFI terms of use). See <Link to="/data-health">Data health</Link> for
        source status and licence notes.
      </p>
    </section>
  );
}
