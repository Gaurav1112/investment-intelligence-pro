# Verification Report

Date: 2026-10-15 · Machine: macOS (Apple Silicon), Python 3.12.13, Node 24.15 · All results below come from **actual runs**.

Status labels: **VERIFIED** (executed, with evidence) · **IMPLEMENTED, NOT VERIFIED** · **REQUIRES CONFIGURATION** · **BLOCKED**.

## 1. Automated test results (final run — see §6 for the command log)

| Suite | Result |
|---|---|
| Backend `pytest` (unit, property, oracle, data, services, API, security, red-team) | **VERIFIED — 1,237 passed, 1 skipped (opt-in live-network test)** (Track 6 re-run; 1,231 before the 6 new tax tests) |
| Backend `ruff check` / `ruff format --check` / `mypy --strict` (69 source files) | **VERIFIED — ruff clean, 134 files formatted, mypy --strict: no issues in 69 source files** |
| Frontend `vitest` | **VERIFIED — 208 passed (23 files)** |
| Frontend `tsc` type-check and production build | **VERIFIED — tsc OK; Vite production build OK** |
| Dependency audit (`pip-audit --strict`, `pnpm audit --prod`) | **VERIFIED — no known vulnerabilities (Python and npm) on 2026-10-15** |

### What the backend suite covers

| Area | Evidence | Independent oracle |
|---|---|---|
| Money / rounding / Indian formatting | `tests/unit/test_money.py` (spec fixtures incl. HALF_UP/HALF_EVEN ties, lakh/crore boundaries, 10^15) | — |
| Day counts, EDATE, calendars | `tests/unit/test_dates.py` (RBI FAQ 65-day example, 30E vs US, SEBI leap rule) | — |
| Returns, CAGR, TWR, XIRR, costs | `tests/unit/test_returns.py`, `test_costs.py`, property tests | **pyxirr**, **scipy brentq** (worst 9.8e-10) |
| Fixed income (T-bill, G-sec, corporates, YTM/YTC, duration, convexity) | `tests/unit/test_fixed_income.py`, properties | **QuantLib 1.44** (1e-8 … 1e-10); reproduces RBI 14-Oct-2026 auction cut-off yields |
| Deposits (FD, DICGC) | `tests/unit/test_deposits.py` | QuantLib compounding (₹1e-6) |
| Tax (65 versioned rules, ITA 1961 → 2025; table `india-tax@2026-10-15.r2`) | `tests/unit/test_tax.py`, `test_rules_loader.py` (incl. 3 correction regression tests and a primary-citation check on every rule upgraded from NV) | No computational oracle exists. Rules checked against the **statute text** (Income-tax Act 2025 as amended by FA 2026; Finance Acts 2024, 2025, 2026; ITA 1961): 51 P / 6 S / 8 NV (was 31 / 14 / 20) → IMPLEMENTED, NOT VERIFIED until CA sign-off (`docs/finance/ca-review-packet.md`) |
| Risk metrics, scenarios | `tests/unit/test_risk_metrics.py`, `test_scenarios.py`, properties | **numpy/scipy/QuantLib** (1e-9 … 1e-12) |
| Forecast baselines, walk-forward, DM-HLN, feasibility | `tests/forecasting/*` incl. a planted-future-information leakage test | **scoringrules** (1e-12) |
| Ranking policy 1.1.0 | `tests/unit/test_ranking.py` + 6 Hypothesis invariants (permutation invariance, partition, junk-candidate stability, tier monotonicity, no projected loss under preservation) | — |
| Supervisor (gate, contracts, compliance, conflicts, reproducibility) | `tests/supervisor/test_supervisor.py`, `tests/redteam/test_redteam_supervisor.py` | — |
| Data ingestion (strict parsers, validators, SSRF-safe fetcher, imports/exports) | `tests/data/*` (probe-derived fixtures) | ISIN checksum vs known real ISINs |
| Explained-number contract across 8 API flows | `tests/api/test_explained_contract.py` | — |
| Concurrency | `tests/api/test_concurrency.py` (80 parallel requests) | — |
| Security (threat-model SEC-xx) | `tests/security/*` — see §3 | — |
| Red-team reproductions | `tests/redteam/*` — 53 tests; **40 fail on the pre-fix code** (verified by stashing the fixes) | — |

## 2. Live verification (real network, real data; personal use within AMFI's terms)

| Check | Status | Evidence |
|---|---|---|
| AMFI NAVAll live fetch → parse → validate → store | **VERIFIED** | 14,376 rows; 14,125 accepted; 251 rejected with reasons; 1,779 schemes stored (minimised scope) |
| AMFI NAV-history backfill | **VERIFIED** | HDFC Liquid Direct Growth: 11 years, 3,769 NAVs in 64 s; only that scheme's rows kept |
| Manual T-bill from RBI press release (14-Oct-2026, 182-day cut-off 6.2896 %) | **VERIFIED** | Ranked T1; ₹5,00,000 → ₹5,10,729.19 after illustrative tax (hand-checked) |
| Discovery on live data only (fixtures refused in personalised mode) | **VERIFIED** | T-bill (T1) then HDFC Liquid (T3, 0 of 3,587 loss windows) |
| Return-target feasibility on live data | **VERIFIED** | ≥ 20 % p.a. over 1 y: 0 of 60 windows; ≥ 6.5 %: 30 of 60; 3-year question refused (1 independent period) |
| All 16 pages in a real browser (CSP active) | **VERIFIED** | Screenshots in `docs/screenshots/` and `docs/screenshots/ux/`; no console errors after fixes |
| Backup + restore drill | **VERIFIED** | `make backup`, `make restore-drill` against the live-data DB |
| Clean-machine `make setup` from an empty checkout | **IMPLEMENTED, NOT VERIFIED** | Toolchain was already present on this machine |

