import type { Explained } from "../lib/types";
import type { NeedView } from "../lib/types-actions";
import { asExplained, BASIS_LABEL, humanise } from "./ActionCard";
import { ExplainedNumber } from "./ExplainDrawer";

/** "Needs from you" (design-judgement.md graft 7; engine/actions/needs.py). The server ranks needs by the largest single
 * ₹ bound each input unlocks; this list keeps that order and never adds bounds (not across bases, not across cards). */
export function NeedsList({ needs, onExplain }: { needs: readonly NeedView[]; onExplain: (e: Explained) => void }) {
  if (needs.length === 0) return <p className="subtle">Nothing is needed from you today.</p>;
  return (
    <ol className="needs" aria-label="Needs from you">
      {needs.map((n) => {
        const top = n.unlocks[0];
        return (
          <li key={n.missing_input}>
            <strong>{humanise(n.missing_input)}</strong>
            <span className="small subtle mono"> ({n.codes.join(", ")})</span>
            <ul className="small">
              {n.how_to_fix.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
            {top ? (
              <p className="small">
                Unlocks up to <ExplainedNumber item={asExplained(top.number)} onExplain={onExplain} /> ({BASIS_LABEL[top.basis]})
                {n.unlocks.length > 1 ? (
                  <span className="subtle"> — the largest of {n.unlocks.length} bounds; bounds are never added.</span>
                ) : null}
              </p>
            ) : (
              <p className="small subtle">The engine cannot bound the ₹ this unlocks, so it is listed last.</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
