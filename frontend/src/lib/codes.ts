// Plain-English labels for engine codes. The code itself is still shown (muted, mono) next to the label so that every
// message stays traceable to the engine; nothing here changes what a code means.

const LABELS: Record<string, string> = {
  // ranking eligibility (backend engine/ranking.py)
  EXCLUDED_BY_USER: "Excluded by you",
  HORIZON_MISMATCH: "Does not fit your withdrawal date",
  INSUFFICIENT_OR_STALE_DATA: "Data missing or out of date",
  LIQUIDITY_TOO_SLOW: "Too slow to turn into cash",
  EXIT_COST_TOO_HIGH: "Exit cost above your limit",
  BELOW_MINIMUM_TICKET: "Amount below the minimum investment",
  BELOW_CREDIT_FLOOR: "Credit rating below your floor",
  CREDIT_QUALITY_UNKNOWN: "Portfolio credit quality unknown (enter its factsheet)",
  UNINSURED_CREDIT_EXPOSURE: "Part of the amount is not deposit-insured",
  INSUFFICIENT_LOSS_EVIDENCE: "Too little history to show a low loss rate",
  MISSING_LOSS_EVIDENCE: "No reliable loss history",
  LOSS_FREQUENCY_ABOVE_LIMIT: "Lost money too often in the past",
  LOWER_BAND_BELOW_FLOOR: "Low-end outcome below the amount invested",
  LOWER_BAND_BELOW_LOSS_BUDGET: "Low-end outcome beyond your loss budget",
  // candidate building (engine/candidates.py)
  EXIT_LOAD_UNKNOWN: "Exit load not entered yet",
  INSUFFICIENT_HISTORY: "Not enough price history",
  NO_NAV_STORED: "No NAV stored",
  NO_AMFI_CODE: "No AMFI code",
  STALE_NAV: "Latest NAV is out of date",
  // flags and refusals
  FIXTURE_NOT_MARKET_DATA: "FIXTURE — not market data",
  TAX_RULE_UNVERIFIED: "Tax rule not yet verified",
  TAX_CLASS_INFERRED_FROM_CATEGORY: "Tax class inferred from category",
  LOW_EVIDENCE: "Low evidence",
  EXCEEDS_DICGC_LIMIT_AT_THIS_BANK: "Partly outside DICGC cover",
  NOT_DICGC_INSURED: "Not DICGC insured",
  PREMATURE_PENALTY_UNKNOWN: "Early-exit penalty unknown",
  ANNUALISED_FROM_SHORT_PERIOD: "Annualised from a short period",
  CONSTRAINT_CONFLICT: "Your settings pull in different directions",
};

/** Split "CODE: detail" (or a bare CODE) into its parts. Returns code null for free text. */
export function splitCode(raw: string): { code: string | null; detail: string } {
  const m = /^([A-Z][A-Z0-9_]{2,})(?::\s*(.*))?$/s.exec(raw.trim());
  if (!m) return { code: null, detail: raw };
  return { code: m[1] ?? null, detail: m[2] ?? "" };
}

/** Friendly label for a code (prefix match for families such as TAX_RULES_ASSUMED_UNCHANGED_*), else null. */
export function codeLabel(code: string): string | null {
  if (LABELS[code]) return LABELS[code];
  if (code.startsWith("TAX_RULES_ASSUMED_UNCHANGED")) return "Tax rules assumed beyond the legislated year";
  if (code.startsWith("STALE")) return "Data out of date";
  return null;
}

/** Fallback when no label is known: "SOME_CODE" → "Some code". */
export function humanise(code: string): string {
  const s = code.toLowerCase().replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
