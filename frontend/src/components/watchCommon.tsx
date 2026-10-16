// Request-error wording, freshness mapping and the instrument search box, shared by Watchlist, Overview, Alerts,
// Settings and others. Kept outside pages/ so no page module imports another page (audit-perf-frontend F4).
import { useRef, useState, type KeyboardEvent } from "react";
import { FreshnessBadge } from "./FreshnessBadge";
import { errorText } from "./fiCommon";
import { api, ApiError } from "../lib/api";
import type { Freshness, InstrumentList, InstrumentListItem } from "../lib/types";

const FRESHNESS: readonly Freshness[] = ["LIVE", "DELAYED", "END_OF_DAY", "STALE", "FIXTURE", "MANUAL", "UNKNOWN"];

/** Any backend badge string → a badge the FreshnessBadge component knows; unknown labels become UNKNOWN, never hidden. */
export function safeFreshness(x: string | null | undefined): Freshness {
  return (FRESHNESS as readonly string[]).includes(x ?? "") ? (x as Freshness) : "UNKNOWN";
}

/** Message for a refused request: the backend's `{code, message}` body is shown in words, else the generic text. */
export function apiMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.detail as { message?: unknown } | null | undefined;
    if (body && typeof body.message === "string") return `${body.message} (${e.code})`;
  }
  return errorText(e);
}

export function apiCode(e: unknown): string | null {
  return e instanceof ApiError ? e.code : null;
}

/** Search the local instrument store by name (GET /api/instruments?q=) and pick one. No nested <form>: usable inside forms. */
export function InstrumentSearch({
  idPrefix,
  selected,
  onSelect,
}: {
  idPrefix: string;
  selected: InstrumentListItem | null;
  onSelect: (item: InstrumentListItem | null) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<InstrumentList | null>(null);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function search() {
    const term = q.trim();
    if (term.length < 2) {
      setErr("Type at least 2 characters of the instrument name.");
      return;
    }
    setPending(true);
    setErr(null);
    try {
      setResults(await api<InstrumentList>(`/api/instruments?q=${encodeURIComponent(term)}`));
    } catch (e) {
      setResults(null);
      setErr(errorText(e));
    } finally {
      setPending(false);
    }
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void search();
    }
  };

  if (selected)
    return (
      <div className="field">
        <span className="label-like">Instrument</span>
        <div className="row-tight" role="status">
          <span>
            Selected: <strong>{selected.name}</strong> <span className="mono small">{selected.instrument_id}</span>
          </span>
          {selected.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              onSelect(null);
              setTimeout(() => input.current?.focus(), 0);
            }}
          >
            Change instrument
          </button>
        </div>
      </div>
    );

  const items = results?.items.slice(0, 25) ?? [];
  return (
    <div className="field">
      <label htmlFor={`${idPrefix}-q`}>Find instrument by name</label>
      <div className="row-tight">
        <input id={`${idPrefix}-q`} ref={input} className="input-wide" value={q} maxLength={80} onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey} aria-describedby={`${idPrefix}-q-hint`} />
        <button type="button" className="btn" onClick={() => void search()} disabled={pending}>
          {pending ? "Searching…" : "Search"}
        </button>
      </div>
      <div id={`${idPrefix}-q-hint`} className="hint">Searches instruments already in the local store (funds, T-bills and deposits you entered).</div>
      {err ? (
        <div className="field-error" role="alert">
          {err}
        </div>
      ) : null}
      {results ? (
        <div role="status" className="small">
          {results.items.length === 0
            ? "No stored instrument matches that name."
            : `${results.items.length}${results.truncated ? "+" : ""} match(es)${results.items.length > items.length ? `; first ${items.length} shown — refine the name` : ""}.`}
        </div>
      ) : null}
      {items.length ? (
        <ul className="plain-list search-results" aria-label="Matching instruments">
          {items.map((it) => (
            <li key={it.instrument_id} className="row-tight">
              <button type="button" className="btn" onClick={() => onSelect(it)} aria-label={`Select ${it.name}`}>
                Select
              </button>
              <span>{it.name}</span>
              <span className="small subtle mono">{it.instrument_id}</span>
              {it.fixture ? <FreshnessBadge freshness="FIXTURE" /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
