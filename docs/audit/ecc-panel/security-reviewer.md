# ECC panel — security-reviewer report

Date: 2026-10-15 · Scope: `backend/src/iip`, `frontend/src`, `Makefile` (`.claude/agents` excluded) · Mode: read-only review.
Context read: threat-model.md, known-limitations.md, final-red-team-report.md. Already-known limitations are not repeated.

## Summary

The core web-security posture is strong: loopback bind with startup refusal, exact Host allowlist (DNS rebinding),
session cookie HttpOnly + SameSite=Strict, CSRF = Origin/Sec-Fetch-Site + content-type + per-session token with
constant-time compare, no CORS, a strict CSP (`script-src 'self'`, no inline), streamed body cap, an SSRF-hardened
fetcher (allowlist, public-IP check, connection pinned to the vetted address, redirects re-checked, bounded
decompression), parameterised SQL everywhere (the f-string sites only interpolate `?` placeholders or
identifier-asserted constants), CSV formula neutralisation, an XLSX container inspection, in-memory CAS parsing with
PII dropped at the parser boundary, AES-256-GCM + scrypt encrypted backups with the header used as AAD, and a
loopback-only/allowlisted LLM path with output validation. Front-end external links accept only `https://` and use
`rel="noreferrer noopener"`; there is no `innerHTML`/`dangerouslySetInnerHTML`.

No critical or high findings. One medium (privacy erase is incomplete) and six low findings follow.

## Findings

### SR-01 (MEDIUM) "Erase all my data" leaves encrypted backups and plaintext restored databases behind and reports 0 remaining
- `backend/src/iip/services/portfolio.py:1291-1295` `_backup_files` globs only `iip-*.sqlite3` and `iip-*.db`.
- `make backup-encrypted` writes `backups/iip-<UTC>.db.enc` (`encrypted_backup.py` `main`), which the pattern
  `iip-*.db` does not match (verified: for `iip-X.db.enc`, `iip-X.db`, `iip-x-v2.sqlite3`, `restored-X.db` the
  function returns only the `.db` and `.sqlite3` files).
- `make restore-encrypted` writes a **plaintext** full copy to `<data-dir>/restored-<UTC>.db`
  (`encrypted_backup.py:223`); it is outside `backups/`, so neither `inventory()` nor `erase()` sees it.
- `make restore-drill` (`Makefile:73`) restores into `tempfile.mkdtemp()/r.db` and never deletes it — another
  plaintext full copy outside the data dir.
- Impact: after `POST /api/privacy/erase {delete_backups: true}` the UI shows `backups_remaining: 0` while complete
  copies of holdings, transactions and the tax profile remain on disk (one of them unencrypted). This breaks the
  SEC-81 / C-12 erase promise the user relies on before handing over or disposing of the machine.
- Fix: include `iip-*.db.enc` (and stray `*.partial`) in `_backup_files`; list and erase `restored-*.db` in the data
  dir (or write restores into `backups/` with the same prefix); have `restore-drill` delete its temp directory.
  Add a test that creates each artefact and asserts erase removes it and inventory counts it.

### SR-02 (LOW) Local-LLM "loopback only" check is a time-of-check/time-of-use race for hostnames
- `backend/src/iip/llm/adapter.py:183-194` calls `check_loopback()` (its own `getaddrinfo`) and then lets httpx resolve
  the hostname again to connect; the same pattern is in `probe()` (`adapter.py:248`). The comment claims "a name
  that later resolves off-box is refused (SEC-75)", but the address actually connected to is never checked.
- `iip/data/fetch.py` solves exactly this with `PinnedNetworkBackend`; the LLM path does not.
- Impact: only when the user configures a hostname (not the default `127.0.0.1`), e.g. an mDNS `*.local` name;
  a LAN responder can answer the second lookup and receive the prompt (personal values if
  `IIP_LLM_LOCAL_PERSONAL=1`) plus the `Authorization: Bearer` value of `api_key_env`.
- Fix: in local mode accept only IP literals / `localhost`, or connect to the vetted address (reuse the pinned
  transport from `fetch.py`).

### SR-03 (LOW) Session cookie is shared with every other 127.0.0.1 port, and `/api/me` turns the cookie alone into full API access
- Cookies are not port-isolated: `iip_session` (`app.py:134`, `path="/"`, host `127.0.0.1`) is also sent by the
  browser to any other service on `127.0.0.1:<any port>` for same-site requests. SameSite=Strict does not help
  (ports do not change the site).
- `GET /api/me` (`app.py:148-150`) returns the CSRF token to any holder of the cookie. A non-browser client can set
  `Origin: http://127.0.0.1:8741` / `Sec-Fetch-Site: same-origin` itself, so a captured cookie gives read **and**
  write access (erase, imports, LLM config).
