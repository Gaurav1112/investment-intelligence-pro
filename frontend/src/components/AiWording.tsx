import { useState } from "react";
import type { LlmReportFields } from "../lib/types-llm";
import "../styles/llm.css";

/** Required AI-use disclosure (regulatory-readiness G8). The backend appends it to the report disclosures. */
export const AI_DISCLOSURE_PREFIX = "AI-generated wording";

/**
 * Shown when the report's narrative was reworded by the optional LLM (`writer === "llm"`): an "AI-generated wording"
 * label, the AI disclosure returned by the backend, and a toggle to see the deterministic template text instead.
 * For template reports it renders `children` (the normal deterministic sections) unchanged.
 */
export function AiWording({ report, children }: { report: LlmReportFields; children: React.ReactNode }) {
  const [showTemplate, setShowTemplate] = useState(false);
  if (report.writer !== "llm") return <>{children}</>;
  const disclosure = report.disclosures.find((d) => d.startsWith(AI_DISCLOSURE_PREFIX));
  return (
    <div className="ai-narrative">
      <p className="small">
        <span className="ai-label">AI-generated wording</span>
      </p>
      {disclosure ? <p className="ai-disclosure">{disclosure}</p> : null}
      <button type="button" className="btn ai-toggle" aria-pressed={showTemplate} onClick={() => setShowTemplate((v) => !v)}>
        {showTemplate ? "Show AI wording" : "Show deterministic wording"}
      </button>
      {showTemplate ? (
        <div data-testid="template-text">{children}</div>
      ) : (
        <div data-testid="ai-text">
          {report.narrative.split("\n").map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
      )}
    </div>
  );
}
