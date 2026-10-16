# Research: automation infrastructure (daily refresh, signal runs, notifications)

Wave 1 · research id `automation-infra` · written 2026-10-15 · every external claim was accessed on 2026-10-15.

Status labels: **VERIFIED** (read in a primary source today), **NOT VERIFIED** (no primary source found, or
inferred), **REQUIRES CONFIGURATION** (works once the user sets something up), **BLOCKED**.

## 0. Bottom line

1. **Vercel Cron on Hobby can run the daily pipeline, with care.** You can have up to 100 cron entries, but each one
   may run at most **once per day**, and Vercel fires it at some point **within the hour you name (±59 min)**. Each run
   is one ordinary function call (≤ 300 s; the app's own budget is 90 s per step). Vercel does not retry a failed run,
   it may skip a run, and it may deliver the same run twice. The pattern that fits is **several distinct daily jobs at
   different hours**, each one idempotent and doing "everything outstanding since the last success". All VERIFIED
   below.
2. **As the code stands, every cron call would be refused.** Vercel's cron calls the deployment's generated
   `*.vercel.app` host, and the app's Host allowlist returns `400 BAD_HOST` for that host. The cron would also hit the
   session check (401) and, being a GET, conflict with ADR-0008's "GET requests have no side effects". A narrow,
   separately authenticated `/api/cron/*` path is needed (§3). The host behaviour is NOT VERIFIED on this project and
   rests on a third-party report plus the Vercel docs' wording.
3. **GitHub Actions `schedule` works as a backup trigger, but should not be the main runner.** It is free for this
   public repo and can run every 5 minutes. On the other hand it is "best effort / may be dropped", it is disabled
   after 60 days without repo activity, and on a public repo its logs can be read by others. Running the job *inside*
   Actions would put the Turso token in GitHub and fetch AMFI from non-Indian IPs (NOT VERIFIED that AMFI answers
   there). Recommendation: no Actions in v1. Optionally add a *trigger-only* watchdog later.
4. **Notifications, without paid keys.** Use a **Telegram bot** in v1: free, one HTTPS call, and only the holder of
   the bot token can send. Treat **Web Push (VAPID)** as the privacy upgrade: the payload is end-to-end encrypted to
   your device and no third-party account is needed. Do **not** use ntfy.sh public topics (anyone who learns the topic
   can read it *and publish fake alerts*). Do **not** use a Gmail app password (Google says it is "not recommended" and
   it is a credential to your Google account). Whatever the channel, the message carries **no amounts, holdings,
   scheme names or buy/sell verbs**. It only says "a new report is ready, open the app" (§5).
5. **Signals stay gated.** The cron only *runs* the deterministic engine. It passes the data's own as-of date, never
   the wall clock, and it stores a snapshot whose result may be "abstain / no suitable candidate". The automation layer
   never creates a signal that the backtest gate has not already authorised. Equity (stock) buy/sell automation is
   **BLOCKED** until a lawful EOD equity source exists (source-registry: NSE/BSE terms forbid it). This report covers
   automating the AMFI/MF pipeline only.

---

## 1. Vercel Cron Jobs on Hobby

### 1.1 Limits and behaviour (all VERIFIED 2026-10-15)

| Fact | Quote | Source |
|---|---|---|
| Count | Hobby: "100 cron jobs" per project; minimum interval "Once per day"; precision "Per-hour (±59 min)" | https://vercel.com/docs/cron-jobs/usage-and-pricing |
| More than daily fails the deploy | "Hobby accounts are limited to daily cron jobs. This cron expression would run more than once per day." | same |
| Timing | "a cron job configured as `0 1 * * *` (every day at 1 am) will trigger anywhere between 1:00 am and 1:59 am" | same |
| Cost | "Cron jobs are included in **all plans**" … "usage and pricing limits for these functions apply to all cron job executions" | same |
| Trigger | "Vercel makes an HTTP GET request to your project's production deployment URL … `https://*.vercel.app/api/cron`" | https://vercel.com/docs/cron-jobs |
| UTC only | "The timezone is always UTC" | same |
| Identification | "will always contain `vercel-cron/1.0` as the user agent" plus an `x-vercel-cron-schedule` header | same |
| Auth | "The value of the variable [`CRON_SECRET`] will be automatically sent as an `Authorization` header" with "the `Bearer` prefix"; Vercel recommends "a random string of at least 16 characters" | https://vercel.com/docs/cron-jobs/manage-cron-jobs |
| Duration | "The duration limits for Cron jobs are identical to those of Vercel Functions" | same |
| No retries | "Vercel will not retry an invocation if a cron job fails." | same |
| Missed or duplicate runs | "Cron job delivery is best effort … your function does not execute, and no runtime log is created for that scheduled run." "Cron delivery can also occasionally invoke the same scheduled run more than once." | same |
| Overlap | "Vercel can trigger a second instance while the first is still running" — use a lock | same |
| Idempotency advice | "Design your operations to be **idempotent** and reconciliation-based so each run can safely reprocess outstanding work since the last successful run." | same |
| No redirects | "Cron jobs do not follow redirects … Redirect responses are treated as final" | same |
| Rollback | After an Instant Rollback, "your cron jobs are reverted to the state of the rolled-back deployment" | same |
| Hobby function limit | "Vercel Function maximum duration: 300s (5 minutes)" | https://vercel.com/docs/plans/hobby |
| Hobby quotas | Active CPU "4 CPU-hrs", Function Invocations "First 1,000,000", Runtime Logs "1 hour of logs" | same |
| Over quota | "if you exceed your usage limits on the Hobby plan, you will have to wait until 30 days have passed" | same |
| Personal use only | "the Hobby plan restricts users to non-commercial, personal use only" | same |

### 1.2 What this means for this app

- **Hour-level precision.** You can only choose the *hour* of each job. Choose hours so that even the worst case
  (end of the hour) still makes sense. A job that must follow another one goes ≥ 1 hour later, and a lease
  (`DbLease`, ADR-0013) still guards against overlap.
- **Budget.** The verified NAVAll run took 98 s in one call (ADR-0013). Note that this is above the current 90 s
  per-step budget; the budget is checked between blocks, so a step may overrun a little. The arithmetic on 30 runs
  a month:
  - 30 × ~100 s ≈ 50 min of *wall* time a month.
  - Active CPU is billed on CPU time, not on wall time. An I/O-bound ingest uses less CPU than its wall time, so it
    stays far below 4 CPU-hrs. The CPU share was not measured (NOT VERIFIED).
- **Logs.** Hobby keeps only 1 hour of runtime logs, and a missed cron run leaves no log at all. The app's own run
  ledger in Turso (`ingestion_runs` plus the new `cron_runs`, §4) is therefore the only durable record of what
  happened. Freshness is already computed at read time (reliability-design §5), so a dead scheduler cannot leave a
  "fresh" flag behind.
- **Resumable jobs fit.** Each NAVAll or backfill step is already resumable (`job_progress`). A cron call does one
  step. A later daily job continues if the run is not `done`, and does nothing if it is.

### 1.3 Proposed schedule (UTC → IST; Hobby fires anywhere in the hour)

AMFI deadlines (source-registry §2.1):
- NAVs for day T are due by **23:00 IST on T**.
- Fund-of-funds and overseas-heavy schemes are due by **10:00 IST on T+1**.

| # | `vercel.json` schedule | IST window | Job | Does nothing when |
|---|---|---|---|---|
| J1 | `0 1 * * *` | 06:30–07:29 | `navall` step: start a NAVAll run for the newest NAV date not yet stored | the newest stored NAV date already equals AMFI's newest |
| J2 | `0 2 * * *` | 07:30–08:29 | `navall` continuation (reconcile): finish an unfinished run | no run is open |
| J3 | `0 3 * * *` | 08:30–09:29 | `history` gap fill, one step, for **tracked/selected schemes only** (AMFI minimisation) | there is no gap |
| J4 | `0 5 * * *` | 10:30–11:29 | `navall` re-run for FoF/overseas late NAVs (supersede links already exist), then the **signal snapshot** (deterministic engine), then the **notification outbox** | a snapshot for (data as-of date, engine version, input hash) already exists |
| J5 | `0 13 * * *` | 18:30–19:29 | `watchdog`: if today's J4 snapshot is missing or a dataset is stale or broken, queue one "pipeline needs attention" ping | everything is fresh, or the same state was already notified |

- Five entries is far below the cap of 100. Do not use day-of-week fields; run daily and let the job check the
  business-day calendar itself, which also covers holidays.
- Vercel notes: "You cannot configure both day of the month and day of the week at the same time" (cron-jobs page).

---

## 2. GitHub Actions `schedule` as an alternative

| Fact | Quote | Status / source |
|---|---|---|
| Frequency | "The shortest interval you can run scheduled workflows is once every 5 minutes." | VERIFIED, https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows |
| Reliability | "can be delayed during periods of high loads" … "some queued jobs may be dropped" | VERIFIED, same |
| Inactivity | "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days." | VERIFIED, same |
| Branch | "Scheduled workflows run on the latest commit on the default branch" | VERIFIED, same |
| Timezone | can "optionally specify a timezone using an IANA timezone string" | VERIFIED, same |
| Cost | "GitHub Actions usage is **free** for … **public repositories** that use standard GitHub-hosted runners." Private repos on Free: 2,000 min/month | VERIFIED, https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions |
| Job limit | 6 hours per job on GitHub-hosted runners | VERIFIED, https://docs.github.com/en/actions/reference/limits |
| Secrets | "Secrets are automatically redacted from logs", but not when printed after transformation. "Mask all sensitive information that is not a GitHub secret by using `::add-mask::VALUE`" | VERIFIED, https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets |
| Log visibility | "You must be logged in to a GitHub account to view workflow run information, including for public repositories" and "Read access to the repository is required". Every logged-in user has read access to a public repo, so **any GitHub user can read the run logs** | Quote VERIFIED (https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs); the conclusion is an inference, NOT VERIFIED by a direct statement |
| Typical delay size | — | NOT VERIFIED (no official figure) |
| AMFI reachable from GitHub runner IPs | — | NOT VERIFIED (only `bom1` was probed) |

### Two ways to use it

**Option A: Actions as the worker.** Python runs in the runner and writes to Turso directly.
- Gains: no 300 s limit and a 5-minute minimum interval.
- Costs:
  - the Turso write token sits in GitHub as a second custody point;
  - the job's output lives in a **public** repo's logs;
  - AMFI is fetched from non-Indian IPs;
  - the job dies quietly after 60 idle days;
  - it duplicates the hosted code path (locks, leases, budget) that ADR-0013 already tested.
- **Not recommended.**

**Option B: Actions as a trigger only.** A step runs `curl -X POST -H "Authorization: Bearer $CRON_TRIGGER_SECRET"`
against `https://<production host>/api/cron/<job>`.
- It calls the production alias, so the existing Host allowlist already accepts it.
- The logs show only the HTTP status. The response body must contain counts and states only, and the workflow should
  print the status code alone.
- Use it as a **watchdog / second trigger** if Vercel cron proves unreliable. The same idempotent endpoint makes
  double triggering harmless.
- Keep in mind that the 60-day auto-disable makes it a poor *sole* scheduler for a repo you may not touch for months.
- **Optional, v2.**

**Recommendation:** Vercel Cron as the only scheduler in v1. Keep the endpoint method-agnostic (accept the Vercel
GET and an optional POST) so Option B can be added without a redesign.

---

## 3. Fitting cron into the existing security model (ADR-0008 / ADR-0013)

Current middleware (`backend/src/iip/api/security.py`), in order:
1. Host allowlist: exactly the `IIP_PUBLIC_ORIGIN` host, otherwise 400.
2. Body cap.
3. Session cookie on every `/api` route except `POST /api/session` and `GET /api/health`.
4. CSRF on state-changing methods.

**The problem, in three parts.**
- **Host.** A Vercel cron request arrives with `Host = <project>-<hash>-<scope>.vercel.app`.
  - Third-party evidence: "Vercel Cron calls the deployment's own host, which ALLOWED_HOSTS refuses", and its logs
    showed `responseStatusCode: 400`.
    https://github.com/namphuongtran/familyroots/issues/265 (opened 2026-10-10; accessed 2026-10-15).
  - Vercel documents `VERCEL_URL` as "The domain name of the generated deployment URL" and
    `VERCEL_PROJECT_PRODUCTION_URL` as "A production domain name of the project".
    https://vercel.com/docs/environment-variables/system-environment-variables.
  - Status: **NOT VERIFIED on this project.** First test: `vercel crons run` or the dashboard "Run" button, then read
    the status.
- **Session.** A cron call has no cookie, so it gets 401.
- **Method.** A cron call is a GET, while ADR-0008 says GETs have no side effects.

**Proposed narrow exception (new ADR-0014 "scheduled jobs").**
- **Route.** Only `GET|POST /api/cron/{job}`, where `job` belongs to a fixed set
  (`navall`, `navall-continue`, `history`, `snapshot`, `watchdog`). There are no parameters: the job decides what to
  do from the database state, never from the request.
- **Host.**
  - On this route only, accept `Host ∈ {public host, $VERCEL_URL}`.
  - Read `VERCEL_URL` at startup. If it is absent in hosted mode, the route answers 404 and everything else is
    unchanged.
  - Every other route keeps refusing deployment URLs.
- **Auth.**
  - Require `Authorization: Bearer <CRON_SECRET>`, compared with `hmac.compare_digest`.
  - `CRON_SECRET` must be ≥ 32 chars (the app's own token rule; Vercel's floor is 16), otherwise startup is refused
    if crons are enabled.
  - It must be **different from** `IIP_ACCESS_TOKEN`. A cron secret grants only "run a fixed job", never a session.
  - No cookie is set or read, and the user agent is not trusted (the familyroots issue and the Vercel docs both say
    UA and Host are not authentication).
- **CSRF.** Not applicable: the route uses no cookie and no ambient credential. A browser cannot attach the bearer
  header cross-site without CORS, and the app emits no CORS headers.
- **The "GET has no side effects" rule** is amended for this path only, and the reason is written down: the side
  effect is idempotent and authenticated by a secret header.
- **Rate limits.**
  - At most one claim per (job, IST date), plus continuation steps of an open run.
  - A wrong secret returns 401 and goes to `rate_hits` like login (10/min). This stops someone from brute-forcing the
    secret against the open deployment hostname.
- **Response.** Counts and states only (`{"job":"navall","state":"done","schemes":1779}`). Never amounts or holdings.
  The existing C-13 log policy applies.
- **Preview deployments.** Vercel runs crons only against production. The handler also refuses when
  `VERCEL_ENV != "production"`.
- **Status:** REQUIRES CONFIGURATION (`CRON_SECRET` in Vercel as a sensitive env var; `vercel.json` `crons`).

**Threat-model additions to log:**
- SEC-cron-1: a leaked cron secret lets an attacker trigger AMFI refreshes, which the claims cap; it cannot read data.
- SEC-cron-2: a host exception that leaks to other routes. Guard it with a test that every non-cron route still
  returns 400 on the `VERCEL_URL` host.
- SEC-cron-3: duplicate delivery, guarded by the idempotency keys in §4.
- SEC-cron-4: spoofed notifications, see §5.

---

## 4. Idempotent jobs into Turso

The building blocks already exist and are verified (ADR-0013):
- single-statement conditional claims (`refresh_claims`, `rate_hits`);
- `DbLease` with a 330 s TTL;
- resumable `job_progress`;
- batched `upsert_observations_batch` with supersede links;
- `ingestion_runs`.

Rule: **every cross-instance decision is one conditional statement.** Interactive remote transactions are still
NOT VERIFIED (ADR-0013 item 4).

Additions:

```sql
-- One row per job per IST business date: the claim. Duplicate delivery hits the PK and returns rowcount 0.
CREATE TABLE cron_runs (
  job        TEXT NOT NULL,              -- fixed enum
  run_key    TEXT NOT NULL,              -- e.g. data as-of date '2026-10-14', NOT wall-clock "today"
  state      TEXT NOT NULL CHECK (state IN ('claimed','running','done','noop','failed')),
  attempts   INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL, finished_at TEXT, detail_code TEXT,   -- codes only, no values
  PRIMARY KEY (job, run_key));

-- Engine output: immutable, content-addressed. Re-running with the same inputs writes nothing new.
CREATE TABLE signal_snapshots (
  snapshot_id    TEXT PRIMARY KEY,       -- sha256(engine_version || rules_version || input_manifest_hash)
  as_of_date     TEXT NOT NULL,          -- newest observation_date used, from the data
  engine_version TEXT NOT NULL, rules_version TEXT NOT NULL,
  verdict        TEXT NOT NULL,          -- e.g. 'ABSTAIN' | 'NO_SUITABLE_CANDIDATE' | 'REPORT'
  payload_json   TEXT NOT NULL,          -- engine result with per-number source/formula trace
  created_at     TEXT NOT NULL);

-- Outbox: at most one send per (snapshot, channel).
CREATE TABLE notification_outbox (
  snapshot_id TEXT NOT NULL, channel TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','sending','sent','failed')),
  updated_at TEXT NOT NULL, PRIMARY KEY (snapshot_id, channel));
```

How each job runs:
- **Claim.** `INSERT INTO cron_runs … ON CONFLICT(job, run_key) DO UPDATE SET attempts=attempts+1, state='running'
  WHERE state IN ('failed')`.
  - `rowcount 0` means another delivery owns the claim, or the job is already done, so return `noop`.
  - A `running` row older than the lease TTL can be taken over. This mirrors the existing cold-start rule.
- **Key on the data, not the clock.**
  - `run_key` is the AMFI NAV date the job targets, so a run that slips past midnight UTC is still the same run.
  - The engine gets `as_of` from the stored observations, which keeps `engine/` free of clock and IO (binding rule).
  - Only the service layer stamps `started_at`.
- **Reconciliation.** Each job computes the outstanding work: the newest AMFI date minus the newest stored date,
  plus open `job_progress`. A missed day is therefore caught up by the next run, as Vercel itself recommends.
- **Snapshot.** `INSERT … ON CONFLICT(snapshot_id) DO NOTHING`. Identical inputs give an identical id, so a duplicate
  is a no-op by construction.
  - An `ABSTAIN` verdict is stored too, so "the system ran and said no" is distinguishable from "the system did not
    run".
- **Outbox send.**
  - Claim with `UPDATE notification_outbox SET state='sending' WHERE … AND state='pending'`. Send only on
    `rowcount 1`, then mark it `sent`.
  - A crash between claim and send loses at most one ping. That is the safe direction: no duplicate "SELL"-style
    alerts, and nothing in a ping is actionable anyway.
- **Turso free plan.** VERIFIED (https://turso.tech/pricing): "500 Million" rows read, "10 Million" rows written,
  "5GB", "1 day" point-in-time restore. Overage is "billed automatically once enabled", so keep overages disabled.
  - Rough load: ~1,780 NAV rows a day ≈ 53k rows a month, plus progress and snapshot rows. That is about 1 % of the
    write allowance.
  - Exactly how Turso counts index writes is NOT VERIFIED, so add a monthly counter check on the System page.
- **Tests to add.** All are hermetic, with fake clock and fake fetcher, on both drivers:
  - a duplicate delivery of each job is a no-op;
  - two concurrent deliveries lead to exactly one owner;
  - a missed J1 is caught up by J2;
  - a crash mid-step resumes;
  - a snapshot is byte-identical on re-run;
  - the outbox sends once;
  - no route other than `/api/cron/*` accepts the `VERCEL_URL` host;
  - a wrong or missing bearer gives 401 and is rate-limited.

---

## 5. Notifications without paid keys

**Content policy, for every channel.** A notification is a **ping**, not a report:
- It may say: "IIP: daily report ready (data as of 14-Oct). Open the app." or "IIP: data pipeline needs attention."
- It must not carry amounts, holdings, scheme names, buy/sell verbs or target prices.
- Why:
  1. Every channel below stores content with a third party, or could.
  2. A spoofed ping can then only make you open the app, where the authenticated, traceable report lives.
  3. It keeps the C-13 "no personal values leave the app" rule.
- The app's fetcher allowlist (`backend/src/iip/data/fetch.py`, code-defined hosts) must gain exactly the
  notification host(s) chosen.

| Channel | Cost | Integrity (who can send) | Privacy (who sees content) | Terms / caveats | Verdict |
|---|---|---|---|---|---|
| **Telegram bot** | Free: "bots are able to message their users **at no cost**" (https://core.telegram.org/bots/faq); 1 msg/s per chat | Only the bot-token holder. HTTPS `https://api.telegram.org/bot<token>/sendMessage` with `chat_id`, `text`; `protect_content` is available (https://core.telegram.org/bots/api) | Not E2E: "Telegram is a cloud service. We store messages … from your cloud chats on our servers"; only secret chats are E2E (https://telegram.org/privacy) | Bot ToS: free sending "free of charge"; delete user data when no longer needed; a separate privacy policy if practices differ (https://telegram.org/tos/bot-developers). For a one-user personal bot this is minimal, and its exact applicability is NOT VERIFIED | **Recommended for v1** (cheapest to build; one HTTPS call; works on any phone) |
| **Web Push (VAPID)** | Free; no account: iOS web push needs no Apple developer membership: "You do not need to be a member of the Apple Developer Program" (https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/) | Only the holder of the VAPID private key, to your subscription | Payload encrypted to your device: RFC 8291 "provides confidentiality and integrity for messages sent from an application server to a user agent" (https://www.rfc-editor.org/rfc/rfc8291) | iOS: only for **Home Screen web apps** (iOS 16.4+, same WebKit post). Needs a service worker, a manifest, a subscription table, and a Python Web Push library (choice, licence and maintenance NOT VERIFIED). The push-service endpoint hosts must go on the fetcher allowlist (exact host list NOT VERIFIED) | **Recommended v2** (best privacy; more build) |
| **ntfy.sh (public server)** | Free without sign-up (https://ntfy.sh/); the free tier's exact limits are not shown on the page (NOT VERIFIED) | **Anyone who knows the topic**: "the topic is essentially a password" (https://docs.ntfy.sh/publish/). Anonymous topics are readable *and writable* by whoever guesses them, so fake alerts can be injected. Reserved (access-controlled) topics are listed only on paid tiers (Supporter "3 reserved topics") | "Messages you publish are temporarily cached … (default: 12 hours)"; "Message metadata and content may be transmitted through Google's FCM infrastructure" (https://docs.ntfy.sh/privacy/) | Self-hosting fixes the integrity issue but needs a server, which this project does not have | **Not recommended** (spoofable; content transits FCM) |
| **Gmail SMTP + app password** | Free; Gmail cap "more than 500 emails sent in a day" is an error (https://support.google.com/mail/answer/22839) | Your own account | Stored in your mailbox at Google | Google: "App passwords aren't recommended and are unnecessary in most cases"; an app password "gives a less secure app or device permission to access your Google Account"; requires 2-Step Verification; all app passwords are revoked on a password change (https://support.google.com/accounts/answer/185833). That puts a Google-account credential in Vercel env. Outbound SMTP (465/587) from Vercel functions is NOT VERIFIED | **Not recommended** (credential blast radius far larger than the job) |

**In-app first, regardless.** The authoritative channel is the app itself:
- a "Today" card shows the latest `signal_snapshots` row, its verdict, its as-of date and the freshness banners;
- a ping only points there.

If the user picks no channel, nothing breaks: the report simply waits in the app.

---

## 6. Recommended design (single user, consistent with ADR-0008/0013)

```
Vercel Cron (UTC, daily, ±59 min)            Turso (libSQL)
 J1 01h navall ─┐                             cron_runs (claim per job×data-date)
 J2 02h cont.   ├─► GET /api/cron/{job} ──►   job_progress / leases (existing)
 J3 03h history │   Host ∈ {public, VERCEL_URL}   observations (batched upsert)
 J4 05h snapshot├─► Bearer CRON_SECRET (≠ access token)  signal_snapshots (content-addressed, may be ABSTAIN)
 J5 13h watchdog┘   VERCEL_ENV=production only     notification_outbox (send-once)
                    one ≤90 s step, idempotent ──► Telegram sendMessage (v1) / Web Push (v2): ping only
```

1. ADR-0014 "scheduled jobs" records the cron route, the host exception, the secret, the GET amendment and the
   outbox semantics.
2. `vercel.json` gets the `crons` array (§1.3). `CRON_SECRET` is a sensitive env var.
3. The cron route, the claim tables and the tests in §4. Do this before turning crons on.
4. First live check, recorded in known-limitations:
   - press "Run" in the dashboard;
   - confirm the Host value received;
   - confirm a `200 noop` on the second press;
   - confirm a `cron_runs` row.
5. Notifications: the Telegram adapter behind `IIP_NOTIFY=telegram|webpush|off` (default `off`), with
   `IIP_TELEGRAM_BOT_TOKEN` and `IIP_TELEGRAM_CHAT_ID` as sensitive vars. A test enforces the ping-only text template
   (sentinel amounts never appear; reuse REL-62).
6. Optional later:
   - GitHub Actions trigger-only watchdog (§2, Option B);
   - Web Push.

What this does **not** do:
- It does not create signals. The J4 snapshot only runs engine functions whose backtest gate is satisfied, and
  otherwise stores `ABSTAIN`.
- It does not touch equities (BLOCKED on data terms).
- It does not widen data storage beyond the AMFI minimisation already in place.

## 7. Open items (NOT VERIFIED until tested live)

- The Host header of a scheduled (not manual) Vercel cron call on this project.
- Whether a 98–100 s NAVAll step via cron behaves like the same step called from the UI (same function, so expected
  yes).
- Turso's row-write accounting for indexed tables.
- Whether AMFI answers from GitHub runner IPs (relevant only to Option A, which is not recommended).
- The Web Push library choice and the push-service host list.
- Whether Telegram's bot-developer ToS clauses apply to a private one-user bot.
