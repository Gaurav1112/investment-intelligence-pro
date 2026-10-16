import { useRef, useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { Link } from "react-router-dom";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { Empty, ErrorState, Loading } from "../components/States";
import { api } from "../lib/api";
import { dateLabel, pct, utcStamp } from "../lib/format";
import type { InstrumentListItem, WatchItem, WatchlistResponse } from "../lib/types";
import { useApi } from "../lib/useApi";
import { navLabel, ratePct } from "../components/fiCommon";
import { apiCode, apiMessage, InstrumentSearch, safeFreshness } from "../components/watchCommon";

// ------------------------------------------------------------------ shared helpers
// Moved to components/watchCommon.tsx (A06). Re-exported for the importers that have not switched yet.
export { apiCode, apiMessage, InstrumentSearch, safeFreshness } from "../components/watchCommon";

// ------------------------------------------------------------------ change since added

const REASON_TEXT: Record<string, string> = {
  STALE_NAV: "the latest NAV is STALE, so no change is shown (older NAVs are never used)",
  NO_NAV_STORED: "no NAV is stored for this scheme yet",
  STALE_DATA: "the latest stored value is STALE, so no change is shown",
  NO_OBSERVATION_ON_OR_BEFORE_DATE_ADDED: "no stored value on or before the day you added it, so there is no starting point",
  NO_AMFI_CODE: "this fund has no AMFI code, so it cannot be valued",
};

export function reasonText(reason: string): string {
  if (reason.startsWith("NO_SERIES")) return "no stored price series exists for this instrument type";
  if (reason.startsWith("LATEST_NAV_QUALITY_"))
    return `the latest NAV is marked ${reason.slice("LATEST_NAV_QUALITY_".length).toLowerCase()}, so no change is shown`;
  return REASON_TEXT[reason] ?? reason;
}

function signed(value: string, body: string): { arrow: string; cls: string; text: string } {
  const neg = value.trim().startsWith("-");
  const zero = /^-?0*(\.0*)?$/.test(value.trim());
  if (zero) return { arrow: "■", cls: "", text: body };
  return neg ? { arrow: "▼", cls: "down", text: `−${body}` } : { arrow: "▲", cls: "up", text: `+${body}` };
}

function ChangeCell({ item }: { item: WatchItem }) {
  const c = item.change;
  if (!c) return <span className="small subtle">Not shown: {reasonText(item.reason ?? "unknown reason")}.</span>;
  const isNav = (item.series_id ?? "").startsWith("nav:");
  const fmt = (v: string) => (isNav ? navLabel(v) : ratePct(v));
  const abs = c.value.replace("-", "");
  const delta = signed(c.value, isNav ? navLabel(abs) : pct(abs, 2, false).replace("%", "percentage points"));
  return (
    <div>
      <div>
        {fmt(c.from.value)} on {dateLabel(c.from.date)} → {fmt(c.to.value)} on {dateLabel(c.to.date)}
      </div>
      <div className={delta.cls}>
        <span aria-hidden="true">{delta.arrow}</span> {delta.text}
        {item.absolute_return ? (
          <>
            {" "}
            ({item.absolute_return.display} absolute, not annualised)
          </>
        ) : null}
      </div>
      {isNav ? null : <div className="small subtle">yield change, not a price change</div>}
    </div>
  );
}

// ------------------------------------------------------------------ rows and form

function RemoveButton({ item, onRemoved }: { item: WatchItem; onRemoved: (msg: string) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setPending(true);
    setErr(null);
    try {
      await api(`/api/watchlist/${encodeURIComponent(item.instrument_id)}`, { method: "DELETE" });
      onRemoved(`Removed ${item.name} from the watchlist.`);
    } catch (e) {
      setErr(apiMessage(e));
      setPending(false);
    }
  }
  return (
    <span className="row-tight">
      {confirming ? (
        <>
          <button type="button" className="btn btn--danger" onClick={go} disabled={pending} aria-label={`Confirm remove ${item.name}`}>
            {pending ? "Removing…" : "Confirm remove"}
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => setConfirming(false)} disabled={pending}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" className="btn" onClick={() => setConfirming(true)} aria-label={`Remove ${item.name}`}>
          Remove
        </button>
      )}
      {err ? (
        <span className="field-error" role="alert">
          {err}
        </span>
      ) : null}
    </span>
  );
}

