import type { Freshness } from "../lib/types";
import { dateLabel } from "../lib/format";

const META: Record<Freshness, { glyph: string; word: string; cls: string }> = {
  LIVE: { glyph: "●", word: "LIVE", cls: "live" },
  DELAYED: { glyph: "◐", word: "DELAYED", cls: "delayed" },
  END_OF_DAY: { glyph: "◑", word: "END-OF-DAY", cls: "eod" },
  STALE: { glyph: "○ ⚠", word: "STALE", cls: "stale" },
  FIXTURE: { glyph: "▨", word: "FIXTURE — not market data", cls: "fixture" },
  MANUAL: { glyph: "✎", word: "MANUAL ENTRY", cls: "eod" },
  UNKNOWN: { glyph: "?", word: "NO DATA", cls: "stale" },
};

/** Glyph + word + date: never colour alone (ux-design §4.4). */
export function FreshnessBadge({ freshness, date, title }: { freshness: Freshness; date?: string | null; title?: string }) {
  const m = META[freshness];
  return (
    <span className={`badge badge--${m.cls}`} title={title}>
      <span aria-hidden="true">{m.glyph}</span> {m.word}
      {date ? <span className="badge__date"> {dateLabel(date)}</span> : null}
    </span>
  );
}
