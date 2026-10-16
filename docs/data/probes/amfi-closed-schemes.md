# AMFI survivorship probe: do closed and merged schemes appear in NAV history?

Package A09 (`docs/research/wave1/PLAN.md` §5.2). Tool: `backend/scripts/probe_amfi_closed.py`.
This page holds **the answer and counts only**. No scheme code, name, ISIN or NAV is recorded here, and the probe saved
no raw response (AMFI terms of use: personal, non-commercial use; no significant storage).

## Answer

| Question | Status |
|---|---|
| Do schemes that no longer publish a NAV (closed, matured, wound up or merged) appear in AMFI NAV history? | **VERIFIED: yes** (live run, 2026-10-16) |
| Does AMFI NAV history contain **every** closed or merged scheme (completeness)? | **NOT VERIFIED** |
| Can a closure be told apart from a merger from AMFI's files? | **NOT VERIFIED**: neither file says which; the code reports "stopped publishing" only |
| Earliest NAV-history date per core-universe (U1) role | **REQUIRES CONFIGURATION**: needs the user-confirmed role bindings (J-7, package B06). Run `earliest` locally; the dates print to your terminal only |
| `tp` = 1 is open-ended, 2 close-ended, 3 interval | tp 1 and tp 2: **VERIFIED** (every accepted row of the tp 1 window sat under an "Open Ended Schemes" section and every tp 2 row under "Close Ended Schemes"). tp 3: NOT VERIFIED (AMFI returned no data for this fund house in the window) |

## Method

1. Fetch today's NAVAll and scheme master (parsed in memory).
2. Fetch one past 90-day history window, 2015-01-01 to 2015-03-31, for one large fund house, for `tp` 1, 2 and 3.
3. For every scheme code in that window, look up today's NAVAll: **live** (current NAV), **dormant** (in NAVAll with a
   NAV date more than 30 days older than the file's newest date) or **absent**.
4. If any code in the old window is dormant or absent today, schemes that stopped publishing do appear in history.

The scheme master's `Closure Date` is **not** used to call a scheme closed: in the probed layout it equals the launch date
for open-ended schemes, so it reads as the NFO closing date.

## Counts (live run, 2026-10-16T04:00Z, one fund house)

| Count | Value |
|---|---|
| Scheme codes in today's NAVAll | 14,126 |
| Scheme codes in today's scheme master | 16,452 |
| Codes in the 2015 window, `tp` 1 (open-ended) | 217 |
| Codes in the 2015 window, `tp` 2 (close-ended) | 869 |
| Codes in the 2015 window, `tp` 3 (interval) | 0 |
| Codes in the 2015 window, total | 1,086 |
| … still live today | 157 |
| … dormant in NAVAll today | 23 |
| … absent from today's NAVAll | 906 |
| … absent from today's scheme master | 904 |
| … no current NAV today, `tp` 1 (open-ended: closures, mergers or plan consolidations) | 60 |
| … no current NAV today, `tp` 2 (close-ended: maturities in the main) | 869 |
| … series that stopped inside the window itself | 44 |
| History rows rejected by the parser | 0 |

## What this means for the gates

- G2 (survivorship) for cross-sectional rules: AMFI history **does** carry schemes that later stopped, including 60
  open-ended ones from this one window. That is necessary, not sufficient: completeness is NOT VERIFIED, so cross-sectional
  rules stay `ABSTAIN (survivorship_unverified)` until a wider check (more fund houses and windows) is run and reviewed.
- Pre-2013 rows are labelled `history: regular_plan_pre_2013` by the parser helpers (Direct plans start 2013-01-01).

## How to rerun (local, personal use)

```sh
cd backend
PYTHONPATH=src .venv/bin/python scripts/probe_amfi_closed.py survivorship --mf <fund-house id> --from 2015-01-01 --to 2015-03-31
PYTHONPATH=src .venv/bin/python scripts/probe_amfi_closed.py earliest --roles /path/outside/repo/roles.json --since 2006-04-01
```

Copy only the answer and the counts into this page.
