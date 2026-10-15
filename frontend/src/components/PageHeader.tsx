import type { ReactNode } from "react";

/**
 * Consistent page anatomy: title, one-line purpose, an optional data-as-of / provenance line and an optional action area.
 * Results follow the header; the provenance / disclaimer footer goes in <PageFooter>.
 */
export function PageHeader({
  title,
  purpose,
  meta,
  actions,
}: {
  title: ReactNode;
  purpose?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head__text">
        <h1>{title}</h1>
        {purpose ? <p className="page-head__purpose">{purpose}</p> : null}
        {meta ? <div className="page-head__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-head__actions">{actions}</div> : null}
    </header>
  );
}

/** Provenance and disclaimers at the foot of a page (always visible, never collapsed). */
export function PageFooter({ children }: { children: ReactNode }) {
  return <footer className="page-foot small subtle">{children}</footer>;
}
