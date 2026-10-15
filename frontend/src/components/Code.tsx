import type { ReactNode } from "react";
import { codeLabel, humanise, splitCode } from "../lib/codes";

/**
 * An engine reason such as "EXIT_LOAD_UNKNOWN: enter the scheme's exit load…" shown as plain English, with the original
 * text kept verbatim in a muted mono suffix for traceability.
 */
export function CodeText({ raw }: { raw: string }) {
  const { code } = splitCode(raw);
  if (!code) return <span>{raw}</span>;
  const label = codeLabel(code) ?? humanise(code);
  return (
    <span>
      {label} <span className="code-suffix">{raw}</span>
    </span>
  );
}

/** Label for a bare code (for grouping/counts), with the code as a muted suffix. */
export function CodeLabel({ code }: { code: string }) {
  return (
    <span>
      {codeLabel(code) ?? humanise(code)} <span className="code-suffix">{code}</span>
    </span>
  );
}

/** Instrument name cell: up to two lines with the full name as a tooltip, then the identifier on a muted mono line. */
export function InstName({ name, code, children }: { name: string; code?: string | null; children?: ReactNode }) {
  return (
    <>
      <span className="inst-name" title={name}>
        {children ?? name}
      </span>
      {code ? <span className="inst-code">{code}</span> : null}
    </>
  );
}
