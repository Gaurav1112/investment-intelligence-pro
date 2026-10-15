import type { Freshness } from "../lib/types";
import { dateLabel } from "../lib/format";

const META: Record<Freshness, { glyph: string; word: string; cls: string }> = {
  LIVE: { glyph: "●", word: "LIVE", cls: "live" },
  DELAYED: { glyph: "◐", word: "DELAYED", cls: "delayed" },
  END_OF_DAY: { glyph: "◑", word: "END-OF-DAY", cls: "eod" },
  STALE: { glyph: "○ ⚠", word: "STALE", cls: "stale" },
  FIXTURE: { glyph: "▨", word: "FIXTURE — not market data", cls: "fixture" },
  MANUAL: { glyph: "✎", word: "MANUAL ENTRY", cls: "eod" },
  DERIVED: { glyph: "∑", word: "COMPUTED FROM YOUR RECORDS", cls: "neutral" },
  USER_INPUT: { glyph: "✎", word: "YOUR INPUT", cls: "neutral" },
  ILLUSTRATIVE: { glyph: "◇", word: "ILLUSTRATIVE", cls: "delayed" },
  UNAVAILABLE: { glyph: "—", word: "NOT AVAILABLE", cls: "stale" },
  UNKNOWN: { glyph: "?", word: "FRESHNESS UNKNOWN", cls: "stale" },
};

/** The badge word for a freshness, e.g. for an accessible name ("STALE", "FRESHNESS UNKNOWN"). */
export function freshnessWord(freshness: Freshness): string {
  return META[freshness].word;
}

/** Freshness values that are NOT a current market or user value: assistive tech must hear the word (WCAG 1.3.1). */
export const NOT_CURRENT: ReadonlySet<Freshness> = new Set<Freshness>([
  "STALE", "DELAYED", "FIXTURE", "ILLUSTRATIVE", "UNAVAILABLE", "UNKNOWN",
]);

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
