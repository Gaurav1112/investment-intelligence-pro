# ADR-0017: Data rights — AMFI in hosted mode, index-derived constants, equity data

Status: **Proposed (2026-10-16), awaiting the owner's acceptance.** The owner decided U-01, U-10 and U-12 on 2026-10-16
(`docs/product/decisions-register.md`); U-08 and U-17 use the PLAN §3 defaults. Extends ADR-0004 (data sources,
licensing posture and provenance).

## Context

All quotes below were read in wave 1 (access date 2026-10-15) and are repeated from the cited reports; no new web
research was done for this ADR.

- **AMFI** terms (https://www.amfiindia.com/terms-of-use, via `docs/data/source-registry.md` §2.1) grant a right "for
  your personal and non-commercial use only" and say "You may not publicly perform, publicly display, transmit,
  publish … or create derivative works … You shall not store electronically any significant portion of any part of
  the Site." The registry already treats any hosted deployment as **REQUIRES LICENCE / WRITTEN PERMISSION**.
- **niftyindices.com** terms (https://www.niftyindices.com/terms-of-use, verify MOM-8): "personal, non-commercial use
  only" and "No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted, posted
  or distributed in any form without prior written permission from the Company". The stress-table constants
  (−59.5 / −67.0 / −72.9 / −75.6 %) were computed from niftyindices TRI series.
- **NSE** terms (https://www.nseindia.com/static/nse-terms-of-use, "Updated on: 29/10/2025"): "User is prohibited to
  conduct any systematic or automated data collection activities", and data may not be used "for any gaming, virtual
  trading or simulation activities under any circumstances whatsoever" (verify NSE-2).
- Single-stock signals cannot pass gates G2/G3 on any permitted free route: no delisted stocks, dividends and demergers
  unadjusted (`research-equity-data-alt.md`; verify EQ-6).

## Decision

1. **AMFI, hosted (U-01, decided 2026-10-16): local-first.**
   - Local mode (`make run` on the owner's machine) auto-tracks the core universe (≤ 30 schemes, U-07) plus holdings and
     watchlist.
   - Hosted mode (Vercel/Turso) **stores only rows for schemes the owner holds or watches**. J1 discards every other
     NAVAll row in memory; nothing beyond that is archived.
   - Backtests never run hosted; hosted mode imports evidence bundles that contain no raw NAVs (ADR-0016).
   - In parallel, the owner may send AMFI the permission letter drafted in
     `docs/operations/amfi-permission-letter-draft.md` (U-17). Nothing changes until a written answer arrives; this ADR is
     then revised.
2. **Index-derived stress constants (U-08 default): local config, not the public repo.** The rule table keeps the
   schema and a citation pointer; the values are loaded from the owner's local config. The engine uses
   `max(cited, AMFI-recomputed)` anyway (ADR-0015), so the app still works without them, with the AMFI series start date
   shown.
3. **Equity data (U-10, decided 2026-10-16): none.** No stock or ETF price feed; stocks ABSTAIN with
   `no_lawful_survivorship_free_data`. NSE, BSE and niftyindices automation and NSE-scraping libraries stay BLOCKED;
   Kite and every paid feed stay excluded. Broker APIs (Upstox, Angel One) remain REQUIRES CONFIGURATION, local only,
   behind optional package X-01 if U-10 is ever reopened.
4. **Every source carries a licence class and a status label** in `data/registry.py` (A07) and on the Settings data
   rights panel (C04): VERIFIED, NOT VERIFIED, REQUIRES CONFIGURATION or BLOCKED, with the decision that would unblock
   it.
5. **Repo hygiene (public repo):** no market-data files, no real scheme codes or ISINs, no backtest outputs and no
   index-derived constants are committed. Fixtures are synthetic.

## NOT VERIFIED (recorded as required by PLAN row A01)

| Item | Why it is open | What would settle it |
|---|---|---|
| **AMFI hosted storage** | Whether storing held/watched schemes' NAVs (or a capped universe) in a hosted database is "personal" use, and whether it is a "significant portion" or a "derivative work" under the AMFI terms, is an interpretation. | A written answer from AMFI to the letter (U-17), or legal advice. |
| **niftyindices stress-constant provenance** | Whether drawdown statistics derived from niftyindices series are "material from the Site" that may not be "copied … uploaded" without permission is an interpretation. | A written answer from NSE Indices, or replacing the constants with AMFI-recomputed drawdowns. Until then: local config (decision 2). |
| **NSE "simulation" ambiguity** | Whether a private historical backtest is a "simulation activity" under the NSE terms. The clause groups it with "gaming" and "virtual trading"; NSE's data policy §8.4 omits the word "simulation" (verify NSE-2). Treated as blocked by project policy. Matters only if equity data is ever used. | A written answer from NSE (marketdata@nse.co.in), U-17. |
| Broker developer terms (Upstox, Angel One) on storage and backtesting | Unread (X-01). | Reading them, if U-10 is reopened. |

## Consequences

- The phone (hosted) view shows full data only for held and watched schemes; discovery and core-universe tracking are
  richer on the local machine.
- Each hosted NAVAll run ends with `purge_untracked_hosted`: every NAV (latest included) and month-end series of a
  scheme that is no longer held or watched is removed, with its instrument row unless user-entered data (factsheet
  facts, goal mapping, role binding) refers to it. This also clears rows a pre-fix hosted refresh stored. A scheme
  with any recorded transaction counts as held (its history values the ledger), even after it is fully sold.
- The engine keeps working without the niftyindices constants, using AMFI-recomputed drawdowns that may start after
  2008 for some roles (A09 measures the start dates).
- Stock pages show holdings, sizes against limits and tax dates only, never buy/sell output.

## Evidence

`docs/data/source-registry.md` §2.1; `docs/research/wave1/verify-equity-data-nse.md` NSE-2, NSE-3;
`verify-evidence-momentum.md` MOM-8; `research-equity-data-alt.md`; `design-judgement.md` §2.1 item 4, §2.4;
PLAN §3 (U-01, U-08, U-10, U-17), §6, §7, §8.
