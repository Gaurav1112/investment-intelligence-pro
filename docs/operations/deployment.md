# Deployment and Operation (local, single user)

Investment Intelligence Pro runs **only on your own machine**. It binds to `127.0.0.1` and refuses any other address. There is
no hosted version: data-licence terms (AMFI: personal, non-commercial use only) and the regulatory analysis
(`docs/security/regulatory-readiness.md`) both assume personal use.

## Requirements

| Tool | Version used | Notes |
|---|---|---|
| Python | 3.12 (managed by `uv`) | `uv sync --frozen` installs the exact lockfile |
| uv | ≥ 0.11 | |
| Node.js | 24 | Run scripts with `node --run …` (see the quirk below) |
| pnpm | 10 | Used **only** for `pnpm install` / `pnpm audit` |
| Disk | ~0.5 GB | venv ~300 MB, node_modules ~160 MB, data grows slowly |

**Machine quirk (this Mac):** Volta's pnpm runs under Node 20 even though `node` is Node 24. Because of this, the Makefile never runs
`pnpm <script>`; it always uses `node --run <script>`. The frontend has no native addons, so the quirk cannot cause segfaults.

## First run

```bash
make setup          # pinned dependencies (uv.lock, pnpm-lock.yaml)
make run            # builds the frontend, starts http://127.0.0.1:8741 (creates ~/.iip and the access token)
make open           # in a second terminal: opens the browser with the one-time login link
```

- Data lives in `~/.iip` (override with `IIP_DATA_DIR`): `iip.db` (SQLite), `secrets/access-token` (mode 0600), `backups/`.
- The login link puts the token in the URL **fragment** (`#login=…`). The browser never sends the fragment to the server. The app
  removes it from the address bar immediately and exchanges it for an HttpOnly, SameSite=Strict session cookie.
- Restarting the server ends all sessions. Run `make open` again.

## Getting real data (personal use)