function AddForm({ onAdded }: { onAdded: (msg: string) => void }) {
  const [selected, setSelected] = useState<InstrumentListItem | null>(null);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!selected) {
      setErr("Search for and select an instrument first.");
      return;
    }
    setPending(true);
    setErr(null);
    try {
      await api("/api/watchlist", { method: "POST", body: { instrument_id: selected.instrument_id, note: note.trim() } });
      onAdded(`Added ${selected.name} to the watchlist.`);
      setSelected(null);
      setNote("");
    } catch (ex) {
      setErr(apiCode(ex) === "ALREADY_WATCHED" ? `${selected.name} is already on your watchlist.` : `Not added: ${apiMessage(ex)}`);
    } finally {
      setPending(false);
    }
  }
  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="watch-add-title">
      <h2 id="watch-add-title">Add to watchlist</h2>
      <InstrumentSearch idPrefix="watch" selected={selected} onSelect={setSelected} />
      <div className="field">
        <label htmlFor="watch-note">Note (optional)</label>
        <textarea id="watch-note" className="input-wide" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)}
          aria-describedby="watch-note-hint" />
        <div id="watch-note-hint" className="hint">
          Up to 500 characters. Notes are saved with the entry; to change a note, remove the entry and add it again.
        </div>
      </div>
      {err ? (
        <p className="callout callout--stale" role="alert">
          {err}
        </p>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={pending}>
        {pending ? "Adding…" : "Add to watchlist"}
      </button>
    </form>
  );
}

export default function Watchlist() {
  const list = useApi<WatchlistResponse>("/api/watchlist");
  const [notice, setNotice] = useState<string | null>(null);
  const status = useRef<HTMLParagraphElement>(null);
  const done = (msg: string) => {
    setNotice(msg);
    list.reload();
    setTimeout(() => status.current?.focus(), 0);
  };
  const items = list.data?.items ?? [];
  return (
    <section>
      <PageHeader
        title="Watchlist"
        purpose={
          <>
            Instruments you are tracking. The change shown is the absolute change between the stored value on or before the day you added it and the latest stored value — never annualised, and never filled in from older data when the latest is STALE.
          </>
        }
      />
      <p ref={status} tabIndex={-1} role="status" className={notice ? "callout" : "sr-only"}>
        {notice ?? ""}
      </p>
      {list.loading ? (
        <Loading label="Loading your watchlist" />
      ) : list.error ? (
        <ErrorState error={list.error} retry={list.reload} />
      ) : items.length === 0 ? (
        <Empty title="Your watchlist is empty">
          <p>Search for a fund, T-bill or deposit below and add it. Its change since the day you add it will appear here.</p>
        </Empty>
      ) : (
        <>
          {list.data ? <p className="small subtle">As of {utcStamp(list.data.as_of)}</p> : null}
          {items.some((i) => i.badge === "FIXTURE") ? (
            <p className="callout callout--warn fixture-zone" role="note">
              <strong>FIXTURE data present.</strong> Rows marked FIXTURE use synthetic development data, not market data.
            </p>
          ) : null}
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Watched instruments</caption>
              <thead>
                <tr>
                  <th scope="col">Instrument</th>
                  <th scope="col">Data</th>
                  <th scope="col">Added</th>
                  <th scope="col">Change since added</th>
                  <th scope="col">Note</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.instrument_id} className={it.badge === "FIXTURE" ? "fixture-zone" : it.badge === "STALE" ? "is-excluded" : undefined}>
                    <td>
                      <Link to={`/i/${encodeURIComponent(it.instrument_id)}`}>{it.name}</Link>
                      <div className="small subtle">{it.kind}</div>
                    </td>
                    <td>
                      <FreshnessBadge freshness={safeFreshness(it.badge)} date={it.latest?.observation_date ?? null} />
                      {it.latest ? (
                        <div className="small">
                          <Link to={`/evidence/${it.latest.obs_id}`}>Evidence for latest value</Link>
                        </div>
                      ) : null}
                    </td>
                    <td>{utcStamp(it.added_at)}</td>
                    <td>
                      <ChangeCell item={it} />
                    </td>
                    <td className="note-cell">{it.note ?? <span className="subtle">—</span>}</td>
                    <td>
                      <RemoveButton item={it} onRemoved={done} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <AddForm onAdded={done} />
    </section>
  );
}
