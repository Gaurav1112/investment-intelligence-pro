# Verification: automation-infra (adversarial review)

Reviewed: `docs/research/wave1/research-automation-infra.md` · reviewer pass written 2026-10-15 · every URL below was
opened on 2026-10-15 unless marked "search summary only". Repo files were read at their current state; nothing else was
modified.

Verdict scale: **CONFIRMED** (the source says what the report says) · **WEAKENED** (true in part, overstated, mislabelled
or resting on a wrong citation) · **REFUTED** (the source does not support it).

## Summary

| id | Claim | Report status | Verdict |
|---|---|---|---|
| AUTO-1 | Vercel Hobby cron: daily only, ±59 min, no retries, best effort, possible duplicates | VERIFIED | **CONFIRMED** |
| AUTO-2 | Cron calls would be refused (Host 400, session 401, GET rule) | NOT VERIFIED | **CONFIRMED** (code part certain; host part correctly left NOT VERIFIED) |
| AUTO-3 | Idempotency design for Turso | VERIFIED | **WEAKENED** (an unbuilt design labelled VERIFIED; SQL and key inconsistencies) |
| AUTO-4 | GitHub Actions `schedule` unsuitable as primary worker | VERIFIED | **CONFIRMED** |
| AUTO-5 | Telegram v1, Web Push v2, reject ntfy.sh public topics and Gmail app passwords | REQUIRES CONFIGURATION | **CONFIRMED** (minor caveats) |
| AUTO-6 | Free-tier quotas are comfortably sufficient | VERIFIED | **CONFIRMED** with caveats (one meter omitted; CPU share unmeasured) |
| AUTO-7 | Equity buy/sell automation BLOCKED by data terms | BLOCKED | **WEAKENED** (quote misattributed to NSE; broker-API route not considered) |

No finding is refuted outright. Two are weakened.

---

## AUTO-1 — CONFIRMED

Every quote was found verbatim:
- https://vercel.com/docs/cron-jobs/usage-and-pricing (page `last_updated: 2026-07-15`): Hobby row "100 cron jobs | Once
  per day | Per-hour (±59 min)"; "Hobby accounts are limited to daily cron jobs. This cron expression would run more than
  once per day."; "a cron job configured as `0 1 * * *` (every day at 1 am) will trigger anywhere between 1:00 am and
  1:59 am."
- https://vercel.com/docs/cron-jobs/manage-cron-jobs (`last_updated: 2026-08-11`): "Vercel will not retry an invocation
  if a cron job fails."; "Cron job delivery is best effort … your function does not execute, and no runtime log is
  created for that scheduled run."; "Cron delivery can also occasionally invoke the same scheduled run more than once.";
  "Design your operations to be **idempotent** and reconciliation-based …"; "Cron jobs do not follow redirects.";
  "We recommend using a random string of at least 16 characters"; "The `authorization` header will have the `Bearer`
  prefix".
- https://vercel.com/docs/cron-jobs: "The timezone is always UTC"; "You cannot configure both day of the month and day
  of the week at the same time"; `vercel-cron/1.0` user agent and `x-vercel-cron-schedule` header.

The IST conversions in §1.3 are arithmetically right (UTC+05:30).

## AUTO-2 — CONFIRMED (with a caveat on the strength of the host evidence)

Code facts, read in the repo:
- `backend/src/iip/api/settings.py:58-61`: in hosted mode `allowed_hosts` is exactly the `IIP_PUBLIC_ORIGIN` netloc,
  with the comment "a Vercel preview or deployment URL is refused".
- `backend/src/iip/api/security.py:251-254`: any other Host → `400 BAD_HOST`.
- `security.py:271-276` and `PUBLIC_ROUTES` (line 51, only `POST /api/session` and `GET /api/health`): any other `/api`
  route without a session cookie → `401 UNAUTHENTICATED`.
- ADR-0008 line 7: "GET requests have no side effects." ADR-0013 line 7: "a raw deployment URL is refused (400)".

So the headline ("every cron call would be refused") holds **even if the Host question resolves favourably**, because
the 401 is unconditional for a cookieless request. That is enough to confirm the finding.

Caveat on the host evidence:
- https://github.com/namphuongtran/familyroots/issues/265 (opened 2026-10-10) does say "Vercel Cron calls the
  deployment's own host, which ALLOWED_HOSTS refuses" and "The function log read `400`". But it is one third-party
  project, the 400 was from a **manual** `vercel crons run` per the search summary of its fix PR #266, and the raw Host
  header value is not shown in the issue.
- The Vercel doc's example `https://*.vercel.app/api/cron` does not discriminate: this project's production alias
  (`investment-intelligence-pro.vercel.app`) is itself a `*.vercel.app` host. The doc says "production deployment URL",
  which is ambiguous between the alias and the generated URL.
- The report already labels this NOT VERIFIED and proposes a live test. That is the right label.

