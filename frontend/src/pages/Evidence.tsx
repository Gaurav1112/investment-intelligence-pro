import { useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { Loading } from "../components/States";
import { dateLabel, utcStamp } from "../lib/format";
import type { EvidenceBrief, EvidenceResponse } from "../lib/types";
import { useApi } from "../lib/useApi";
import { apiCode, apiMessage } from "./Watchlist";

function UrlText({ url }: { url: string }) {
  return (
    <>
      <span className="mono small break">{url}</span>
      {url.startsWith("https://") ? (
        <>
          {" "}
          <a href={url} target="_blank" rel="noreferrer noopener">
            Open source page
          </a>
        </>
      ) : null}
    </>
  );
}

function Stamp({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="subtle">not recorded</span>;
  try {
    return <>{utcStamp(iso)}</>;
  } catch {
    return <span className="mono">{iso}</span>;
  }
}

function Chain({ title, rows, empty }: { title: string; rows: EvidenceBrief[]; empty: string }) {
  return (
    <div>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p className="small subtle">{empty}</p>
      ) : (
        <div className="table-wrap">
          <table className="table table--compact">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col">Observation</th>
                <th scope="col">Stored value</th>
                <th scope="col">Observation date</th>
                <th scope="col">Retrieved (UTC)</th>
                <th scope="col">Quality</th>
                <th scope="col">SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.obs_id}>
                  <td>
                    <Link to={`/evidence/${r.obs_id}`}>#{r.obs_id}</Link>
                  </td>
                  <td className="mono">{r.value}</td>
                  <td>{dateLabel(r.observation_date)}</td>
                  <td>
                    <Stamp iso={r.retrieved_at} />
                  </td>
                  <td>{r.quality_status}</td>
                  <td className="mono small break">{r.sha256}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EvidenceDetail({ obsId }: { obsId: string }) {
  const ev = useApi<EvidenceResponse>(`/api/evidence/${encodeURIComponent(obsId)}`);
  if (ev.loading) return <Loading label="Loading evidence" />;
  if (ev.error || !ev.data)
    return (
      <div className="state state--error" role="alert">
        <p>
          {apiCode(ev.error) === "NOT_FOUND"
            ? `No observation #${obsId} is stored.`
            : `The evidence could not be loaded: ${apiMessage(ev.error)}`}
        </p>
        <p>
          <Link to="/evidence">Look up another observation</Link> · <Link to="/data-health">Data health</Link>
        </p>
      </div>
    );
  const d = ev.data;
  const o = d.observation;
  return (
    <div className={d.fixture ? "fixture-zone" : undefined}>
      {d.fixture ? (
        <p className="callout callout--warn" role="note">
          <FreshnessBadge freshness="FIXTURE" /> This observation is synthetic development data, not market data.
        </p>
      ) : null}
      <p className={d.is_current ? "callout" : "callout callout--stale"} role="note">
        {d.is_current ? (
          "This is the current stored value for its series."
        ) : (
          <>
            This value has been superseded
            {o.superseded_by !== null ? (
              <>
                {" "}
                by <Link to={`/evidence/${o.superseded_by}`}>observation #{o.superseded_by}</Link>
              </>
            ) : null}
            ; it is kept for the record and is not used for current figures.
          </>
        )}
      </p>
      <dl className="kv">
        <dt>Series</dt>
        <dd className="mono">{o.series_id}</dd>
        <dt>Kind</dt>
        <dd>{o.kind}</dd>
        <dt>Stored value</dt>
        <dd>
          <span className="mono">{o.value}</span> {o.unit}
          {o.currency ? ` (${o.currency})` : ""} <span className="small subtle">exactly as stored</span>
        </dd>
        <dt>Observation date</dt>
        <dd>{dateLabel(o.observation_date)} (India calendar date)</dd>
        <dt>Published</dt>
        <dd>
          <Stamp iso={o.publication_time} />
        </dd>
        <dt>Retrieved</dt>
        <dd>
          <Stamp iso={o.retrieved_at} />
        </dd>
        <dt>Source</dt>
        <dd>
          {o.source_id}
          {d.source ? (
            <span className="small">
              {" "}
              · {d.source.owner} · {d.source.official ? "official source" : "UNOFFICIAL source"} · mode {d.source.mode}
            </span>
          ) : (
            <span className="small subtle"> · source not in the registry</span>
          )}
        </dd>
        <dt>Source URL</dt>
        <dd>
          <UrlText url={o.url} />
        </dd>
        <dt>Raw file SHA-256</dt>
        <dd className="mono small break">{o.sha256}</dd>
        <dt>Quality</dt>
        <dd>{o.quality}</dd>
        <dt>Convention</dt>
        <dd>{o.convention ?? <span className="subtle">none recorded</span>}</dd>
        <dt>Ingestion run</dt>
        <dd>
          {d.ingestion_run ? (
            <>
              <span className="mono">{d.ingestion_run.run_id}</span> · {d.ingestion_run.status} · started{" "}
              <Stamp iso={d.ingestion_run.started_at} />
            </>
          ) : o.ingestion_run_id ? (
            <span className="mono">{o.ingestion_run_id}</span>
          ) : (
            <span className="subtle">none (manual or fixture entry)</span>
          )}
        </dd>
        {d.source ? (
          <>
            <dt>Licence</dt>
            <dd className="small">{d.source.licence_note}</dd>
          </>
        ) : null}
      </dl>
      <h2>Superseded chain</h2>
      <Chain title="Newer values that replaced this one" rows={d.superseded_chain.newer} empty="None — nothing has replaced this value." />
      <Chain title="Older values this one replaced" rows={d.superseded_chain.older} empty="None — this value replaced nothing." />
      <p className="small">
        <Link to="/data-health">Data health</Link> · <Link to="/methodology">Methodology</Link>
      </p>
    </div>
  );
}

function Lookup() {
  const nav = useNavigate();
  const [id, setId] = useState("");
  const [err, setErr] = useState<string | null>(null);
  function go(e: FormEvent) {
    e.preventDefault();
    const t = id.trim().replace(/^#/, "");
    if (!/^\d{1,12}$/.test(t)) {
      setErr("Enter an observation id: a whole number, e.g. 1234.");
      return;
    }
    setErr(null);
    nav(`/evidence/${t}`);
  }
  return (
    <form className="card" onSubmit={go} noValidate aria-labelledby="ev-lookup-title">
      <h2 id="ev-lookup-title">Look up an observation</h2>
      <div className="field">
        <label htmlFor="ev-id">Observation id</label>
        <div className="row-tight">
          <input id="ev-id" inputMode="numeric" value={id} onChange={(e) => setId(e.target.value)} aria-invalid={Boolean(err)}
            aria-describedby="ev-id-err" />
          <button type="submit" className="btn btn--primary">
            Show evidence
          </button>
        </div>
        {err ? (
          <div id="ev-id-err" className="field-error" role="alert">
            {err}
          </div>
        ) : null}
      </div>
    </form>
  );
}

export default function Evidence() {
  const { obsId } = useParams();
  if (obsId !== undefined) {
    const valid = /^\d{1,12}$/.test(obsId);
    return (
      <section>
        <PageHeader title={`Evidence · observation #${valid ? obsId : "?"}`} purpose="Where exactly this stored value came from." />
        {valid ? (
          <EvidenceDetail key={obsId} obsId={obsId} />
        ) : (
          <p className="callout callout--stale" role="alert">
            “{obsId}” is not an observation id. Ids are whole numbers. <Link to="/evidence">Look one up</Link>.
          </p>
        )}
      </section>
    );
  }
  return (
    <section>
      <PageHeader title="Evidence" purpose="Where exactly a stored value came from: source, retrieval time, checksum and quality status." />
      <p>
        Every market value this app uses — a NAV, a yield, a deposit rate — is stored as an <strong>observation</strong>: the value,
        the date it applies to, the source and its address, when it was retrieved (UTC), a SHA-256 checksum of the raw file it was
        read from, and a quality status. When a source corrects a value, the old observation is kept and linked to the new one,
        so the history can be followed in both directions.
      </p>
      <p>
        Open evidence from the links next to values (for example “NAV evidence” on the Overview, or “Evidence for latest value” on
        the Watchlist), or look up an id below. To see whether today&apos;s data can be trusted overall, use{" "}
        <Link to="/data-health">Data health</Link>.
      </p>
      <Lookup />
    </section>
  );
}
