// Required disclosure strings — verbatim copies of backend/src/iip/rules/compliance_phrases.yaml `required:`.
// A test asserts they match the backend file exactly, so the two can never drift.
export const REQUIRED = {
  past_performance: "Past performance may or may not be sustained in future and is not a guarantee of future returns.",
  ranking: "Ordered by the criteria and weights you set.",
  projection: "Hypothetical illustration based on your assumptions; not a forecast.",
  footer: "Personal research tool. Not investment advice. Not registered with SEBI as an Investment Adviser or Research Analyst.",
  ai_disclosure: "AI-generated wording. Every number comes from the deterministic engine or a dated source.",
} as const;

export function Disclosure({ kind }: { kind: keyof typeof REQUIRED }) {
  return <p className="small subtle disclosure">{REQUIRED[kind]}</p>;
}
