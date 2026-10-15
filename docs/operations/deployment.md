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
   page) with its URL and date. The app never scrapes RBI, NSE, BSE, CCIL or FBIL (their terms prohibit it).

## Development

```bash
make dev            # backend in dev mode (fixtures allowed) + Vite HMR on http://127.0.0.1:5173
```

- In dev mode `POST /api/dev/seed-fixtures` creates **synthetic FIXTURE instruments**. They are badged and hatched everywhere, and
  personalised ranking refuses them unless the "demonstration only" toggle is used. Production mode refuses to seed them.
- The Vite dev server keeps its default host check. The backend accepts the dev origin only when `IIP_ENV=dev`.

## Quality gate

```bash
make check          # backend + frontend tests, ruff, mypy --strict, tsc, production build, dependency audit
```

`make audit` runs `pip-audit --strict` on the locked Python dependencies and `pnpm audit --prod`. It fails on any known vulnerability.

## Backups

```bash
make backup         # SQLite online backup API → ~/.iip/backups/iip-<UTC>.db, verified with integrity_check
make restore-drill  # restores the newest backup into a temp file and checks it (never touches the live DB)
```

To restore for real: stop the app, keep a copy of `~/.iip/iip.db`, then use `iip.store.db.restore(backup, ~/.iip/iip.db)`.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `IIP_ENV` | `prod` | `prod`, `dev` or `test`. Fixtures and API docs exist only outside `prod`. |
| `IIP_HOST` | `127.0.0.1` | A non-loopback value is refused unless `IIP_ALLOW_NON_LOOPBACK=1` (strongly discouraged) |
| `IIP_PORT` | `8741` | |
| `IIP_DATA_DIR` | `~/.iip` | Database, token and backups |
| `IIP_AUTH` | `on` | `off` only with `IIP_ENV=test` |
| `IIP_DEV_ORIGINS` | — | Extra browser origin for the Vite dev server (dev only) |
| `IIP_LLM` | `off` | The optional LLM adapter is not part of v1 (see known limitations) |

## Status labels for this document

- Local run, login flow, fixture demo, live AMFI NAVAll + history ingestion, backup and restore drill: **VERIFIED** on 2026-10-15
  (macOS, Apple Silicon).
- Clean-machine `make setup` from an empty checkout: **IMPLEMENTED, NOT VERIFIED**. This machine already had the toolchain.
