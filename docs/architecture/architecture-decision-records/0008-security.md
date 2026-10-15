# ADR-0008: Local security posture

## Decision
- Bind to 127.0.0.1. Any other bind is refused unless explicitly overridden.
- A **mandatory** 256-bit access token, exchanged for an HttpOnly, SameSite=Strict session cookie.
- An exact Host+port allowlist as the first middleware, which defeats DNS rebinding.
- CSRF protection: a custom header plus an Origin or Sec-Fetch-Site check plus a JSON content type on every state change. GET requests have no side effects.
- The SPA is served from the same origin, so there are no CORS headers. A strict CSP is applied.
- Fetchers use a code-defined host allowlist. User-supplied URLs are never fetched; private and loopback IPs and redirects off the allowlist are refused; byte caps and timeouts apply.
- Imports: 5 MiB cap, row/column/cell caps, macro files rejected, formulas never evaluated. On export, cells are neutralised against CSV formula injection.
- Logs contain no amounts, holdings or personal fields.
- Dependency audits: `pip-audit`, `pnpm audit`.

## Evidence
threat-model.md (SEC-01…SEC-81).
