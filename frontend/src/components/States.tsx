import type { ReactNode } from "react";
import { ApiError } from "../lib/api";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state state--loading" aria-busy="true" role="status">
      <span className="skeleton" /> <span className="skeleton skeleton--short" />
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg =
    error instanceof ApiError
      ? error.status === 401
        ? "Your session has expired. Re-open the app with `make open` to sign in again."
        : `The request failed (${error.code}). No result is shown rather than a possibly wrong one.`
      : "Something went wrong. No result is shown rather than a possibly wrong one.";
  return (
    <div className="state state--error" role="alert">
      <p>{msg}</p>
      {retry ? (
        <button type="button" className="btn" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state--empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}