## AUTO-3 — WEAKENED

What holds:
- The Vercel quote recommending idempotent, reconciliation-based jobs is verbatim (see AUTO-1).
- ADR-0013 does record single-statement claims, `DbLease` with a 330 s lapse (line 42) and resumable progress as
  verified building blocks.

Why it is weakened:
1. **Mislabelled status.** The finding is a *proposed design* (`cron_runs`, `signal_snapshots`, `notification_outbox`
   do not exist; no test has run). Only its building blocks are VERIFIED. Under the project's labels the design itself
   is NOT VERIFIED until built and tested.
2. **The claim SQL does not do what the prose says.** `ON CONFLICT(job, run_key) DO UPDATE … WHERE state IN ('failed')`
   cannot take over a stale `running` row, yet the next bullet says "A `running` row older than the lease TTL can be
   taken over". As written, a function killed mid-run leaves the (job, run_key) claim stuck forever. The WHERE needs a
   staleness predicate (e.g. `OR (state='running' AND started_at < :cutoff)`), with `:cutoff` computed in the service
   layer.
3. **Key contradiction.** The table comment says "One row per job per IST business date", §3 says "At most one claim
   per (job, IST date)", but §4 says `run_key` is the **data** as-of date, "NOT wall-clock 'today'". These are different
   keys with different duplicate behaviour; the report must pick one (the data-date key is the one consistent with the
   binding rules).
4. **Claim-before-know problem.** For J1 the data-date `run_key` is "the newest NAV date not yet stored", which is only
   known after fetching AMFI. Two duplicate deliveries therefore both fetch NAVAll before either can claim. Harmless for
   correctness, but the report's "duplicate delivery hits the PK" overstates the protection.
5. **Stuck outbox.** A crash after `state='sending'` leaves the row in `sending` with no reaper, so that snapshot is
   never pinged. The report accepts "loses at most one ping", but the watchdog (J5) should detect `sending` rows older
   than the lease TTL, otherwise the loss is silent.

## AUTO-4 — CONFIRMED

From https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows
(raw HTML grepped): "The `schedule` event can be delayed during periods of high loads of GitHub Actions workflow runs. If
the load is sufficiently high enough, some queued jobs may be dropped."; "In a public repository, scheduled workflows
are automatically disabled when no repository activity has occurred in 60 days."; "The shortest interval you can run
scheduled workflows is once every 5 minutes."

From https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs: "You must be logged in to a
GitHub account to view workflow run information, including for public repositories." and "Read access to the repository
is required to perform these steps." The report correctly marks "any logged-in user can read the logs" as an inference.

## AUTO-5 — CONFIRMED (minor caveats)

- Telegram, https://core.telegram.org/bots/faq: "By default, bots are able to message their users at no cost" and "In a
  single chat, avoid sending more than one message per second." CONFIRMED.
- Telegram, https://telegram.org/privacy: "Telegram is a cloud service. We store messages, photos, videos and documents
  from your cloud chats on our servers …" CONFIRMED.
- RFC 8291, https://www.rfc-editor.org/rfc/rfc8291 (line 18 of the text): "This scheme provides confidentiality and
  integrity for messages sent from an application server to a user agent." CONFIRMED.
- ntfy, https://docs.ntfy.sh/publish/: "Since there is no sign-up, **the topic is essentially a password**, so pick
  something that's not easily guessable." https://ntfy.sh/: Supporter tier lists "3 reserved topics"; "If you purchase
  ntfy Pro, you can reserve topic names instead." CONFIRMED.
- ntfy privacy, https://docs.ntfy.sh/privacy/: "Messages you publish are temporarily cached on our servers (default: 12
  hours)"; "Message metadata and content may be transmitted through Google's FCM infrastructure". CONFIRMED.
- Google, https://support.google.com/accounts/answer/185833: "App passwords aren't recommended and are unnecessary in
  most cases"; 2-Step Verification required; app passwords revoked on password change. CONFIRMED.

Caveats (not enough to weaken):
- "Web Push: no third-party account is needed" is true, but delivery still runs through the browser vendor's push
  service (Apple / Google / Mozilla), which sees metadata and timing even though RFC 8291 hides the payload. The report
  should say "no account", not imply no third party.
- The Telegram bot-developer ToS applicability is left NOT VERIFIED; I did not resolve it either.

## AUTO-6 — CONFIRMED with caveats

Quotas are quoted correctly:
- https://vercel.com/docs/plans/hobby (`last_updated: 2026-09-14`): Active CPU "4 CPU-hrs"; Function Invocations "First
  1,000,000"; "Vercel Function maximum duration | 300s (5 minutes)"; Runtime Logs "1 hour of logs"; "if you exceed your
  usage limits on the Hobby plan, you will have to wait until 30 days have passed"; "the Hobby plan restricts users to
  non-commercial, personal use only".
