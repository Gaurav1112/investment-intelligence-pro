# Investment Intelligence Pro — Requirements (Phase 0)

Status: DRAFT v0.1 · Written 2026-10-15 · Owner: project developer (single user, self-hosted)

This document separates what is **confirmed**, what is **assumed**, what **needs the user's decision**,
what **needs external services**, and what **needs professional (legal/tax) review**. Research documents
referenced here are produced in Phases 1–3 and may revise items marked *pending research*.

---

## 1. Environment discovered (Phase 0 audit)

| Item | Finding | Consequence |
|---|---|---|
| Existing app for this purpose | None. `~/PersonalProject/nse-trading-lab` is an equity swing-trading/backtesting Streamlit tool (yfinance, MTF tracker, GO/WAIT/AVOID verdicts). | Not modified. Different goal (trading signals) from this product (horizon-matched wealth decisions). Its Zerodha cost model and look-ahead guards are noted as internal prior art only. |
| Runtimes | Node 24.15 (Volta), pnpm 10.28 (runs under Node 20 via Volta — native addons segfault through `pnpm <script>`), Python 3.12.13 (uv-managed), 3.13, 3.14; uv 0.11; Go 1.25; Docker 29; SQLite 3.43; PostgreSQL 14 client. | Avoid Node native DB addons; run JS scripts with `node --run`. Python 3.12 via uv is the safest target for scientific wheels. |
| Disk | ~17 GB free of 460 GB (96 % used). | No large clones, no heavy images; keep dependencies lean. |
| GitHub CLI | Authenticated. | Repository statistics are gathered from the GitHub API with dates, never estimated. |
| Standing user preferences (from prior sessions) | Build, not buy. No paid AI API keys; any AI must be vendor-neutral, optional and local, with a deterministic fallback. Code stays local (no push) unless asked. | The "AI research assistant" is optional. Every v1 research role is deterministic. A local OpenAI-compatible LLM boundary may be defined but nothing depends on it. |

## 2. Product statement

A self-hosted research workbench for an Indian resident investing in INR. It helps the investor compare options for a
**specific amount and withdrawal date** (1, 3, 6, 12 months; longer for comparison) against **explicit objectives and
constraints**. Every number comes from a deterministic, versioned engine and from source-dated data.

It does not promise returns. It does not execute transactions. It is allowed to answer:

> **No suitable candidate found under the current constraints.**

## 3. Confirmed requirements (from the brief)

### 3.1 Investor objectives — treated as distinct modes, never collapsed into "max return"

| Code | Objective | Primary success measure | Dominant risks considered |
|---|---|---|---|
| A | Capital preservation | Probability/size of nominal loss at the withdrawal date ≈ 0 under stated assumptions | Credit, mark-to-market, liquidity, early exit |
| B | Predictable income / maturity proceeds | Dispersion of proceeds at the target date | Reinvestment, credit, call |
| C | Liquidity / emergency reserve | Time and cost to cash, and value stability | Exit load, settlement lag, gating/side-pocketing |
| D | Risk-adjusted growth | Downside-aware outcome bands after costs and taxes | Drawdown, volatility, regime |
| E | Aggressive growth (explicit downside acceptance) | Upside, with a user-acknowledged loss budget | Large drawdowns, horizon mismatch |

### 3.2 Minimum suitability inputs

The application collects these before producing any *personalised* ranking:

1. Investable amount (INR, > 0).
2. Required withdrawal date (or horizon).
3. Whether a nominal principal loss is acceptable, and up to how much (amount or %).
4. Whether the funds may be needed early (probability or "possible / unlikely").
5. Liquidity requirement (maximum days to cash, and maximum exit cost).
6. Existing holdings and concentration (optional; manual entry or file import).
7. Tax circumstances (optional): regime (new/old), marginal slab, surcharge band, residential status.
8. Preferences and restrictions (excluded categories/issuers, minimum credit rating, exclusion of NBFC deposits, and so on).

**Rule:** if any of inputs 1–5 is missing, the app shows **exploration mode**: general comparisons using clearly labelled
illustrative defaults, with no ranking framed as suited to the user. Missing tax data means pre-tax figures, plus after-tax figures
shown only under labelled *assumed* tax profiles.

### 3.3 Horizons

Horizons of 1M, 3M, 6M and 12M are first-class. 2Y, 3Y and 5Y are shown for comparison only. Returns for holding periods under one year are
shown as **absolute returns**. Annualised figures appear only as secondary values with a visible caveat.

