const TIER_TEXT: Record<string, string> = {
  T1: "Contractual · sovereign",
  T2: "Contractual · fully insured",
  T3: "Bounded uncertainty",
  T4: "Unbounded market risk",
};
const FILL: Record<string, number> = { T1: 1, T2: 2, T3: 3, T4: 4 };

/** Certainty tier as a one-hue 5-step bar + words (never a traffic light; ux-design §4.5). */
export function TierLabel({ tier }: { tier: string }) {
  const n = FILL[tier] ?? 5;
  return (
    <span className="tier" title="More fill = more uncertainty about the outcome">
      <span className="riskbar" aria-hidden="true">
        {"▮".repeat(n)}
        {"▯".repeat(5 - n)}
      </span>{" "}
      <span className="small">
        {tier} · {TIER_TEXT[tier] ?? "Unknown"}
      </span>
    </span>
  );
}
