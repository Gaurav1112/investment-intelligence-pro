/** Plain-English names for instrument kinds (never show the internal code, e.g. `mf_scheme`, to the user). */
export const KIND_LABEL: Record<string, string> = {
  mf_scheme: "Mutual fund scheme",
  tbill: "Treasury bill",
  gsec: "Government security",
  sdl: "State development loan",
  corp_bond: "Corporate bond",
  fd: "Fixed deposit",
  small_savings: "Small savings scheme",
  cash: "Cash",
};

export const kindLabel = (kind: string): string => KIND_LABEL[kind] ?? kind;