### 3.4 Functional scope (v1 target)

The brief's pages 1–16. Each page has real functionality and real loading, empty and error states. The deterministic
engine, data provenance and testing come before visual polish.

### 3.5 Non-negotiables carried as acceptance criteria

- No fabricated market data. Development fixtures are labelled `FIXTURE — not market data` everywhere they render.
- Every material observation carries provenance: source, retrieval timestamp, observation date, currency/unit, quality status and convention.
- Stale or missing data disables the claims that depend on it, and the UI says so.
- Rankings are deterministic. Identical versioned inputs give byte-identical outputs. Every ranking decision carries an explanation.
- No real-money transactions, no brokerage links, and no storage of bank or broker credentials.
- No claims of regulatory approval, registration or compliance.
- Status labels used throughout the delivery documents: VERIFIED / IMPLEMENTED, NOT VERIFIED / REQUIRES CONFIGURATION / BLOCKED.

### 3.6a Binding principle: deterministic supervisor, no hallucination (user directive, 2026-10-15)

> "We will be using supervisor approach to make sure every context is gathered; making it deterministic will make sure there
> are no hallucinations, as there is real money."

Every research or decision flow runs under a **Supervisor**, and the Supervisor is **deterministic code, not an LLM**.

1. **Context manifest.** Each question type declares its required context before any work starts. Example for "Compare options for
   ₹X over 6 months": suitability inputs complete; NAV or yield observations for each candidate within their freshness SLO;
   expense, exit-load and tax-rule versions; credit rating with date (bonds); risk-free rate observation; data-quality status. Each item
   carries `required | optional`, a freshness rule and acceptable sources.
2. **Dispatch and contract validation.** The Supervisor runs specialist workers (Market Data, MF Research, Fixed Income, Macro,
   Quant, Portfolio Risk, Forecast Validation, Skeptic, Compliance). Each returns a schema-validated contract: claims, evidence,
   source id/URL, observation date, gaps, conflicts, requested calculations. Contracts that fail validation are discarded and logged.
3. **Completeness gate.** Synthesis runs only when every `required` manifest item is present, fresh and provenance-complete.
   Otherwise the result is **ABSTAIN**, listing exactly which context is missing or stale. The Supervisor never fills gaps with
   defaults, interpolation or model output.
4. **Number provenance.** Every number displayed must trace to (a) a deterministic engine calculation with a recorded
   input hash and engine version, or (b) a dated source observation. Text from any optional LLM is scanned: a number not found in
   the provided facts causes the text to be rejected and replaced with the deterministic template.
5. **Conflict surfacing.** Material disagreement between workers (e.g., Skeptic finds a rating downgrade the MF agent did
   not cite) is shown to the user, not resolved silently.
6. **Reproducibility.** The run record (manifest, contracts, engine versions, input snapshot hash, output hash) is stored. Re-running
   it must give byte-identical output.

### 3.6 User-stated return aspiration (2026-10-15)

The user's stated aim is **"at least 20–25 % gain every year or even more."**

How the product treats it, so that it is neither ignored nor allowed to drive reckless ranking:

- It is recorded as an **aspiration**, not a constraint the engine optimises for. Ranking never selects an option *because*
  its historical return exceeded 20 %.
- A deterministic **Return-Target Feasibility** analysis (spec: `docs/research/return-target-feasibility.md`, *pending research*)
  shows, for each category or instrument with adequate history:
  - the historical frequency of meeting the target over rolling 1/3/5-year windows;
  - the outcome distribution;
  - drawdowns experienced along the way;
  - the frequency of loss.
  Labels say "historical frequency", never "probability of success".
- Targets that are incompatible with the chosen objective and horizon (e.g. 20 % p.a. with capital preservation over 3 months) are
  flagged as a **constraint conflict**, with the trade-off spelled out. They are not silently accepted.
- Pursuing such a target maps to objective **E (aggressive growth)**. That objective requires an explicit, user-entered loss
  budget before any ranking.

## 4. Reasonable implementation assumptions (changeable; recorded as ADRs)