### Defects found only by live verification (all fixed, each with a regression test)

1. AMFI sections without an AMC line (4 in the real file) — parser failed closed → brand-checked carry-forward.
2. Unit-string mismatch stored every NAV as `rejected` — an earlier claim of "verified" was retracted and corrected.
3. Same NAV date from two official AMFI sources → duplicate dates → merged when equal, `SOURCE_CONFLICT` when not.
4. Real AMFI category labels: ELSS index funds filed under "Index Funds"; FMP/interval schemes → name-based lock-in, close-ended refusal.
5. Login link opened in an already-open tab (same-document hash change) kept a dead session.
6. Results table overflow, misleading "market-linked" FD tier label, raw codes and 34-digit precision in the UI.
7. Re-entered T-bill quote crashed Discovery (duplicate candidate ids).
8. Parallel requests on one shared SQLite connection → `InterfaceError` (500) → per-thread connections.

## 3. Security verification (threat model `docs/security/threat-model.md`)

| Control | Status | Tests |
|---|---|---|
| Host+port allowlist (DNS rebinding), loopback-only bind, startup refusals | VERIFIED | SEC-01…04, 14, 15 (`test_api_security.py`); also checked live with `curl` (evil Host → 400) |
| Mandatory token, session cookie attributes, login rate limit | VERIFIED | SEC-11…13 |
| CSRF (header + Origin/Sec-Fetch-Site + content type), no CORS | VERIFIED | SEC-05…09; mutation-tested (removing the check fails the tests) |
| CSP and hardening headers, generic errors, no docs in prod | VERIFIED | SEC-20…22 |
| GET routes never write | VERIFIED | SEC-10 (found and fixed a DDL write in `/api/ready`) |
| No URL input is fetched; TLS never disabled; no dangerous calls | VERIFIED | SEC-54, 57, 65 |
| Injection / fuzzed bodies never 500 | VERIFIED | SEC-60, 61 (Hypothesis) |
| Upload caps, zip bomb, macros, XXE, formula injection on export | VERIFIED | SEC-30…34, 40 (`tests/data/test_imports_exports.py`) |
| SSRF-safe fetcher (allowlist, private IPs, redirects, byte caps, IP pinning) | VERIFIED | SEC-50…53 (`tests/data/test_fetch.py`) |
| Logs contain no amounts/names; no secrets in status/errors/repr | VERIFIED | SEC-62…64 |
| Prompt injection / unsourced numbers / banned phrases in narrative | VERIFIED | SEC-70, 71, 72 (supervisor + red-team obfuscation tests) |
| Privacy export / erase (DB **and** WAL bytes), backups included | VERIFIED | SEC-80, 81 + erase-backup regression |
| File permissions 0700/0600 | VERIFIED | SEC-82 (found and fixed default permissions) |
| Manual refresh rate limit | VERIFIED | SEC-86 (found and fixed: no limit existed) |
| Dependency audit | VERIFIED | SEC-84 via `make audit` (found pytest PYSEC-2026-1845 → upgraded) |
| Cross-origin page attack (Playwright, second origin) | IMPLEMENTED, NOT VERIFIED | SEC-16 — covered at the API level by the CSRF/Origin tests; browser-level test not automated |
| XSS through imported names rendered in the UI | IMPLEMENTED, NOT VERIFIED (browser) | SEC-23 — React text rendering + CSP; `dangerouslySetInnerHTML` banned by test (SEC-24); no Playwright test |
| LLM adapter controls (prompt contents, loopback endpoint, cloud allowlist, output validation, timeouts, memoisation) | VERIFIED (stub server) | SEC-70…76: `tests/security/test_llm_boundary.py` and `tests/api/test_llm_api.py` against an httpx MockTransport stub. No live model was available (127.0.0.1:11434 and :1234 not listening), so live wording quality is IMPLEMENTED, NOT VERIFIED |
| Encrypted backups | N/A in v1 | SEC-83 — optional feature not built |
| Supply-chain pinning policy (`minimumReleaseAge`, `onlyBuiltDependencies`) | Open | SEC-85 — lockfiles present and frozen in `make setup`; the pnpm policy settings are not configured |

## 4. Determinism guarantees

| Guarantee | Evidence |
|---|---|
| Engine purity (no clock, I/O, unseeded randomness, oracles in runtime) | `tests/unit/test_engine_purity.py` (AST scan) |
| Same inputs → same output hash (ranking, discovery, supervisor runs, analysis) | `test_identical_inputs_give_identical_result_hash`, `test_run_is_reproducible`, ranking property tests |
| Stored runs replay | `runs` table; `/api/runs/{id}` returns the stored output hash; API test compares it |
| Bootstrap randomness seeded and recorded | `tests/forecasting/test_baselines.py` |

## 5. Independent review

- Backend red team (Agent J): `docs/audit/final-red-team-report.md` — 8 high, 9 medium, 4 low; all high fixed.
- Independent final review (Agent L): same report, "Independent final review" section — reproduction tests confirmed to fail
  on the pre-fix code; open items triaged; two product decisions (RT-19, RT-20) made by the user and implemented as
  `ranking_policy@1.1.0`.

## 6. Command log (final run)

```
$ cd backend && .venv/bin/pytest -q -p no:warnings
1231 passed, 1 skipped in 83.13s (0:01:23)
$ ruff check src tests && ruff format --check src tests && mypy
All checks passed!
134 files already formatted
Success: no issues found in 69 source files
$ cd frontend && node --run typecheck && node --run test && node --run build
typecheck: OK
 Test Files  23 passed (23)
      Tests  208 passed (208)
✓ built in 183ms
$ make audit
No known vulnerabilities found
No known vulnerabilities found
```