1. **Data health → Fetch latest AMFI NAVs.** Downloads AMFI's `NAVAll.txt` once and keeps only Direct-plan Growth schemes plus
   anything you hold or watch (data minimisation, per AMFI's terms of use).
2. **Mutual funds → Backfill history** for each scheme you want evaluated. This makes polite, rate-limited 90-day requests and keeps
   only that scheme's rows. Discovery needs enough history for at least 10 independent windows at your horizon. For example, a 6-month
   horizon needs about 5 years of history; with less, the scheme is excluded and the reason is shown.
3. **Mutual funds → Enter exit load** for non-liquid funds, from the scheme's SID/KIM, with a citation. No public source publishes exit loads, so
   until you enter one, the fund is excluded (`EXIT_LOAD_UNKNOWN`) rather than assumed load-free.
4. **Fixed income → add T-bills / FDs.** Enter the yield or rate from the official page (RBI auction press release, the bank's rate
   page) with its URL and date. The app never scrapes RBI, NSE, BSE, CCIL or FBIL (their terms prohibit it). For an FD, also
   state the deposits you already hold at that bank (0 if none); FDs in your actual portfolios at the same bank are added
   automatically. With neither, DICGC cover cannot be checked and the FD is never ranked as insured.

## Importing a CAS statement (CAMS / KFintech PDF)

Status: **IMPLEMENTED, NOT VERIFIED** with a real statement (tests use a synthetic PDF only).

1. Request a **Detailed** Consolidated Account Statement (with transactions, from the beginning) from CAMS or KFintech. It arrives
   as a password-protected PDF; the password is usually derived from your PAN and date of birth. Summary statements and
   NSDL/CDSL depository statements are refused because they carry no transaction ledger.
2. Make sure the schemes are in the local store first (**Data health → Fetch latest AMFI NAVs**). Matching is by the **exact ISIN**
   printed on the statement, never by name; a scheme whose ISIN is not stored is shown as *unmatched* and none of its rows are
   imported.
3. **Overview → open a portfolio → Import CAS statement (PDF).** Choose the PDF, type the password, and press *Preview CAS
   import*. The PDF and password are used in memory only for that request and are not stored or logged; the file is not written
   to disk. Your name, PAN, email, address, phone and folio numbers are discarded. The PDF must fit within the 5 MiB request limit.
4. Read the preview: rows that will be stored (purchases, SIPs and switch-ins as buys; redemptions and switch-outs as sells;
   IDCW payouts as dividends), rejected and ignored rows with reasons (stamp duty/STT/TDS are ignored), and the **reconciliation**
   of each scheme's closing units on the statement against the units this import would add. A mismatch must be ticked as
   reviewed before applying; a statement that would sell more units than were bought is blocked (OVERSELL).
5. *Confirm and store* applies exactly the previewed rows, confirmed by the file's SHA-256, after a pre-import backup
   (`~/.iip/backups/*pre-import*.sqlite3`), in one database transaction. Re-importing the same file is refused.

## Development

```bash
make dev            # backend in dev mode (fixtures allowed) + Vite HMR on http://127.0.0.1:5173
```

- In dev mode `POST /api/dev/seed-fixtures` creates **synthetic FIXTURE instruments**. They are badged and hatched everywhere, and
  personalised ranking refuses them unless the "demonstration only" toggle is used. Production mode refuses to seed them.
- The Vite dev server keeps its default host check. The backend accepts the dev origin only when `IIP_ENV=dev`.

## Quality gate

```bash
make check          # backend + frontend tests, lockfile sync, ruff, mypy --strict, tsc, production build, dependency audit
make test-browser   # opt-in real-browser security tests (SEC-16 cross-origin, SEC-23 XSS) in headless Chromium
```

- `make audit` runs `pip-audit --strict` on the locked Python dependencies and `pnpm audit --prod`. It fails on any known
  vulnerability.
- `make lockcheck` (part of `make check`, SEC-85) runs `uv lock --check` and `pnpm install --frozen-lockfile
  --lockfile-only`, and asserts the pnpm policy in `frontend/pnpm-workspace.yaml`: `onlyBuiltDependencies: []` (no
  dependency install scripts run) and `minimumReleaseAge: 10080` (versions younger than 7 days are never resolved).
- `make test-browser` builds the frontend, installs Playwright's Chromium on first use (about 150 MB, into
  `~/Library/Caches/ms-playwright`), then starts the real server in production mode on a free port with a temporary data
  directory. The tests are skipped in plain `pytest` runs unless `IIP_BROWSER_TESTS=1`.

## Backups

```bash
make backup         # SQLite online backup API → ~/.iip/backups/iip-<UTC>.db, verified with integrity_check
make restore-drill  # restores the newest plain backup into a temp file, checks it, deletes the temp copy (never touches the live DB)
```

To restore for real: stop the app, keep a copy of `~/.iip/iip.db`, then use `iip.store.db.restore(backup, ~/.iip/iip.db)`.

### Encrypted backups (optional, SEC-83)

```bash
make backup-encrypted                       # → ~/.iip/backups/iip-<UTC>.db.enc (0600); prompts for a passphrase twice
make restore-encrypted                      # newest .enc → a NEW file ~/.iip/restored-<UTC>.db (never the live DB)
make restore-encrypted BACKUP=… DEST=…      # a specific file / destination (DEST must not exist)
```

- AES-256-GCM with a key derived by scrypt (n = 2¹⁷, r = 8, p = 1) from your passphrase (≥ 12 characters). The salt,
  nonce and KDF parameters are in the file's header, which is authenticated too. The passphrase is never stored.
- Set `IIP_BACKUP_PASSPHRASE` to run unattended; otherwise you are prompted. **A lost passphrase cannot be recovered.**
- The plaintext database never touches the disk during backup. Restore decrypts and checks everything in memory (GCM tag,
  then SQLite `integrity_check`) before writing anything: a wrong passphrase or a modified file fails cleanly and leaves
  no partial file. To use a restored file, stop the app and move it to `~/.iip/iip.db` (keep the old one).