| # | Assumption | Rationale |
|---|---|---|
| A1 | Single user, localhost deployment; the operator is also the investor. | Matches the stated personal use. Limits the regulatory and privacy surface (see regulatory-readiness.md). |
| A2 | Market = India, currency = INR, time zone = Asia/Kolkata for observation dates, UTC for retrieval timestamps. | Brief default. |
| A3 | Mutual fund data from AMFI's published NAV files is the v1 live source. Other data sources are manual or curated imports with dated citations. | *Pending Agent E research.* |
| A4 | Money uses Python `Decimal`. Statistics use float64 and are quantised at the boundary. | Brief Phase 5. |
| A5 | Tax rules are a dated, versioned table with source URLs. The user can override them. A Chartered Accountant review is flagged. | *Pending Agent B research.* |
| A6 | The AI layer is optional and off by default. The research "agents" are deterministic evidence-contracted modules that work fully without any LLM. Prose explanation goes through **one OpenAI-compatible adapter** (`base_url`, `model`, optional key from env). Supported provider classes: (1) **local** — Ollama, LM Studio, llama.cpp: default when enabled, $0, data never leaves the Mac; (2) **free-tier cloud** — e.g. Groq, Gemini, Mistral, Cerebras, NVIDIA NIM, OpenRouter free models, as catalogued by `open-free-llm-api/awesome-freellm-apis` (4,229★ @2026-10-15, MIT, refreshed daily): opt-in per provider. Cloud providers receive only a **redacted evidence packet** (no amounts, holdings, tax profile or identity). Many free tiers may use prompts for training, so each provider entry records its data-use terms (verified at configuration time). Free-tier rate limits are handled with caching and graceful fallback to the deterministic writer. No LLM output is ever parsed into a number. | User preference: no paid API keys, vendor-neutral. Free tiers remove the cost concern but not the privacy concern; redaction and local-first defaults address it. |
| A7 | Portfolio holdings are entered manually or imported from CSV. CAS PDF import is deferred. | It avoids handling statement passwords in v1. |
| A8 | Bind to 127.0.0.1 **and** require a **mandatory** 256-bit local access token, exchanged for a session cookie. Also enforce a Host+port allowlist (DNS-rebinding defence), CSRF header + Origin checks, and same-origin SPA (no CORS). A multi-user deployment would require full authentication (ADR). | Revised 2026-10-15 per `docs/security/threat-model.md`. A loopback bind alone does not stop DNS-rebinding or CSRF attacks from a malicious web page in the user's browser. |

## 5. Decisions that require user input (defaults chosen so work proceeds)

| Decision | Default used | Why it is the user's call |
|---|---|---|
| Will this ever be offered to other people (free or paid)? | **No — personal use only.** | Changes the regulatory posture materially (SEBI IA/RA). |
| Tax regime, slab, surcharge band | Not stored; after-tax figures shown under illustrative profiles. | Personal data. |
| Whether to enable an optional local LLM (Ollama/LM Studio) for prose explanations | Disabled. | Preference and hardware. |
| Licensed market data (paid feeds for bonds/equities) | Not used. | Cost and terms. |

## 6. Capabilities that require external services

| Capability | Requires | v1 status (expected) |
|---|---|---|
| Daily MF NAV | AMFI public files | REQUIRES CONFIGURATION (network fetch on the user's machine) |
| Historical NAV series | AMFI historical report or unofficial mirror | *Pending research* |
| T-bill / G-sec yields and auction results | RBI / FBIL / CCIL publications | *Pending research* — likely manual or curated import |
| Corporate bond prices, ratings | Exchanges, rating agencies (licensing) | Likely BLOCKED for live data; manual entry |
| CPI inflation | MoSPI | *Pending research* |
| FD rates | Bank websites (no central API) | Manual entry with a dated citation |
| Holdings import from CAS | CAMS/KFintech statements | Deferred |

## 7. Questions requiring professional review

1. Whether any planned feature amounts to "investment advice" or a "research report" under SEBI regulations if the tool is ever shared (Agent K).
2. Correctness of the tax treatment of debt MFs (Sec. 50AA / "specified mutual fund"), T-bill discounts and listed vs. unlisted bonds under the law in force on the analysis date, including the Income-tax Act 2025 transition (Agent B, CA review).
3. Redistribution limits of AMFI, NSE/BSE, FBIL and CCIL data (Agent E).
4. DPDP Act obligations if more than one person's data is ever processed (Agent K).

## 8. Out of scope for v1

Derivatives, leverage, crypto/tokens, intraday trading signals, order execution, brokerage or bank linking, social features,
paid advice, and automated portfolio changes.
