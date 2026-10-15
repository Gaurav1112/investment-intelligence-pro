import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorState, Loading } from "../components/States";
import { dateLabel, utcStamp } from "../lib/format";
import type { DataHealthResponse, IngestionRun, SourceHealth } from "../lib/types";
import { useApi } from "../lib/useApi";

const MODE_TEXT: Record<SourceHealth["mode"], { word: string; glyph: string; explain: string; cls: string }> = {
  live: { word: "FETCHED", glyph: "⇣", explain: "Fetched over the network when you run an ingestion.", cls: "badge--eod" },
  manual: { word: "MANUAL ONLY", glyph: "✎", explain: "Never fetched. Values exist only if you enter them with a citation.", cls: "badge--delayed" },
  disabled: { word: "DISABLED", glyph: "⊘", explain: "Never fetched and never used. Registered for reference only.", cls: "badge--stale" },
};

const LICENCE_TEXT: Record<SourceHealth["licence"], string> = {
  PERSONAL_USE_ONLY: "Personal, non-commercial use only",
  PUBLIC_GOVT: "Public government data",
  LICENSED: "Licensed data",
  UNKNOWN: "Licence unknown",
};

const STATUS_TEXT: Record<string, string> = {
  ok: "OK",
  partial: "PARTIAL — some rows rejected or missing",
  failed: "FAILED — nothing stored",
  held: "HELD — not applied",
  running: "RUNNING (or interrupted)",
};
const statusText = (s: string) => STATUS_TEXT[s] ?? s;

function stamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return utcStamp(iso);
  } catch {
    return iso;
  }
}

function LastRun({ run }: { run: SourceHealth["last_run"] }) {
  if (!run) return <span className="subtle">never run</span>;
  return (
    <div className="small">
      <strong className={run.status === "ok" ? undefined : "field-error"}>{statusText(run.status)}</strong>
      <div>finished {stamp(run.finished_at)}</div>
      <div>
        rows ok {run.rows_ok} · rejected {run.rows_rejected}
      </div>
      {run.error ? <div className="field-error mono">{run.error}</div> : null}
    </div>
  );
}

function SourceRow({ s }: { s: SourceHealth }) {
  const m = MODE_TEXT[s.mode];
  return (
    <tr className={s.mode === "disabled" ? "is-excluded" : undefined}>
      <td>
        <strong>{s.name}</strong>
        <div className="small subtle">
          <span className="mono">{s.source_id}</span> · {s.owner}
        </div>
        <div className="small">{s.official ? "Official source" : <strong>UNOFFICIAL — cross-check only</strong>}</div>
      </td>
      <td>
        <span className={`badge ${m.cls}`}>
          <span aria-hidden="true">{m.glyph}</span> {m.word}
        </span>
        <div className="small subtle">{m.explain}</div>
        {s.requires_configuration ? <div className="small subtle">Needs network access or configuration to run.</div> : null}
      </td>
      <td className="small">
        <strong>{LICENCE_TEXT[s.licence]}</strong>
        <div>{s.licence_note}</div>
        {s.terms_url ? (
          <a href={s.terms_url} target="_blank" rel="noreferrer noopener">
            Terms of use
          </a>
        ) : (
          <span className="subtle">No terms page recorded</span>
        )}
      </td>
      <td className="small">{s.freshness || <span className="subtle">not stated</span>}</td>
      <td>
        <LastRun run={s.last_run} />
      </td>
    </tr>
  );
}

function RunsTable({ runs }: { runs: IngestionRun[] }) {
  return (
    <div className="table-wrap">
      <table className="table table--compact">
        <caption className="sr-only">Recent ingestion runs, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Started</th>
            <th scope="col">Source</th>
            <th scope="col">Status</th>
            <th scope="col">Finished</th>
            <th scope="col" className="num">Rows ok</th>
            <th scope="col" className="num">Rejected</th>
            <th scope="col">Error</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td className="small">{stamp(r.started_at)}</td>
              <td className="mono small">{r.source_id}</td>
              <td className={r.status === "ok" ? "small" : "small field-error"}>{statusText(r.status)}</td>
              <td className="small">{stamp(r.finished_at)}</td>
              <td className="num">{r.rows_ok}</td>
              <td className="num">{r.rows_rejected}</td>
              <td className="small mono">{r.error ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const QUALITY_TEXT: Record<string, string> = {
  ok: "passed validation",
  stale: "stale",
  suspect: "suspect — flagged by a validator",
  rejected: "rejected — never used",
  fixture: "FIXTURE — synthetic, not market data",
  manual: "manual entry with citation",
};

export default function DataHealth() {
  const h = useApi<DataHealthResponse>("/api/data-health");
  if (h.loading) return <Loading label="Loading data health" />;
  if (h.error) return <ErrorState error={h.error} retry={h.reload} />;
  if (!h.data) return null;
  const d = h.data;
  const counts = Object.entries(d.observation_counts).sort(([a], [b]) => a.localeCompare(b));
  return (
    <section>
      <PageHeader
        title="Data health"
        purpose={
          <>
            Where each number comes from, whether it may be fetched, and what happened the last time it was. Live intraday feeds are not used; end-of-day data is the expected state.
          </>
        }
      />

      <h2>Sources</h2>
      {d.sources.length === 0 ? (
        <Empty title="No sources are registered" />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">Registered data sources</caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Mode</th>
                <th scope="col">Licence</th>
                <th scope="col">Freshness rule</th>
                <th scope="col">Last run</th>
              </tr>
            </thead>
            <tbody>
              {d.sources.map((s) => (
                <SourceRow key={s.source_id} s={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Tax rules</h2>
      {d.tax_rules_loaded ? (
        <p>
          Loaded. Coverage to <strong>{d.tax_rules_coverage_to ? dateLabel(d.tax_rules_coverage_to) : "—"}</strong>; after-tax
          results beyond that date are labelled as assuming unchanged rules. See <Link to="/methodology">Methodology</Link>.
        </p>
      ) : (
        <p className="callout callout--stale" role="alert">
          The tax rule file failed to load. Results that depend on tax abstain instead of guessing.
        </p>
      )}

      <h2>Stored observations by quality status</h2>
      {counts.length === 0 ? (
        <Empty title="No observations are stored yet">
          <p>
            Fetch the latest AMFI NAVs from <Link to="/mf">Mutual funds</Link>, or add T-bills and deposits on{" "}
            <Link to="/fi">Fixed income</Link>.
          </p>
        </Empty>
      ) : (
        <dl className="kv">
          {counts.map(([k, n]) => (
            <div key={k} className="kv__row">
              <dt>
                <span className="mono">{k}</span> <span className="small subtle">({QUALITY_TEXT[k] ?? "unrecognised status"})</span>
              </dt>
              <dd className="num">{n}</dd>
            </div>
          ))}
        </dl>
      )}

      <h2>Recent ingestion runs</h2>
      {d.runs.length === 0 ? (
        <Empty title="No ingestion has run yet">
          <p>
            Runs appear here after you fetch AMFI NAVs or backfill a scheme&apos;s history on <Link to="/mf">Mutual funds</Link>.
          </p>
        </Empty>
      ) : (
        <>
          <p className="small muted">The {d.runs.length} most recent runs (at most 50), newest first. Times are UTC.</p>
          <RunsTable runs={d.runs} />
        </>
      )}
    </section>
  );
}
