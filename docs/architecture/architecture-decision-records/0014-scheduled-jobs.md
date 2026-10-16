# ADR-0014: Scheduled jobs (daily refresh) and the narrow cron route

Status: **Proposed (2026-10-16), awaiting the owner's acceptance.** Built by packages A03 (security exception), A04
(`vercel.json` crons, shipped disabled), A10 (tables) and B03 (route and jobs). Live behaviour is NOT VERIFIED until the
first production run (see "Not verified").

## Context

- The 98 s NAV refresh runs only when the owner presses a button in the browser; nothing is scheduled
  (`docs/research/wave1/audit-journey.md`; PLAN §4 rank 11).
- The app has to prepare the Today page before the owner looks at it (PLAN §1). That needs a scheduler.
- Vercel Hobby cron facts, all VERIFIED 2026-10-15 in `docs/research/wave1/research-automation-infra.md` §1.1:
  - "Hobby accounts are limited to daily cron jobs" (https://vercel.com/docs/cron-jobs/usage-and-pricing);
  - a job "will trigger anywhere between 1:00 am and 1:59 am" for `0 1 * * *`; "The timezone is always UTC";
  - "Vercel will not retry an invocation if a cron job fails"; delivery is "best effort" and "can also occasionally
    invoke the same scheduled run more than once" (https://vercel.com/docs/cron-jobs/manage-cron-jobs);
  - the call is "an HTTP GET request to your project's production deployment URL", with `CRON_SECRET` sent as
    `Authorization: Bearer …`;
  - Hobby function limit "300s".
- ADR-0008 and ADR-0013 refuse three properties every cron call has: the deployment Host (not `IIP_PUBLIC_ORIGIN`), no
  session cookie, and a side effect on a GET (`research-automation-infra.md` §3).

## Decision

1. **Five daily jobs**, each one resumable step of at most 90 s (`HOSTED_JOB_BUDGET_S`, ADR-0013) that catches up on
   everything since its last success (`design-risk-first.md` §9.1):

   | Job | UTC hour → IST window | Work |
   |---|---|---|
   | J1 `navall` | 01 → 06:30–07:29 | Fetch NAVAll; upsert only held, watched and (local mode) core-universe rows — see ADR-0017 |
   | J2 `navall-continue` | 02 → 07:30–08:29 | Finish an open run; RBI T-bill RSS poll; MoSPI CPI check |
   | J3 `history` | 03 → 08:30–09:29 | Gap-fill NAV history for stored schemes; refresh `series_grid` |
   | J4 `snapshot` | 05 → 10:30–11:29 | Risk engine over all goals → content-addressed `signal_snapshots` (ABSTAIN stored too); shadow `rule_evaluations` (ADR-0016) |
   | J5 `watchdog` | 13 → 18:30–19:29 | If today's snapshot is missing or a dataset is stale, queue one "needs attention" ping |

   Business days are decided inside the job from the trading calendar, never in the cron expression. The calendar
   oracle ends on 2026-12-31; a manual task to load the 2027 NSE holiday circular is part of B06.
2. **One narrow route:** `GET|POST /api/cron/{job}`, `job` from the fixed enum above, no parameters. The job decides
   what to do from database state only.
   - The `$VERCEL_URL` host is accepted **on this route only**. Every other route keeps returning 400 on that host, and
     a test asserts it (A03).
   - `Authorization: Bearer <CRON_SECRET>`, compared with `hmac.compare_digest`. `CRON_SECRET` is at least 32
     characters (the app's own token rule; Vercel's floor is 16) and must differ from `IIP_ACCESS_TOKEN`. It grants
     "run a fixed job", never a session.
   - An empty or missing `CRON_SECRET` makes the route answer **404**. The `crons` array therefore ships in
     `vercel.json` disabled in effect until the owner sets the secret (graft 18).
   - A wrong secret returns 401 and is counted in `rate_hits` like login (10/min).
   - Production only: the handler refuses when `VERCEL_ENV != "production"`.
   - The response carries codes and counts only, never amounts or holdings.
   - The ADR-0008 rule "GET has no side effects" is amended **for this path only**: the side effect is idempotent and
     authenticated by a secret header.
3. **Idempotency** (`design-risk-first.md` §9.3, with the verify-file fix for killed runs):
   - claim with one conditional upsert on `cron_runs(job, run_key)` that also takes over a `failed` row or a `running`
     row older than the stale cutoff; `:now` and `:stale_before` come from the service layer, never from `engine/`;
   - `run_key` is the **data as-of date** (the AMFI NAV date the job targets), derived after a cheap conditional fetch
     (graft 19), never the wall-clock date;
   - all writes are idempotent upserts, so a duplicate delivery is a no-op;
   - the outbox reaper marks stale `sending` rows `failed` and **never resends**: losing a ping is the safe direction.
4. **Notifications are off by default** (U-09 default). When enabled, a ping says only that the report is ready; see
   ADR-0018.
5. **Local mode** gets the same jobs through `make run` / a local scheduler; local mode is where the full core-universe
   tracking runs (U-01, ADR-0017).

## Consequences

- The Today page reads a stored snapshot in one statement; the engine never runs on page load (B02).
- A missed or duplicated Vercel delivery costs at most one day of freshness; the next run catches up.
- The deployment-host exception is new attack surface. Threats SEC-cron-1…4 (`research-automation-infra.md` §3) are
  added to the threat model by the package that edits it; the per-route 400 test guards SEC-cron-2.
- Hobby fires "anywhere in the hour", so the IST windows above are windows, not times.

## Not verified (checked on the first live run, B03)

- Whether the cron request's Host is the deployment URL on this project (third-party evidence only:
  https://github.com/namphuongtran/familyroots/issues/265).
- Whether Vercel Deployment Protection intercepts the cron call.
- Whether each job fits 90 s against the `bom1` database (depends on U-12; see `docs/operations/turso-bom1-move.md`).

## Evidence

`docs/research/wave1/research-automation-infra.md` §1, §3, §4; `docs/research/wave1/design-risk-first.md` §9;
`docs/research/wave1/design-judgement.md` §2.3 items 18–19; PLAN §5.1 rule 2, rows A03, A04, B03.
