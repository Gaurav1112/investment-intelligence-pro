import { useEffect, useRef } from "react";
import type { Explained } from "../lib/types";
import { utcStamp, dateLabel } from "../lib/format";
import { FreshnessBadge } from "./FreshnessBadge";

/** "Explain this number" — native <dialog> (ADR-0006 amendment). Sections in the order mandated by ux-design §5.1. */
export function ExplainDrawer({ item, onClose }: { item: Explained | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (item && !d.open) {
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
      heading.current?.focus();
    }
    if (!item && d.open) d.close();
  }, [item]);

  return (
    <dialog ref={ref} className="drawer" aria-labelledby="explain-title" onClose={onClose} onCancel={onClose}>
      {item ? (
        <article>
          <header className="drawer__head">
            <h2 id="explain-title" ref={heading} tabIndex={-1}>
              Explain: {item.label} — <span className="num">{item.display}</span>
            </h2>
            <button type="button" className="btn btn--ghost" onClick={onClose} aria-label="Close explanation">
              ×
            </button>
          </header>
          <dl className="explain">
            <dt>What it is</dt>
            <dd>{item.what}</dd>
            <dt>Inputs</dt>
            <dd>
              <ul>{item.inputs.map((x) => <li key={x}>{x}</li>)}</ul>
            </dd>
            <dt>Formula</dt>
            <dd>
              <code>{item.formula}</code>
              {item.substituted ? <div className="mono small">computed: {item.substituted}</div> : null}
              <div className="small subtle">Formula id {item.formula_id}</div>
            </dd>
            <dt>Sources</dt>
            <dd>
              {item.sources.length === 0 ? (
                <span className="subtle">Computed only from your inputs and versioned rules.</span>
              ) : (
                <ul>
                  {item.sources.map((s) => (
                    <li key={`${s.source_id}-${s.observation_date}`}>
                      {s.source_name} {s.official ? "" : "(UNOFFICIAL)"} ·{" "}
                      {s.retrieved_at ? `retrieved ${utcStamp(s.retrieved_at)}` : "retrieval time not recorded"} ·{" "}
                      status {s.quality_status}
                      <div className="small subtle mono">{s.url}</div>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
            <dt>Observed</dt>
            <dd>
              {item.observed ? dateLabel(item.observed) : "—"} <FreshnessBadge freshness={item.freshness} />
            </dd>
            <dt>Assumptions</dt>
            <dd>
              <ul>{item.assumptions.map((x) => <li key={x}>{x}</li>)}</ul>
            </dd>
            <dt>Sensitivity</dt>
            <dd>
              {item.sensitivity.length === 0 ? (
                <span className="subtle">Not applicable (contractual or user-supplied value).</span>
              ) : (
                <ul>
                  {item.sensitivity.map((s) => (
                    <li key={s.label}>
                      {s.label}: <span className="num">{s.display}</span>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
            <dt>Limitations</dt>
            <dd>
              <ul>{item.limitations.map((x) => <li key={x}>{x}</li>)}</ul>
            </dd>
          </dl>
          <footer className="small subtle mono">
            {item.engine_version} · {item.id} · hash {item.hash.slice(0, 12)}…
          </footer>
        </article>
      ) : null}
    </dialog>
  );
}

/** A number that opens its explanation. Rendering a number without an Explained object is not possible here. */
export function ExplainedNumber({ item, onExplain }: { item: Explained; onExplain: (e: Explained) => void }) {
  return (
    <button
      type="button"
      className={`num explainable${item.freshness === "STALE" ? " is-stale" : ""}`}
      onClick={() => onExplain(item)}
      onKeyDown={(e) => {
        if (e.key === "e" || e.key === "E") onExplain(item);
      }}
      aria-label={`${item.label}: ${item.display}. Press to explain.`}
    >
      {item.display}
      <span className="explainable__i" aria-hidden="true">
        ⓘ
      </span>
    </button>
  );
}
