# ADR-0004: Data sources, licensing posture and provenance

## Decision (v1)
| Source | Mode | Status label |
|---|---|---|
| AMFI `NAVAll.txt` (latest) | Live adapter, run on the user's machine | REQUIRES CONFIGURATION (network) |
| AMFI NAV history report | Live adapter, **only for held, watched or shortlisted schemes** | REQUIRES CONFIGURATION |
| AMFI scheme master CSV | Live adapter (metadata) | REQUIRES CONFIGURATION |
| MoSPI CPI API | Adapter needing a user-supplied token; base-2012 and base-2024 series kept **separate** | REQUIRES CONFIGURATION |
| RBI T-bill auctions, policy rates | **Manual entry or user-triggered fetch** with a dated citation (RBI blocks scripts with HTTP 418; its disclaimer prohibits caching) | Manual |
| G-sec / SDL / corporate bond prices and ratings | Manual entry with a citation (NSE/BSE/CCIL/FBIL/CRA terms restrict automated use) | Manual |
| Bank FD rates, small-savings rates | Manual entry with a citation | Manual |
| mfapi.in | Disabled by default; optional cross-check only, labelled UNOFFICIAL | Optional |
| yfinance, NSE scraping | **Not used** | — |

- **Licensing posture:** AMFI's terms allow personal, non-commercial use and forbid storing "any significant portion". We keep the latest snapshot for discovery, keep history only for a bounded set of schemes, never redistribute, and expose no public API. Legal review is flagged (regulatory-readiness.md).
- **Provenance contract:** every observation row carries `source_id, source_url, retrieved_at (UTC), observation_date (IST date), publication_time?, currency, unit, quality_status, convention, raw_hash`.
- **Quality statuses:** `ok | stale | suspect | rejected | fixture | manual`. Rows marked `rejected`, and `stale` rows beyond their SLO, are excluded from ranking. Stale values are never forward-filled.
- **Fixtures** are labelled `fixture` and render with the FIXTURE badge. They are never shown as market data.

## Evidence
source-registry.md (probes: 5,397 of 14,376 NAVAll rows were dated before 2026; RBI returned HTTP 418).
