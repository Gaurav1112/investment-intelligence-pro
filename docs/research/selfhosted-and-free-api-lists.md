# Screening: awesome-selfhosted and API-mega-list (2026-10-15)

The user suggested two lists. Each was screened against the binding constraints:
- authoritative sources only;
- no paid API keys;
- no scraping beyond what each source's terms allow;
- local, single-process, personal use;
- no AGPL code reuse;
- no LLM output becomes a number.

Status: **screened from each list's README at the 2026-10-15 snapshot.** Individual projects were **NOT VERIFIED** beyond what is
stated here.

## 1. awesome-selfhosted/awesome-selfhosted

Investment Intelligence Pro is already a self-hosted application: one local process, SQLite, bound to loopback. The list
holds services you run next to an app, not libraries to build into it. **Verdict: no new dependency adopted.**

| Entry (list section) | Relevance | Verdict |
|---|---|---|
| Ghostfolio (Money) | Already scored in `reference-selection.md` (69.0, row 11) | Ideas only, no code (AGPL-3.0). Its NestJS + Postgres + Redis stack is heavier than this app's single process. |
| Actual, Firefly III, Sure, Kresus, YAFFA (Money) | Budgeting and spend tracking | Out of scope: none of them is a decision engine for MF, T-bill, G-sec, bond or FD, and none applies Indian tax rules. |
| Fava / Beancount (Money) | Plain-text double-entry ledger | **Possible future export target** (a deterministic text format; only the format would be used, no code). Not implemented. |
| Ollama, LocalAI (GenAI) | Local OpenAI-compatible model servers | Already supported without code changes: ADR-0007 local mode accepts any loopback OpenAI-compatible `IIP_LLM_BASE_URL`. The LLM stays optional and never produces numbers. |
| Open-WebUI, AnythingLLM, LibreChat, Khoj (GenAI) | Chat front-ends | Not needed. They would add a second UI that does not enforce the supervisor and compliance gates. |
| Backup (redirects to awesome-sysadmin: restic, Borg, Kopia) | Off-machine copies | Optional for the user. `make backup-encrypted` already writes AES-256-GCM `.db.enc` files, so any sync or backup tool can copy them off the machine without seeing plaintext. |
| Monitoring (Uptime Kuma and similar) | Uptime checks | Not useful for an app that runs only while you use it. `GET /api/ready` exists for anyone who wants it. |

## 2. cporter202/API-mega-list

The README advertises 11,860 APIs. A host count of its links found **1,736 links to `apify.com`**, each with an affiliate
parameter (`?fpr=`). A keyword screen (finance, stock, mutual, India, NSE, BSE, RBI, bond, economy, inflation) returned
only paid "actor" scrapers of third-party sites:
- Google Finance;
- MarketWatch;
- Bankrate;
- "AI market intelligence" products.

No entry is an official Indian publisher (AMFI, RBI, CCIL, FBIL, MOSPI, NSE or BSE).

**Verdict: rejected for every data role.**
- **Paid:** they need an Apify account and token and are billed per use, which breaks the no-paid-keys rule.
- **Non-authoritative:** they re-scrape third-party pages, so provenance cannot be traced to the publisher. The source
  registry (`docs/data/source-registry.md`) requires the official publisher.
- **Terms:** they scrape sites whose terms prohibit it, which breaks the no-scraping constraint.
- **Not deterministic:** "AI sentiment" outputs are model opinions, and no LLM output may become a number.

## 3. Standing rule for "free APIs if needed"

A free API can be added to the registry only when all of these hold:
1. The publisher is the authority for the figure.
2. Its terms allow personal use and the minimised storage this app uses.
3. It needs no key, or a free key referenced by environment-variable **name**, as in ADR-0007.
4. It gets a probe recorded in `docs/data/probes/README.md` (findings and a synthetic shape sample, never the raw response), a strict parser and a source-registry row with a freshness SLO.

The sources the app already uses are all free and official:
- AMFI NAVAll and NAV history;
- RBI press releases (entered by the user);
- MOSPI CPI;
- the user's own CAS statements.

No gap found in this screening needs a new API.