- Impact: requires another local listener (e.g. a process of another OS user, which threat-model T-40 treats as a
  threat) and a same-site visit by the user; hence low.
- Fix: keep the CSRF token in `sessionStorage` (origin- and port-scoped) instead of re-serving it from `/api/me`
  (re-login on lost token), and/or bind the session to a value not derivable from the cookie alone.

### SR-04 (LOW) Upstream throttle (SEC-86) is bypassable: backfill bursts up to 80 unpaced AMFI requests per call; CAS preview re-downloads NAVAll every time
- `api/routes_core.py:183` calls `ingestion.discover_fund_house_id(...)` with no `pause`
  (`services/ingestion.py:302-310`: `pause=None` → no delay) for up to 80 ids, and the route has no rate limit; the
  probe result is cached only on success.
- `api/routes_cas.py:120-124` calls `register_schemes_by_isin` → full NAVAll fetch on every preview with an unknown
  ISIN, outside the 15-minute gate applied to `/api/ingestion/amfi-navall` (`routes_core.py:160-167`).
- Impact: repeated clicks or retries can hammer AMFI, risking an IP block (the app's only live price source becomes
  stale) and breaching the source's terms that SEC-86 exists to respect.
- Fix: pass `pause=time.sleep` (≥ 1 s) in the route; apply the per-source 15-minute gate (shared state) to every
  NAVAll fetch and add a per-scheme backfill limit.

### SR-05 (LOW) Threat-model controls C-13 (security-event logging) and C-16 (per-route rate limits) are documented but not implemented
- `api/security.py:153,175,178,185` reject bad Host, unauthenticated and CSRF-failing requests without any log line;
  C-13 requires each of these to be logged at WARNING and counted on the status page. There is no logging
  configuration/redaction processor in `src/iip` at all (C-13 "field allowlist" / "redaction processor").
- `api/app.py:47` is the only `RateLimiter`; C-16 also specifies import 10/min, LLM 6/min and 300/min overall.
- Neither gap is listed in known-limitations.md, so the docs overstate the controls; a rebinding/CSRF probe or a
  runaway client leaves no trace.
- Fix: log `security_event code=… route=…` in `_reject` for 400/401/403 (no header values), add the limiters, or
  record both as known limitations.

### SR-06 (LOW) `make backup` writes a plaintext database copy with default (umask) permissions
- `Makefile:64` → `store/db.py` `backup()` creates the file through `sqlite3.connect` with default mode (0644 under
  a 022 umask) and never `chmod`s it; the API path (`portfolio.make_backup`) does chmod 0600 + 0700 dir.
- SEC-82 states "DB, secrets and backups 0600". Currently mitigated by the 0700 data directory, but the protection
  disappears as soon as the backups folder is copied or mirrored (`IIP_BACKUP_MIRROR_DIR` in reliability-design).
- Fix: `os.chmod(dest, 0o600)` (and the `.partial`) inside `db.backup`, and `chmod 0700` the backups dir.

### SR-07 (LOW) `make open` puts the long-lived access token on a process command line
- `Makefile:34`: `open "http://127.0.0.1:$(IIP_PORT)/#login=$$(cat …/access-token)"` passes the token as an argv of
  `open`, readable by any local user via `ps` while it runs. The token never expires (only `make token-rotate`).
- Impact: small window, but the token is the single credential for all financial data and is otherwise protected
  by 0600/0700 file modes precisely against other local users.
- Fix: open a token-less URL and have the user paste the token, or serve a one-time, short-lived login nonce
  (exchanged server-side for the session) instead of the permanent token.

## Checked and found sound (no finding)
Host allowlist and SPA path-traversal guard (`dist in candidate.parents` after `resolve()`, absolute-path tricks
included); public routes limited to `POST /api/session` and `GET /api/health`; OPTIONS refused; docs/openapi off in
prod and behind auth in dev; generic 500 handler without detail; startup refusal of non-loopback binds, auth-off and
dev origins outside their envs; fetcher SSRF controls; LLM cloud allowlist exact match (scheme/host/port/path, no
userinfo/query); LLM output validation (markup, links, tool calls, unknown names) and cloud redaction; CSV export
neutralisation; XLSX bomb/macro/DTD checks; CAS multipart parsed in memory with part/field limits; encrypted backup
format (AAD over the header, bounded scrypt parameters, no overwrite on restore); no `eval`/`exec`/`pickle`/
`subprocess`/`yaml.load`; frontend token removed from the URL with `replaceState`, CSRF kept in memory, external
links `https://` only.