- https://turso.tech/pricing: Free "500 Million" rows read, "10 Million" rows written, "5GB", "1 day" PITR; "billed
  automatically once enabled".
- ADR-0013 line 8: "all 1,779 minimised-scope schemes in one 98 s call".

Caveats:
1. **Omitted meter.** The Hobby table also has **Provisioned Memory "360 GB-hrs"**, which is billed on wall time, not
   CPU time. The report argues sufficiency only from Active CPU. Rough check: 5 jobs × 30 days × ≤ 100 s × (memory size,
   NOT VERIFIED for this function) stays far below 360 GB-hrs even at 3 GB, so the conclusion survives, but the analysis
   is incomplete.
2. The CPU share of a NAVAll step was not measured (the report says so).
3. ADR-0013 line 52 records a 144 s step whose response never arrived (HTTP 000) with cause NOT VERIFIED. A cron step
   that overruns the 90 s budget (the 98 s NAVAll does) inherits that unexplained risk, and a cron has no human to retry.
4. Turso's site reportedly carries a notice that Turso is joining Supabase (search summary only, NOT VERIFIED). Free-tier
   terms may change; the System-page counter the report proposes is the right mitigation.

## AUTO-7 — WEAKENED

1. **Misattributed quote.** The finding's evidence cites NSE: "Commercial usage of the Data is forbidden". In
   `docs/data/source-registry.md` that sentence (line 231) belongs to **CCIL**'s Data Sharing Policy, not NSE. The NSE
   basis in the registry (§2.11, lines 238-241) is different: the ToU prohibits "systematic or automated data collection
   activities (including scraping …)", storage "without prior written permission of NSE", and use "for any gaming,
   virtual trading or simulation activities". The finding's summary "forbid redistribution and commercial use" therefore
   misstates the actual NSE restriction, which is stricter in a different way (automated collection and storage at all).
2. The BSE quote is from `bseindia.com/rgess/disclaimer.htm`; the registry itself says "the main-site terms are NOT
   VERIFIED".
3. **"BLOCKED until a lawful EOD equity source exists" is overstated as a near-permanent state.** It ignores broker
   APIs used under the user's own account:
   - https://upstox.com/trading-api/ (opened): "Yes! All trading + data APIs are free of cost." and "₹0 Free access to
     trading & market data APIs".
   - Angel One SmartAPI is reported free including historical candles (search summary only; source
     https://smartapi.angelbroking.com/faq, NOT VERIFIED by me).
   - The data licence/terms of these APIs (personal use, storage, redistribution) were **not read** and are NOT
     VERIFIED. They need a daily login/TOTP token, which conflicts with unattended cron on Vercel.
   Correct label: exchange-website scraping is BLOCKED; a broker-API EOD source is **REQUIRES CONFIGURATION / NOT
   VERIFIED (terms unread)**. Even with data, any buy/sell signal stays gated by the out-of-sample, cost- and tax-aware
   backtest rule.

---

## Important omissions

1. **AMFI terms vs hosted, scheduled storage.** The project's own `source-registry.md` (line 91) says "Treat any hosted
   or commercial deployment as **REQUIRES LICENCE / WRITTEN PERMISSION**." ADR-0013 accepted hosting under "personal
   use only", but the automation report adds unattended daily harvesting into Turso plus persisted `signal_snapshots`
   without reconciling either with the registry line. I re-read https://www.amfiindia.com/terms-of-use: it contains no
   clause against automated access (no "automat", "robot", "scrap" or "crawl"), but it does say "You shall not store
   electronically any significant portion of any part of the Site" and forbids creating "derivative works based on
   anything available through the Site". Whether a stored engine snapshot is a "derivative work" is a legal question
   (NOT VERIFIED; not legal advice). The report should record this tension and keep minimisation (tracked schemes only)
   for J1 as well as J3.
2. **Vercel Deployment Protection.** On Hobby, Vercel Authentication can protect production deployment URLs
   (https://vercel.com/docs/plans/hobby lists it). If cron really targets the generated deployment URL, protection
   could also intercept it. Vercel's cron GA changelog reportedly says cron "added support for Deployment Protection"
   (search summary only, NOT VERIFIED). The first live test (§6 step 4) must check this, not only the Host header.
3. **Stale-claim and stuck-outbox reaping** (AUTO-3 points 2 and 5) are missing from the test list.
4. **Provisioned Memory quota** (AUTO-6 point 1).
5. **Broker-API equity data route** (AUTO-7 point 3), which matters for the user's stated aim of equity buy/sell
   signals; it should be researched (terms, storage rights, unattended-login feasibility) rather than closed as BLOCKED.
6. **Cron cannot produce signals by itself.** The report is right that the automation layer only runs the gated engine,
   but it does not say plainly that, today, no backtest-approved signal exists, so the daily job will mostly store
   `ABSTAIN` / "No suitable candidate". Setting that expectation matters for the user's goal.