- A restored file is a **plaintext** copy of your data. *Erase my data* with "delete backups" removes
  `restored-*.db` in the data dir along with every backup format; a custom `DEST=` elsewhere is yours to delete.

## Hosted on Vercel (personal use)

Status: **IMPLEMENTED, NOT VERIFIED on Vercel.** Design, research and limits are in ADR-0013. `make deploy-check`
(no network) is VERIFIED; the first real deploy must do the checks in ADR-0013 "Not verified".

**Conditions. Read these before deploying:**
- **Only you.** Never share the URL together with the token, and never give other people access. There is no
  multi-user model, and offering fund rankings to others raises SEBI adviser / research-analyst questions
  (`docs/security/regulatory-readiness.md`). AMFI data is for personal, non-commercial use only.
- **Third-party custody.** Your portfolio data will be held by **Turso** (the database and its backups) and processed
  by **Vercel**. The app never logs amounts or personal values, but the data is no longer only on your machine.
- **Missing when hosted:** file backups (use Turso's point-in-time restore, or Settings → Export), the local LLM, and
  byte-level erase (Turso's backups keep deleted rows until they expire).

### 1. Create the database (Turso, free tier)

**Simplest (verified 2026-10-15):** in the Vercel dashboard open the project → **Storage** → **Create Database** →
**Turso**, accept the terms, choose the free plan, and connect it to **Production**. The integration injects
`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` as *sensitive* variables (they cannot be read back or copied); the app reads
those names directly, so skip the two `IIP_DB_*` lines in step 3. (`vercel integration add turso` from the CLI needs
the marketplace terms accepted first and kept reporting `action_required` here, so the dashboard route is the one to
use.)

**Or manually:**

1. Create a Turso account and a database in an Indian region (Mumbai) from the Turso dashboard or the `turso` CLI.
2. Copy the database URL (`libsql://<db>-<org>.turso.io`).
3. Create an auth token for that database only.
4. Keep both values out of the repository and out of chat logs.

### 2. Generate your access token

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # 43 characters; keep it in your password manager
```

### 3. Create the Vercel project and set its environment (Production only)

```bash
vercel link                                   # once, from the repository root
vercel env add IIP_PUBLIC_ORIGIN production   # https://<your-project>.vercel.app — exact, no trailing slash
vercel env add IIP_ACCESS_TOKEN production    # the token from step 2
vercel env add IIP_DB_URL production          # libsql://…turso.io
vercel env add IIP_DB_AUTH_TOKEN production   # the Turso database token
vercel env add IIP_ENV production             # prod
```

| Variable | Required | Meaning |
|---|---|---|
| `IIP_DEPLOY` | set by `app.py` | `vercel`. Hosted mode is on |
| `IIP_ENV` | yes | `prod`. Any other value except `test` refuses startup when hosted |
| `IIP_PUBLIC_ORIGIN` | yes | The exact https origin users type. Every other Host is refused (so preview and deployment URLs return 400) |
| `IIP_ACCESS_TOKEN` | yes | At least 32 characters; refused otherwise |
| `IIP_DB_URL` | yes, unless `TURSO_DATABASE_URL` is set | `libsql://…` or `https://…`. Falls back to `TURSO_DATABASE_URL` (Vercel's Turso integration) |
| `IIP_DB_AUTH_TOKEN` | yes, unless `TURSO_AUTH_TOKEN` is set | Turso database token. Falls back to `TURSO_AUTH_TOKEN` |
| `IIP_LLM` | no | `off` (default) or `cloud`; `local` is refused when hosted |

Set these for **Production only**. Previews would otherwise run against the same database on a Host the app refuses
anyway.

### 4. Deploy and verify

```bash
make deploy-check        # builds the UI, checks vercel.json, requirements.txt and the hosted entrypoint (no network)
vercel deploy --prod     # uploads per .vercelignore; Vercel installs requirements.txt and runs scripts/vercel-build.sh
```

Then open `https://<your-project>.vercel.app/#login=<token>`. As with `make open`, the token is in the URL fragment and
is never sent to the server. Do the first-deploy checks in ADR-0013:
- the UI loads at `/`;
- **Data health → Fetch latest AMFI NAVs** completes (it may take several calls; the page shows progress);
- a backfill completes.

### Hosted maintenance

- After changing backend dependencies, run `make requirements`; `make deploy-check` fails if you forget.
- Rotating the token: change `IIP_ACCESS_TOKEN` in Vercel and redeploy. Existing sessions stay valid until they expire
  (24 h at most). To end them at once, run `DELETE FROM web_sessions` in the Turso shell.
- Restoring: use Turso's point-in-time restore into a new database, then point `IIP_DB_URL` at it.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `IIP_ENV` | `prod` | `prod`, `dev` or `test`. Fixtures and API docs exist only outside `prod`. |
| `IIP_HOST` | `127.0.0.1` | A non-loopback value is refused unless `IIP_ALLOW_NON_LOOPBACK=1` (strongly discouraged) |
| `IIP_PORT` | `8741` | |
| `IIP_DATA_DIR` | `~/.iip` | Database, token and backups |
| `IIP_AUTH` | `on` | `off` only with `IIP_ENV=test` |
| `IIP_DEV_ORIGINS` | — | Extra browser origin for the Vite dev server (dev only) |
| `IIP_LLM` | `off` | `off`, `local` or `cloud` (ADR-0007). `local` with a non-loopback base URL, or `cloud` with a URL off the allowlist, refuses startup. A config saved in Settings overrides it. |
| `IIP_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` in local mode | OpenAI-compatible base URL |
| `IIP_LLM_MODEL` | — | Model name, e.g. a model already pulled into Ollama |
| `IIP_LLM_API_KEY_ENV` | — | The NAME of the env var that holds the provider key (never the key itself) |

## Status labels for this document

- Local run, login flow, fixture demo, live AMFI NAVAll + history ingestion, backup and restore drill: **VERIFIED** on 2026-10-15
  (macOS, Apple Silicon).
- Clean-checkout `make setup` + `make check`: **VERIFIED on 2026-10-15** (macOS, Apple Silicon), details below.

### Clean-checkout verification (2026-10-15)

A fresh `git clone` of the branch (commit `3a49f66`) into an empty temporary directory, then:

| Step | Outcome |
|---|---|
| `make setup` | **Pass** (exit 0, 2.4 s). `uv sync --frozen` created `backend/.venv` from `uv.lock`; `pnpm install --frozen-lockfile` honoured the new `pnpm-workspace.yaml` (no build scripts). |
| `make check` | **Pass** (exit 0): backend pytest green, frontend 23 files / 208 tests, `make lockcheck` OK, ruff + format + `mypy --strict` (70 files) clean, `tsc` + Vite build OK, `pip-audit --strict` and `pnpm audit --prod`: no known vulnerabilities. |
| `make test-browser` | **Pass**: 5 real-browser tests (SEC-16, SEC-23). |

What this does and does not prove:
- Reused from this machine (as allowed): the uv download cache, the pnpm content-addressed store and the Playwright
  Chromium cache, so no package was fetched from scratch; the toolchain (uv 0.11, Python 3.12 via uv, Node 24, pnpm
  10.28 under Volta's Node 20) was already installed. A machine **without** that toolchain, or offline, was not tested.
- `make audit` needs network access (PyPI advisory data, npm registry).
- Gaps found and fixed: (1) `make test` printed no backend pass count (`-q` twice); it now does. (2) Starting the
  backend before `make build` served only the API, so every page was a silent 404; it now logs
  `frontend build missing … run make build` at startup (`tests/api/test_frontend_dist.py`). `make run` always builds
  first, so the normal path was not affected.
- The temporary clone was deleted afterwards.
