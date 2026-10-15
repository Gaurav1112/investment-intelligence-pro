# Investment Intelligence Pro: UX and Visual Design

Status: DRAFT v0.1 · Written 2026-10-15 · Author: Agent G (Product Designer) · Depends on: `docs/product/requirements.md`

Scope: design principles, information architecture for 16 pages, wireframes for 5 key pages, visual system, interaction
patterns, banned anti-patterns, and the recommended component and charting stack. Library statistics were taken from the GitHub
API and npm on 2026-10-15. Notes on competitor products describe public-facing patterns and are design observations, not audited
claims. They must be checked again before anyone quotes them.

Status labels follow the requirements doc: nothing in this document is IMPLEMENTED. It is a specification.

---

## 0. Research summary (what we borrow, what we refuse)

### 0.1 Indian investing products

| Product | Worth borrowing | Where risk is hidden or flattened |
|---|---|---|
| **Zerodha Coin / Kite** | Calm, low-chrome layouts. Restrained colour. Fast keyboard-first search (Kite's `/` and instrument search). Varsity explains concepts in long-form plain language. | Coin fund pages lead with the trailing return number. Risk sits lower down as the SEBI riskometer image. Kite's red and green P&L depends on colour alone. |
| **Groww** | Very low friction to "understand in one screen". Simple return calculators. | The headline is the annualised return, and the horizon chip sits next to it. A short-term liquid or overnight fund can show a big annualised figure. The "Invest" CTA is the visual anchor, not the risk. Calculators project a single point, for example "₹X in 5 years at 12 %". |
| **Kuvera** | Tax-aware views (LTCG harvesting). Goal-linked framing. Family portfolio. | Goal projections use a single assumed rate, with no band. |
| **Value Research** | Dense, honest tables. Category-relative ranks. Long return histories. The star rating discloses its methodology. | Star ratings are read as forward-looking quality signals even though they are backward-looking. Stars are the most prominent element. |
| **Morningstar India** | Separates the backward-looking Star Rating from the forward-looking Medalist Rating. Methodology documents are linked. Portfolio X-ray. | Ratings are still a single glyph that compresses uncertainty. |
| **INDmoney** | Net-worth aggregation. Clean cards. | Aggregation plus "insights" can feel like personalised advice without the suitability inputs behind it. Gamified streaks. |
| **Tickertape** | Screeners with saved filters. "Scorecard" chips. Peer comparison. | Scorecard chips such as "High / Low" coloured red and green read as verdicts and hide how they were computed. |
| **RBI Retail Direct** | Direct access to the primary auctions for T-bills and G-secs. Shows the auction calendar and cut-off yields. | Sparse UI. Price and yield conventions such as discount yield vs YTM, and clean vs dirty price, are left to the user. Mark-to-market risk on a dated G-sec held to before maturity is not shown. |

**Pattern we copy:** Value Research density, Morningstar's separation of "past" from "forward", Zerodha's restraint and
keyboard search, and RBI RD's auction calendar.
**Pattern we refuse:** a return number as hero, colour-only P&L, single-point projections, glyph ratings as verdicts, and
the CTA as anchor. We have no CTA, because we never transact.

### 0.2 Global research tools
- **Koyfin**: dense, customisable dashboards. Every chart has a visible source and as-of date. Keyboard command palette. Model: information density that is still readable because it uses strict typographic hierarchy and tabular numerals.
- **Portfolio Visualizer**: shows its full input set next to every result and lets you change one input and rerun. The output always echoes the assumptions. We copy the **echoed-assumptions header**.
- **Bloomberg-style density**: we copy the *density* and *keyboard primacy*, but not the colour-on-black UI or the cryptic mnemonics. Everything has a visible label, and the shortcut is a secondary affordance.
- **Linear / Stripe craft**: 4-px spacing grid, one accent colour, real focus rings, motion of 120 to 200 ms used only to show cause and effect, and empty states that teach. Stripe's documentation shows how to present a formula or code next to prose, and our "explain this number" drawer follows it.

### 0.3 Risk-communication research
- **Kay, Kola, Hullman and Munson, "When (ish) is my bus?" (CHI 2016)**: quantile dot plots, where each dot is a fixed 5 % (or 2 %) probability. They reduced the variance of probability estimates compared with density plots. **Fernandes et al. (CHI 2018)**: quantile dot plots and CDFs both beat text and intervals for decisions. → Our default outcome display is a **20-dot or 50-dot quantile dot plot of proceeds at the withdrawal date**.
- **Padilla, Kay and Hullman, "Uncertainty Visualization" (2020/2022)**: interval plots and error bars are prone to *deterministic construal*, meaning readers treat the edge as a hard limit. Frequency framing helps. → Intervals are always paired with a frequency statement ("in 3 of 20 historical windows…"). We never show a bare ± bar.
- **Fan charts** (Bank of England inflation fan): good for paths over time, but readers anchor on the central line. → The central line is drawn thinnest. Band labels are on-chart, not in a legend.
- **Hypothetical outcome plots (Hullman, Resnick and Adar 2015)**: an optional animated mode in the Scenario Lab. It is off by default and respects `prefers-reduced-motion`.
- **SEBI MF advertisement rules (Master Circular, performance para)**: CAGR for 1/3/5 years and since inception, point-to-point on ₹10,000, simple annualised for schemes 6 to 12 months old, and simple-annualised 7/15/30-day yields allowed for overnight, liquid and money-market funds. **Our product is stricter than the advertisement floor:** under 1 year we show absolute returns as the primary figure (requirements §3.3). The 2026-03-20 Master Circular refresh must be checked for paragraph numbers before we cite it in the UI.
- **FCA COBS 4.6.2R**: past performance must not be the most prominent feature. It must cover complete 12-month periods (up to 5). The reference period and source must be stated. It must carry a prominent "not a reliable indicator" warning. Fees must be disclosed when figures are gross. → We adopt all of these as product rules, even though we are not a financial promotion.
- **SEBI Potential Risk Class (PRC) matrix**, effective 2021-12-01: a 3×3 grid of credit risk (A to C, by Credit Risk Value) × interest-rate risk (I to III, by Macaulay duration). It shows the *maximum* risk a scheme *may* take. The riskometer is portfolio-based and monthly. → We show both, labelled as what they are: "regulatory ceiling" vs "AMC-reported current".

---

## 1. Design principles

1. **Polish must never create an illusion of certainty.** Every visual refinement (smooth curves, big confident numerals, a
   reassuring colour) is checked against one question: *does it make this number look more known than it is?* If it does, it is
   removed or paired with its uncertainty at equal visual weight.
2. **Distribution first, point second.** A forward-looking figure is shown as a range or distribution before any single number.
   The median, if shown, is never larger or bolder than the band around it.
3. **Every number is clickable to its evidence.** Every material figure opens the *Explain this number* drawer (§5.1). A figure
   that cannot be explained is not shown.
4. **Freshness is part of the number.** An observation date and a freshness badge (§4.4) travel with a value. Stale data
   disables dependent claims and does not silently fall back.
5. **"No suitable candidate found" is a first-class, well-designed result.** It gets the same care as a hit list. It is never
   an empty table.
6. **Horizon and objective are always visible.** The active amount, withdrawal date and objective (A to E) sit in a persistent
   context bar. No ranking appears without them, except in labelled exploration mode.
7. **Absolute before annualised.** Under 12 months, absolute return and ₹ proceeds are primary. Annualised figures are secondary and
   carry a caveat.
8. **Never colour alone.** Direction, risk and freshness are always encoded twice: text plus a glyph or position, plus colour.
9. **Density with hierarchy, not decoration.** Dense tables and small multiples are fine. Gauges, 3-D, gradients-as-meaning and
   ornamental charts are not.
10. **Keyboard is a first-class input.** Every action is reachable without a pointer. Shortcuts are labelled in-place.
11. **The tool informs; the investor decides.** No "Buy" or "Invest" CTA, and no imperative verdicts ("You should…"). Rankings say
    "ranks highest under your stated constraints", never "best".
12. **Fixtures are loud.** Development fixture data is unmistakable in every render (hatched background and a `FIXTURE` badge),
    including in screenshots and exports.

---

## 2. Information architecture

### 2.1 Global shell

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ ◧ IIP   [⌘K Search instruments, pages, actions]           Data: ● EOD 14-Oct  ⚙  ?    │  ← top bar
├───────────────────────────────────────────────────────────────────────────────────────┤
│ CONTEXT  ₹5,00,000 · withdraw 15-Apr-2027 (6M) · Objective A Capital preservation     │  ← persistent context bar
│          Loss tolerance: none · Early need: possible · Mode: PERSONALISED   [Edit]     │    (EXPLORATION in amber)
├────────────┬──────────────────────────────────────────────────────────────────────────┤
│ Decide     │                                                                          │
│  Overview  │                          page content                                    │
│  Discovery │                                                                          │
│  Compare   │                                                                          │
│  Scenarios │                                                                          │
│  Simulator │                                                                          │
│  Risk      │                                                                          │
│ Research   │                                                                          │
│  MF        │                                                                          │
│  Fixed inc.│                                                                          │
│  Watchlist │                                                                          │
│  Alerts    │                                                                          │
│ Trust      │                                                                          │
│  Evidence  │                                                                          │
│  Method    │                                                                          │
│  Data hlth │                                                                          │
│ ─────────  │                                                                          │
│  Settings  │                                                                          │
└────────────┴──────────────────────────────────────────────────────────────────────────┘
```

The navigation groups follow user intent: **Decide** (the goal-bound flow), **Research** (open-ended browsing) and **Trust** (why
believe any of it). Onboarding is a full-screen flow outside the shell, and you can re-enter it from the context bar's [Edit].

### 2.2 Page inventory

| # | Page | Route | Primary question it answers | Key content | Mode behaviour | Primary links out |
|---|---|---|---|---|---|---|
| 1 | Onboarding & objectives | `/onboarding` | "What am I trying to do with this money?" | 5-step wizard: amount → date → objective A–E → loss tolerance and early-need → liquidity → optional: holdings, tax, restrictions | Writes the suitability profile. Skipping any of steps 1–5 → exploration mode | Discovery |
| 2 | Portfolio overview | `/` | "What do I hold, and does it fit my horizons?" | Holdings table, allocation by instrument type, credit and duration profile, horizon-mismatch flags, freshness summary | Without holdings: empty state that teaches CSV import | Risk analysis, Instrument detail |
| 3 | Discovery | `/discover` | "Which instruments fit this amount, date and objective?" | Echoed assumptions, ranked candidates with outcome bands, exclusion ledger, "no suitable candidate" state | Exploration: unranked, grouped by category, illustrative defaults labelled | Instrument detail, Compare |
| 4 | MF explorer | `/mf` | "Browse and filter mutual fund schemes" | Screener table (category, plan, AUM, TER, exit load, PRC cell, riskometer, absolute returns for 1/3/6/12M), saved filters | Same in both modes. Not ranked for the user | Instrument detail |
| 5 | Fixed-income explorer | `/fi` | "Browse T-bills, G-secs, SDLs, corporate bonds and FDs" | Tabs per type. Yield with convention label (discount / YTM / FD compounding), maturity, rating with agency and date, auction calendar | Same in both modes | Instrument detail |
| 6 | Instrument detail | `/i/:id` | "Everything about this one instrument" | Identity and provenance header, horizon outcome panel, past-performance table (complete periods), costs, tax, liquidity, risk, documents | Personalised: outcome for the user's amount and date. Exploration: for ₹1,00,000 illustrative | Compare, Scenario lab, Evidence |
| 7 | Comparison | `/compare?ids=` | "How do 2–4 options differ on what matters for my goal?" | Aligned columns, row-wise differences, outcome dot plots on one shared axis, "what would change the order" | Same, with the illustrative amount in exploration | Instrument detail, Scenario lab |
| 8 | Scenario lab | `/scenarios` | "What happens under rate, credit, inflation or early-exit shocks?" | Scenario presets and custom shocks, before/after proceeds bands, sensitivity tornado | Works in both modes | Explain drawer, Methodology |
| 9 | Portfolio simulator | `/simulate` | "If I split the amount like this, what range of proceeds?" | Allocation editor (sums to 100 %, ₹ exact), outcome distribution, liquidity ladder, concentration warnings | Requires amount and date. Otherwise prompts for them | Scenario lab |
| 10 | Risk analysis | `/risk` | "Where am I exposed?" | Credit, duration, issuer concentration, liquidity ladder, horizon mismatch, drawdown history | Needs holdings or a simulator draft | Instrument detail |
| 11 | Watchlist | `/watchlist` | "Track candidates I'm considering" | Table with freshness, change since added (absolute), notes | Same | Instrument detail, Alerts |
| 12 | Alerts | `/alerts` | "Tell me when something material changes" | Rules (rating action, yield crosses X, NAV data stale, auction result published), local-only delivery log | Same. Local notifications only | Watchlist, Data health |
| 13 | Evidence / source viewer | `/evidence/:obsId` | "Where exactly did this value come from?" | Raw source excerpt, URL, retrieval timestamp (UTC), observation date (IST), checksum, parser version, quality status, lineage graph | n/a | Data health, Methodology |
| 14 | Methodology | `/methodology` | "How is every metric computed?" | Versioned formula pages, assumptions, limitations, changelog, engine version | n/a | Explain drawer deep links |
| 15 | Settings & privacy | `/settings` | "What is stored, and how do I control it?" | Profile, tax profile (optional), stored data inventory, export and delete, theme, density, number format, optional local LLM (off) | n/a | Onboarding |
| 16 | Data health | `/data-health` | "Can I trust today's data?" | Per-source status, last success, next scheduled run, stale and missing counts, claims currently disabled because of data gaps | n/a | Evidence |

### 2.3 Cross-cutting objects
- **Context bar** (amount, date, objective, mode): global state shown on every Decide page.
- **Explain drawer**: opened from any number (`E` key on a focused cell, or a click).
- **Freshness badge**: attached to every value, row and chart.
- **Compare tray**: a sticky bottom tray (maximum 4) that you add to from any table row (`C` key).

### 2.4 Keyboard map (global)
`⌘K`/`Ctrl K` command palette · `/` focus search · `g d` Discovery · `g c` Compare · `g s` Scenarios · `g m` MF · `g f` Fixed income ·
`E` explain focused number · `C` add to compare · `W` add to watchlist · `?` shortcut sheet · `Esc` close drawer and return focus to its opener.
Single-letter shortcuts are disabled while focus is in a text field, which satisfies WCAG 2.1.4 Character Key Shortcuts. They can be turned off in Settings.

---

## 3. Wireframes

Notation: `[ ]` button, `( )` radio, `[x]` checkbox, `▾` select, `ⓘ` opens the explain drawer, `●` freshness badge, `░` fixture hatch.

### 3.1 Onboarding & objectives (step 3 of 5)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  Investment Intelligence Pro                                       Step 3 of 5  ●●●○○ │
│                                                                                       │
│  What matters most for this ₹5,00,000 you need on 15-Apr-2027?                        │
│  Pick one. You can compare objectives later; we never mix them into "max return".     │
│                                                                                       │
│  ( ) A  Keep the full amount safe                                                     │
│         Success = the chance of getting back less than you put in is as close to 0   │
│         as the data allows.  Trade-off: lower expected proceeds.                      │
│  ( ) B  Know what I'll get on the date                                                │
│         Success = narrow range of maturity proceeds.  Trade-off: reinvestment risk.   │
│  ( ) C  Be able to withdraw any time                                                  │
│         Success = days-to-cash and exit cost.  Trade-off: lower yield.                │
│  ( ) D  Grow, but watch the downside                                                  │
│         Success = better lower-band outcome after costs and tax.                      │
│  ( ) E  Grow aggressively — I accept losses                                           │
│         Requires a loss budget on the next step. Not available under 12 months    ⓘ   │
│                                                                                       │
│  ┌ Why we ask ──────────────────────────────────────────────────────────────────────┐ │
│  │ Without steps 1–5 the app runs in EXPLORATION mode: comparisons use illustrative │ │
│  │ ₹1,00,000 and are never ranked "for you".                                        │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                       │
│  [← Back]                     [Skip — explore without a profile]          [Continue →] │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
Steps: 1 Amount (₹ input with live lakh/crore read-back: "₹5,00,000 = 5 lakh") · 2 Date or horizon chip (1M/3M/6M/12M, or a
date picker that shows the resulting horizon in days) · 3 Objective · 4 Loss tolerance (none / up to ₹__ / up to __ %) and early-need
likelihood · 5 Liquidity (max days to cash, max exit cost). Optional: holdings CSV, tax profile, exclusions. Review screen echoes
everything in plain language before saving. Each step is a single `<fieldset>` with a `<legend>`. Errors are inline and announced
via `aria-live="polite"`.

Whether objective E is allowed under 12 months is a product decision. The default shown here is "disabled with explanation".

### 3.2 Discovery (personalised mode, results)

```
┌ CONTEXT ₹5,00,000 · 15-Apr-2027 (182 days) · A Capital preservation · PERSONALISED [Edit] ┐
├────────────────────────────────────────────────────────────────────────────────────────────┤
│ Discovery                                         Data ● EOD 14-Oct-2026 · Engine v0.3.1  │
│ ┌ Assumptions used (echoed) ───────────────────────────────────────────────────────────┐  │
│ │ Pre-tax (no tax profile) · Costs incl. TER, exit load, stamp duty · Hold to date     │  │
│ │ Excluded by you: NBFC deposits, rating < AA+ · Max days to cash: 3     [Change]      │  │
│ └──────────────────────────────────────────────────────────────────────────────────────┘  │
│ Showing 6 of 214 candidates that pass all constraints.  Ordered by: lowest chance of loss, │
│ then narrowest proceeds range.   ▾ Order by                     [Why not others? (208)]    │
│                                                                                            │
│  #  Instrument                  Type     Proceeds on 15-Apr-2027 (5th–95th pct)   Loss    │
│                                          ₹4.9L        ₹5.0L        ₹5.1L       ₹5.2L chance│
│  1  182-day T-bill (auction    T-bill            │      ●            │            0 of 20 ⓘ│
│     22-Oct) ● EOD               Sovereign A-I    │   ₹5,16,8xx fixed*│                      │
│  2  Liquid fund — Scheme X     MF Liquid         │    ├──●──┤        │            0 of 20 ⓘ│
│     Direct-G  ● EOD 14-Oct      PRC A-I           │   ₹5,14,9xx–5,17,6xx│                    │
│  3  Bank FD 6M — Bank Y        FD (DICGC ≤₹5L)  │   ●               │   0 of 20; early    ⓘ│
│     ● STALE rate (31 days)  ⚠                    │                   │   exit −0.5 %         │
│ ...                                                                                        │
│ ─────────────────────────────────────────────────────────────────────────────────────────  │
│ * T-bill held to maturity: proceeds fixed in ₹ given purchase at cut-off; range shows only │
│   auction cut-off uncertainty before purchase.                                             │
│ Past outcomes are not a reliable indicator of future results. Method: Discovery v0.3 ⓘ     │
│                                                       [+ Compare selected (2)]             │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```
Rules:
- Each row's band shares **one ₹ axis** across all rows, so the bands can be compared by position. The median dot is no bolder than the band.
- "Loss chance" uses frequency framing ("0 of 20 historical 182-day windows"), never a percentage with decimals.
- A row with a STALE input keeps its rank position but shows ⚠, and its dependent claim ("loss chance") is greyed with "needs fresh data".
- **"Why not others?"** opens the exclusion ledger: each of the 208 excluded candidates with the first constraint it failed. The ledger can be grouped by reason.
- Exploration mode: the context bar turns amber (`EXPLORATION — illustrative ₹1,00,000, 6M, no objective`). The `#` column is removed. Rows are grouped by category, A–Z.

### 3.3 Instrument detail (mutual fund)

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ Scheme X Liquid Fund — Direct Plan — Growth                 [☆ Watch] [+ Compare] [Scenario]│
│ AMFI code 1xxxxx · ISIN INF… · Category: Debt › Liquid · AMC: X Mutual Fund                 │
│ NAV ₹2,xxx.xxxx  ⓘ  ● EOD  observed 14-Oct-2026 (IST) · retrieved 15-Oct 05:34 UTC · AMFI  │
├───────────────────────────────┬────────────────────────────────────────────────────────────┤
│ FOR YOUR GOAL (182 days)      │ RISK — two different things                               │
│ ₹5,00,000 → on 15-Apr-2027    │ PRC cell (regulatory ceiling)   Riskometer (AMC, Sep-2026)│
│                               │   A   B   C                      Low to Moderate  ⓘ      │
│  ·  ·  ····:::::····  ·       │ I [■] [ ] [ ]                    "AMC-reported; monthly"  │
│ ₹5.12L   ₹5.15L   ₹5.18L      │ II[ ] [ ] [ ]                                             │
│ each dot = 1 of 20 historical │ III[ ][ ] [ ]  Max Macaulay ≤1y, CRV ≥12  ⓘ               │
│ 182-day windows (2019–2026)ⓘ  │ Our checks: exit load 0 after 7 days · settlement T+1     │
│ Absolute: +2.9 % to +3.6 %    │ Worst 182-day window: +1.4 % (Mar–Sep 2020) ⓘ             │
│ (annualised ≈ 5.9–7.3 %,      │ Max drawdown (daily NAV): −0.0x % ⓘ                       │
│  secondary — see caveat ⓘ)    │                                                           │
├───────────────────────────────┴────────────────────────────────────────────────────────────┤
│ PAST PERFORMANCE — complete periods only · source AMFI NAV · ● EOD 14-Oct-2026             │
│  Period            Absolute   Annualised  Category median  Rank in cat.                    │
│  1M (to 30-Sep)    +0.5 %        —          +0.5 %          41/58  ⓘ                        │
│  6M                +3.3 %        —          ...                                            │
│  12M               +6.9 %      +6.9 %       ...                                            │
│  3Y                 ...         CAGR ...                                                    │
│  Past performance is not a reliable indicator of future results.                          │
├────────────────────────────────────────────────────────────────────────────────────────────┤
│ COSTS  TER 0.xx % ⓘ · Exit load (graded, days 1–7) ⓘ · Stamp duty 0.005 % ⓘ               │
│ TAX    Under assumed profile "30 % slab, new regime" ▾ — Sec. 50AA: slab rate ⓘ  (CA review)│
│ LIQUIDITY  T+1 redemption · ₹ cut-off times ⓘ                                              │
│ HOLDINGS  Top 10 issuers · credit mix (bar, labelled) · avg maturity · YTM ⓘ  ● Sep-2026   │
│ DOCUMENTS  SID · KIM · Factsheet (links + retrieval date)                                  │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```
Order is deliberate: identity and provenance → *outcome for your goal* (a distribution) → *risk* → past performance (not first, as
COBS 4.6.2R(1) requires) → costs, tax and liquidity. In the fixed-income variant, the outcome panel shows the cash-flow schedule. A price or
mark-to-market band appears only if the bond is sold before maturity. The yield is labelled with its convention.

### 3.4 Comparison (2–4 instruments)

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ Compare (3)   ₹5,00,000 · 182 days · Objective A        [Only show differences ☑] [Export]│
├──────────────────────┬──────────────────┬──────────────────┬───────────────────────────────┤
│                      │ 182-day T-bill   │ Liquid — Scheme X│ FD 6M — Bank Y                │
│ Freshness            │ ● EOD 14-Oct     │ ● EOD 14-Oct     │ ● STALE 14-Sep ⚠              │
├──────────────────────┼──────────────────┴──────────────────┴───────────────────────────────┤
│ Proceeds on date     │  shared ₹ axis  ₹5.10L ─────────── ₹5.15L ─────────── ₹5.20L       │
│ (dot = 1 of 20)      │  T-bill     ·                         ●                            │
│                      │  Liquid                    ··:::··                                 │
│                      │  FD                            ● (rate stale — band suppressed)    │
├──────────────────────┼──────────────────┬──────────────────┬───────────────────────────────┤
│ Chance of loss       │ 0 of 20          │ 0 of 20          │ 0 (contractual)                │
│ Early exit cost (3M) │ Sell secondary ⓘ │ ~0 (after 7 d)   │ −0.5 % penalty on rate ⓘ       │
│ Days to cash         │ T+1 secondary ⓘ  │ T+1              │ Same day–T+1 (bank) ⓘ          │
│ Credit               │ Sovereign        │ PRC A-I          │ DICGC up to ₹5L/bank ⓘ         │
│ Tax (assumed 30 %)   │ Slab, on maturity│ Slab (50AA)      │ Slab, accrual; TDS ⓘ           │
│ Minimum / lot        │ ₹10,000 multiples│ ₹100             │ ₹1,000                         │
├──────────────────────┴───────────────────────────────────────────────────────────────────── ┤
│ WHAT WOULD CHANGE THE ORDER                                                                 │
│ • If repo rate falls 50 bp before 22-Oct auction, T-bill proceeds −₹1,2xx  ⓘ  [Scenario]   │
│ • If you need the money at 3M, FD drops below Liquid (penalty)              [Scenario]     │
│ Not a recommendation. Ordering reflects your stated constraints only.                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```
Each row is a `<th scope="row">`. Column headers are sticky. Differences are emphasised with weight and a `≠` marker, not colour.

### 3.5 Scenario lab

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ Scenario lab   Base: Liquid — Scheme X, ₹5,00,000, 182 days       Engine v0.3.1 · ● EOD     │
├──────────────────────────────┬─────────────────────────────────────────────────────────────┤
│ SHOCKS                       │ PROCEEDS AT 15-Apr-2027                                     │
│ Preset ▾ [Rate +100bp]       │                                                             │
│                              │ Base     ··:::::··                         5th–95th          │
│ Policy/short rates  [+100] bp│ Shocked     ··::::··                       ₹5.11L–₹5.17L    │
│  ◀━━━━━━━━●━━━━━━▶          │         ┼──────────┼──────────┼──────────┼                  │
│ Credit spread       [  0] bp │       ₹5.08L     ₹5.12L     ₹5.16L     ₹5.20L              │
│ Rating downgrade  ▾ none     │                                                             │
│ Inflation (CPI)    [  0] pp  │ Change in median: −₹1,9xx (−0.4 %) ⓘ                        │
│ Withdraw early at  ▾ never   │ Change in 5th pct: −₹2,4xx ⓘ                                │
│ Hist. regime  ▾ Mar-2020     │                                                             │
│                              │ SENSITIVITY (one shock at a time, ±1 step)                  │
│ [Reset]  [Save scenario]     │            −₹3k     −₹1k  0  +₹1k                           │
│                              │ Rate       ███████████│█████                                │
│ ⓘ Shocks are hypothetical    │ Spread           ████│██                                    │
│   and not forecasts. Model:  │ Early exit         ██│                                      │
│   Scenario v0.2 ⓘ            │ (bars: labelled ₹, sorted by size; no red/green)            │
├──────────────────────────────┴─────────────────────────────────────────────────────────────┤
│ Path view ▾ (fan chart, monthly)  ─  50 % band ▒▒ 90 % band ░░ · median thin line · labels │
│ on-chart · ⏵ Hypothetical outcomes (animated, off by default)                               │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```
Sliders are Radix/React Aria sliders with numeric input mirrors, so values can be typed exactly. Every recompute is deterministic and
debounced by 250 ms. The output shows "Computing…" with a skeleton of the *previous* result dimmed, never a blank.

---

## 4. Visual system

### 4.1 Typography
- **UI and numerals: Inter (variable, OFL-1.1)**, self-hosted via `@fontsource-variable/inter` 5.3.0. There are no Google Fonts CDN calls, for privacy and because the app is offline-capable. Numerals use `font-feature-settings: "tnum" 1, "lnum" 1;` everywhere numbers appear in tables, axes and the context bar. `"zero" 1` (slashed zero) is used in identifiers such as ISIN and AMFI code. *Verify ₹ (U+20B9) glyph coverage in the build test.* The fallback stack is `Inter, "Segoe UI", system-ui, -apple-system, sans-serif`.
- **Code and formulas: IBM Plex Mono (OFL-1.1)** in the explain drawer only.
- Alternative if Inter's ₹ glyph is unsatisfactory: IBM Plex Sans (OFL-1.1, 11.7k stars, active on 2026-10-14).

| Token | Size / line | Weight | Use |
|---|---|---|---|
| `display` | 28 / 36 | 600 | Page title only. Never used for a number |
| `title` | 20 / 28 | 600 | Section headings |
| `heading` | 16 / 24 | 600 | Card and panel headings |
| `body` | 14 / 20 | 400 | Default |
| `body-num` | 14 / 20 | 500, tnum | Table numbers |
| `small` | 12 / 16 | 400 | Captions, provenance, axis labels (minimum size for any text) |
| `micro-caps` | 11 / 16, +0.04em, uppercase | 600 | Badges only. Badge text is never the sole carrier of meaning |

**Number rules.** The largest number on any screen is at most `title` size. This is principle 1: no 48-px hero returns.
Right-align numeric columns and align decimals using tnum and fixed decimals per column.

### 4.2 Indian number formatting
- Exact amounts: `Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'})` → `₹12,34,567.89` (verified on Node 24, 2026-10-15).
- Compact: ICU `en-IN` compact gives `12L` and `1.2Cr`, which is terse and varies by ICU version. **Use an in-house deterministic formatter** that produces `₹12.35 L` / `₹1.23 Cr` (thin space, 2 decimals), with snapshot tests. The exact value is always shown in the tooltip and the explain drawer.
- Settings offers a toggle between lakh/crore (default) and international (million) grouping. This affects display only, never storage.
- Percentages: sign always shown (`+2.9 %`, `−0.4 %` with U+2212 minus), with a narrow no-break space before `%`. Basis points for rate changes (`+100 bp`).
- Dates: `15-Apr-2027` (unambiguous) in the UI, ISO in exports. Time zone suffix on timestamps: `05:34 UTC` / `11:04 IST`.

### 4.3 Colour tokens

Contrast ratios were computed with the WCAG 2.x relative-luminance formula against each surface (script: scratchpad
`contrast.py`; reproduce in `tests/a11y/contrast.test.ts`). All text tokens pass **AA (≥ 4.5:1)** on all three surfaces. Non-text
UI boundaries pass **≥ 3:1** (WCAG 1.4.11).

**Light**

| Token | Hex | vs bg `#FAFAF8` | vs surface `#FFFFFF` | vs surface-2 `#F1F2F4` | Use |
|---|---|---|---|---|---|
| `text` | `#15171C` | 17.16 | 17.93 | 16.01 | Primary text |
| `text-muted` | `#4A5161` | 7.61 | 7.95 | 7.10 | Secondary text |
| `text-subtle` | `#5F6675` | 5.51 | 5.76 | 5.14 | Captions, provenance |
| `border-strong` | `#7D8492` | 3.60 | 3.76 | 3.36 | Input borders, focusable boundaries |
| `accent` / `focus` | `#1F55C4` | 6.37 | 6.66 | 5.94 | Links, focus ring (2 px + 2 px offset) |
| `dir-up` | `#1F55C4` | 6.37 | 6.66 | 5.94 | Positive change (with `+` and ▲) |
| `dir-down` | `#A9420A` | 5.79 | 6.05 | 5.40 | Negative change (with `−` and ▼) |
| `fresh-live` | `#0B6E66` | 5.85 | 6.11 | 5.46 | LIVE badge |
| `fresh-delayed` / `warn` | `#7A5300` | 6.56 | 6.85 | 6.12 | DELAYED badge, warnings |
| `fresh-eod` | `#475467` | 7.36 | 7.69 | 6.86 | END-OF-DAY badge |
| `fresh-stale` | `#B42318` | 6.29 | 6.57 | 5.87 | STALE badge, data errors |
| `fixture` | `#8E1C6B` | 7.95 | 8.31 | 7.41 | FIXTURE badge plus hatch |
| `risk-ink` | `#3E4C8A` | 7.71 | 8.06 | 7.20 | Risk-level glyph fill |

**Dark** (`#0D0F13` bg, `#15181E` surface, `#1D2129` surface-2)

| Token | Hex | vs bg | vs surface | vs surface-2 |
|---|---|---|---|---|
| `text` | `#E7E9EE` | 15.79 | 14.63 | 13.28 |
| `text-muted` | `#AEB4C0` | 9.22 | 8.54 | 7.75 |
| `text-subtle` | `#959DAB` | 7.02 | 6.51 | 5.91 |
| `border-strong` | `#6B7382` | 4.02 | 3.72 | 3.38 |
| `accent` / `focus` / `dir-up` | `#86ABFF` | 8.48 | 7.86 | 7.13 |
| `dir-down` | `#FFA066` | 9.56 | 8.87 | 8.04 |
| `fresh-live` | `#4FD1C1` | 10.25 | 9.50 | 8.62 |
| `fresh-delayed` / `warn` | `#F2C14E` | 11.43 | 10.59 | 9.61 |
| `fresh-eod` | `#B3BDCC` | 10.11 | 9.37 | 8.50 |
| `fresh-stale` | `#FF8A80` | 8.40 | 7.79 | 7.07 |
| `fixture` | `#F48FD0` | 8.85 | 8.20 | 7.44 |
| `risk-ink` | `#A9B4E8` | 9.48 | 8.79 | 7.97 |

**Direction is blue / orange, not green / red.** This pair stays distinguishable under deuteranopia, protanopia and tritanopia
(Okabe–Ito lineage). It is *always* paired with a sign (`+`/`−`) and an arrow glyph (▲/▼). Colour is the third, redundant channel.
**Categorical series** (up to 4 compared instruments) use Okabe–Ito: `#0072B2`, `#E69F00`, `#009E73`, `#CC79A7`. Each series also gets a
distinct dot shape (● ■ ▲ ◆) and a direct label. Legends are never the only key.
**Distribution bands** use one hue at stepped opacity: 90 % band at 18 % alpha, 50 % band at 35 % alpha. The median is a 1-px line in `text`.

### 4.4 Data-freshness badges

Outlined pill (1 px border plus text, both in the token colour, on the surface). Every badge carries a **glyph**, a **word** and a **date**,
so it never relies on colour alone. Hovering or focusing shows the full provenance, and clicking opens the Evidence viewer.

| Badge | Glyph | Meaning (rules owned by Data Health config) | Effect on dependent claims |
|---|---|---|---|
| `LIVE` | ● (solid) | Observed within the source's intraday cadence | None |
| `DELAYED` | ◐ | Intraday source, but older than its cadence (e.g. > 15 min) | Labels "delayed by N min" |
| `END-OF-DAY` | ◑ | Latest official daily publication (e.g. AMFI NAV for T-1) | None. This is the expected state for MF NAV |
| `STALE` | ○ ⚠ | Older than the per-source staleness threshold (e.g. NAV > 3 business days, FD rate > 30 days) | Dependent ranking and probability claims are **disabled** and say "needs fresh data". The row stays visible |
| `FIXTURE` | ▨ | Development fixture, not market data | **Diagonal hatch** behind the whole component, the text `FIXTURE — not market data`, and the hatch is burnt into exports and screenshots. Personalised mode refuses to rank fixtures |

LIVE is expected to be rare in v1, because there are no licensed real-time feeds. Do not design screens that look empty without it.

### 4.5 Risk-label system

Risk is shown as **named dimensions**, never one combined score, and never as a traffic light.

| Dimension | Display | Source label |
|---|---|---|
| Regulatory ceiling (debt MF) | 3×3 PRC grid with the cell filled in `risk-ink`, plus text "A-I: relatively low credit / relatively low interest-rate risk (max)" | "SEBI PRC — declared by AMC" |
| AMC riskometer | Text only: "Low to Moderate", plus month. **Never the dial image** | "AMC-reported, {month}" |
| Credit | Rating text + agency + action date (`AA+ (CRISIL, 12-Aug-2026)`) or "Sovereign" or "DICGC-insured up to ₹5 L per bank" | Rating agency |
| Interest-rate sensitivity | Macaulay/modified duration in years, plus "≈ −₹X per +100 bp on your amount" | Computed ⓘ |
| Liquidity | Days to cash, plus exit cost in ₹ for the user's amount | Computed ⓘ |
| Horizon fit | `Fits` / `Mismatch: matures after your date` / `Mismatch: price risk if sold early` | Computed ⓘ |
| Historical downside | Worst window for this horizon, plus count of loss windows ("2 of 40") | Computed ⓘ |

Levels within a dimension use a **5-step bar glyph** (▮▮▯▯▯) in `risk-ink` plus a word. Bars encode *more risk = more fill*,
one hue only, so no colour reads as "safe".

---

## 5. Interaction patterns

### 5.1 "Explain this number" drawer

Opened from any `ⓘ`, by clicking a number, or with `E` on a focused cell. It is a right-side Radix `Dialog` (non-modal sheet variant) with
focus moved to the heading and returned to the opener on close. URL deep-link: `?explain=<metricId>@<engineVersion>`.

```
┌ Explain: Proceeds 5th percentile — ₹5,14,9xx ─────────────────────────── [Copy] [×] ┐
│ WHAT IT IS   The amount you'd have received in the worst 1-in-20 of past 182-day    │
│              windows, scaled to ₹5,00,000, after TER and exit load.                │
│ INPUTS       NAV series (1,8xx obs, 02-Jan-2019 → 14-Oct-2026)  ● EOD  [Evidence →] │
│              Amount ₹5,00,000 (your profile) · Horizon 182 d · Exit load table v3  │
│ FORMULA      q05( NAV[t+h]/NAV[t] ) × A − costs        [Methodology §4.2 →]        │
│              computed: 1.02983 × 5,00,000 − 0 = ₹5,14,9xx                           │
│ SOURCES      AMFI NAV history · retrieved 15-Oct-2026 05:34 UTC · sha256 3f9a…      │
│ OBSERVED     Latest observation 14-Oct-2026 (IST)                                   │
│ ASSUMPTIONS  • Past windows are representative (strong assumption) • No tax applied │
│              • Overlapping windows (effective n ≈ 15, not 1,6xx)                    │
│ SENSITIVITY  Window 2021+ only: ₹5,13,2xx · Exclude 2020: ₹5,15,1xx                 │
│              Horizon ±30 d: ₹5,12,4xx – ₹5,17,0xx                                    │
│ LIMITATIONS  Does not capture credit events absent from history (e.g. 2019-type     │
│              defaults in this scheme's category). Not a forecast.                   │
│ Engine v0.3.1 · metric proceeds.q05 v2 · deterministic hash 9c1e…                  │
└────────────────────────────────────────────────────────────────────────────────────┘
```
Required sections, in this order: What it is · Inputs · Formula (symbolic plus the substituted arithmetic) · Sources · Observation date ·
Assumptions · Sensitivity (at least 2 alternative inputs) · Limitations · Version and hash. A metric that cannot fill every section
fails a CI check and cannot render.

### 5.2 "No suitable candidate found"

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  No suitable candidate found under your current constraints.                         │
│  This is a valid result, not an error. 214 instruments checked · ● EOD 14-Oct-2026   │
│                                                                                      │
│  Closest misses (each fails exactly one constraint)                                 │
│   Instrument                 Failed constraint            By how much               │
│   Liquid — Scheme Z          Max days to cash ≤ 1          needs T+1 (1 day over)   │
│   FD 6M — Bank Q             Excluded: NBFC deposit        your exclusion            │
│   364-day T-bill             Horizon fit                   matures 182 d after date  │
│                                                                                      │
│  What you could change (shows the effect, doesn't recommend)                        │
│   • Allow T+1 liquidity → 4 candidates pass              [Try this, temporarily]     │
│   • Allow AA rating → 11 candidates pass                 [Try this, temporarily]     │
│                                                                                      │
│  Or keep the money where it is: your current savings/sweep rate is an option too.   │
│  [Full exclusion ledger (214)]                              [Edit constraints]       │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
Rules: neutral styling (no error red, no sad illustration). "Try this, temporarily" opens a *what-if* banner with the relaxed
constraint highlighted. It never silently edits the profile. If the cause is *data* (STALE or missing), the panel says so separately:
"3 candidates could not be evaluated because their data is stale → Data health". Data gaps are not counted as "unsuitable".

### 5.3 Exploration mode vs personalised mode

| Aspect | Exploration | Personalised |
|---|---|---|
| Trigger | Any of suitability inputs 1–5 missing | All of 1–5 present |
| Context bar | Amber `fresh-delayed` outline: "EXPLORATION — illustrative ₹1,00,000 · 6M · no objective" | Neutral: the user's values |
| Ranking | **None.** Grouped by category, A–Z or by a user-chosen sort column with the label "sorted by X, not ranked for you" | Ranked by objective-specific ordering, with the order rule printed above the list |
| Copy | "Examples", "illustrative", "if you invested ₹1,00,000" | "Under your constraints", "for ₹5,00,000 on 15-Apr-2027" |
| After-tax | Only under named assumed profiles (selector) | User profile if given, otherwise assumed profiles |
| Watermark | Small persistent `ILLUSTRATIVE` tag on every chart | none |
| Switch | Banner CTA "Add 3 details to see results for you" → onboarding at the first missing step | Context bar [Edit] |

### 5.4 Return target vs historical frequency

Users often arrive with a target ("I want 8 % in 6 months"). We never answer with "achievable" or "not achievable". We show **how
often it happened**:

```
Your target: +4.0 % absolute in 182 days (₹5,20,000)              ⓘ  (= 8 % p.a. simple, secondary)

Historical 182-day windows, Scheme X Liquid (2019–2026, 20 dots = 20 equally likely quantiles)
                                                    target ┆
   ·  ·  ····::::::····  ·                                 ┆
 +1.5 %          +3.0 %          +3.5 %             +4.0 % ┆
Reached or beat target: 0 of 20.  Closest: +3.6 % (Sep-2023 → Mar-2024).
Instruments in this category that reached it in ≥ 10 of 20: none.  [See what would need to change]
```
Rules: the target line is a dashed vertical rule labelled on-chart. The count is a frequency ("k of 20"), not a probability, and the
caption says "historical frequency, not a forecast". If the target is outside every historical window of every eligible
instrument, show the pattern from 5.2 ("no candidate reached this target historically"). We never suggest taking more risk to hit the target.
At most we show what objective E would involve, with its loss band, and only on request.

### 5.5 Other state patterns
- **Loading**: skeletons keep the layout. Numbers show `—` with `aria-busy`, never `0`.
- **Error**: names the source and the claim affected ("AMFI fetch failed 05:30 UTC; NAV-based results use 13-Oct data (STALE)"), with a link to Data health.
- **Empty**: teaches the next step (CSV template, example filters).
- **Tables**: TanStack Table plus the ARIA `grid` pattern only where cells are interactive, and a plain `<table>` otherwise. Roving tabindex. Arrow keys move between cells, `Home`/`End`, `PgUp`/`PgDn`. `Enter` opens the row. `E`, `C` and `W` act on the row. Sort state is in `aria-sort`. A sticky first column and header. Virtualise only above about 200 rows, keeping `aria-rowcount` and `aria-rowindex`.
- **Charts**: every chart has a visually-hidden data table alternative ("View as table" toggle visible too), a text summary sentence, and keyboard-focusable points for dot plots (arrow keys step quantiles, and the value is announced).
- **Motion**: ≤ 200 ms, cause-and-effect only, disabled under `prefers-reduced-motion`.
- **Target size**: ≥ 24×24 px (WCAG 2.2 SC 2.5.8). **Focus not obscured** (2.4.11): sticky headers and the compare tray reserve scroll padding (`scroll-padding-top/bottom`). **Dragging** (2.5.7): allocation and slider controls all have typed-input alternatives. **Consistent help** (3.2.6): `?` is always in the same top-bar position. **Redundant entry** (3.3.7): the onboarding review step never asks again.

---

## 6. Anti-patterns: banned

These are enforced in design review and, where possible, by lint or tests (e.g. a test that fails if a <12-month return is rendered
as primary annualised).

| Banned | Why | Do instead |
|---|---|---|
| **Fake or scrolling tickers** (marquee of prices, invented symbols, animated "live" numbers without a live source) | Simulates liveness and urgency. Risks showing fabricated data | Freshness badge plus a static value. Fixtures carry a FIXTURE hatch |
| **Gauges, dials, speedometers** (including reproducing the riskometer dial) | A single needle implies precision and a single-scalar risk. Hard to read and inaccessible | Named risk dimensions (§4.5) with text and a bar glyph |
| **"AI confidence 87 %"** or any model-confidence percentage | There is no calibrated basis. It invites over-trust. v1 has no AI | Historical frequency ("k of 20") with an explain drawer |
| **Green "Safe" / "Low risk" badges on debt funds** | Debt MFs carry credit, duration and liquidity risk. 2019–2020 credit events and the Franklin Templeton 2020 scheme wind-ups show it | PRC cell plus rating plus "chance of loss k of N" in neutral ink |
| **Annualising 7-day or other sub-month returns as a headline** | Compounding noise into a big number (e.g. 7-day +0.2 % → "≈ 11 % p.a." compounded) misleads. Allowed in AMC advertisements, but we ban it | Absolute return for the actual window. Annualised only as secondary for ≥ 1M windows, with a caveat |
| Red / green as the only gain/loss encoding | Fails for about 8 % of men (CVD), and is culturally loaded | Blue / orange plus sign plus arrow |
| Single-point projections ("₹X in 5 years") | Hides dispersion | Quantile dot plot or fan chart |
| Hero-sized return numbers | Makes past return the most prominent feature | ≤ `title` size, and after the outcome band |
| Stars, medals or verdict chips ("Best", "Top pick", "Buy") | Verdicts without suitability | "Ranks #1 under your constraints" plus the order rule |
| Hidden time windows ("Returns" without period) | Ambiguous | Period, observation date and the absolute/annualised label are always explicit |
| Dark patterns: urgency timers, streaks, confetti, "X people bought today" | Manipulation | none |
| Bare error bars or ± without frequency framing | Read as hard limits (deterministic construal) | Bands plus a "k of N" caption |
| Truncated y-axes on return bars | Exaggerates differences | Bars start at 0. Dot plots may zoom but show the axis break |

---

## 7. Recommended component and charting stack

Statistics from `gh api repos/<repo>` and `npm view` on **2026-10-15**. Bundle sizes from bundlephobia (min+gzip, **full package
entry**; tree-shaken usage is smaller, so measure in our own build with `vite build --mode analyze` before committing).

| Layer | Pick | Version | License | GitHub ★ | min+gz | Justification |
|---|---|---|---|---|---|---|
| Framework | React + TypeScript + Vite | — | MIT | — | — | Planned stack |
| Primitives (overlays) | **Radix UI Primitives** | `@radix-ui/react-dialog` 1.3.1 | MIT | 19,396 (radix-ui/primitives) | 13.2 kB (dialog) | Mature focus management for Dialog, Popover, Tooltip, Tabs, ToggleGroup. Unstyled. Per-package installs keep the bundle small |
| Primitives (data-entry, i18n) | **React Aria Components** (selective) | 1.22.1 | Apache-2.0 | 15,945 (adobe/react-spectrum) | 279 kB full / much smaller per-component | Best-in-class NumberField (locale-aware `en-IN` parsing), DatePicker with Indian locale, Slider with keyboard and typed-entry, and an accessible Table/GridList. Use these components only. **Do not** mix two libraries for the same widget |
| Styled layer | **shadcn/ui** (copy-in, not a dependency) | CLI, n/a | MIT | 125,630 | 0 (source copied) | Gives Radix-based components we own and restyle to our tokens. No lock-in. We audit each copied component for WCAG 2.2 |
| Styling | Tailwind CSS v4 *or* CSS variables plus vanilla-extract | — | MIT | — | — | Tokens from §4 as CSS custom properties. Tailwind is optional. The token file is the source of truth |
| Tables | **TanStack Table** | `@tanstack/react-table` 9.3.1 | MIT | 28,492 | 31.6 kB | Headless. Sorting, filtering, column pinning, grouping. We render semantic `<table>` and own the ARIA. The v9 major is new, so pin it and read the migration notes |
| Virtualisation | **TanStack Virtual** | 3.14.19 | MIT | 7,145 | 8.4 kB | Only for the MF explorer (thousands of schemes) |
| Custom statistical charts | **visx** (+ d3-scale) | `@visx/xychart` 4.0.0; `d3-scale` 4.0.2 | MIT; ISC | 21,077 (last push 2026-06-22) | 49.9 kB; 16.0 kB | Quantile dot plots, fan charts, PRC grid, tornado and shared-axis comparisons need **bespoke marks**. visx gives SVG primitives with full control of ARIA and focus. The push cadence is slower than it was. Fallback: plain d3-scale/d3-shape plus our own SVG, which is a tiny dependency surface |
| Standard charts (time series, bars) | **Recharts** | 3.10.1 | MIT | 27,628 | 151.5 kB | Fast to build NAV history and allocation bars. v3 has an accessibility layer (keyboard and ARIA). Not used for uncertainty marks |
| Heavy or large series (optional) | ECharts | 6.1.0 | Apache-2.0 | 67,512 | 368 kB | Excellent performance and an `aria` decal pattern feature, but large, canvas-first (weaker per-point a11y) and stylistically opinionated. **Not in v1.** Reconsider only if we need 10k-plus point series |
| Price charts | TradingView lightweight-charts | 5.2.1 | **Apache-2.0 with attribution obligation** | 17,577 | 61.6 kB | **Not recommended for v1.** The NOTICE requires "TradingView Lightweight Charts™, Copyright (c) 2025 TradingView, Inc." and a link to tradingview.com on a user-visible page (the `attributionLogo` option satisfies the link). Its candlestick/trading idiom conflicts with our "not a trading tool" stance. If ever used, add the notice to an About/Licenses page |
| Exploratory charts (internal) | Observable Plot | 0.6.17 | ISC | 5,405 | 128 kB | Good for methodology notebooks and internal QA, not for the product UI |
| Fonts | Inter (variable); IBM Plex Mono | `@fontsource-variable/inter` 5.3.0 | OFL-1.1 | 19,968 (rsms/inter) | n/a | Tabular numerals, ₹ glyph to be verified, self-hosted |
| Formatting | In-house `formatINR`, `formatPct`, `formatDate` plus `Intl` | — | — | — | 0 | Deterministic, snapshot-tested lakh/crore output |
| a11y testing | axe-core plus Playwright, eslint-plugin-jsx-a11y | — | MPL-2.0 / Apache-2.0 / MIT | — | dev-only | CI gate: zero serious/critical axe violations on all 16 pages, light and dark |

**Licence posture:** every runtime dependency is MIT, Apache-2.0, ISC or OFL-1.1, all permissive. Apache-2.0 packages require shipping
their NOTICE files where present. Add an auto-generated `/settings/licenses` page from `license-checker` output. TradingView is the only
candidate with a user-visible attribution duty, which is one more reason to exclude it.

**Why not a single all-in-one chart library:** the core value of the product is honest uncertainty display. The marks we need most
(quantile dot plots, frequency-framed target lines, fan charts with on-chart labels, the PRC grid) are not first-class in Recharts or ECharts,
and forcing them into those libraries produces exactly the polish-over-truth failures that §1 bans.

---

## 8. Open questions for the user

1. Allow objective E (aggressive) at horizons under 12 months, or block it with an explanation (current default)?
2. Dot-plot resolution: 20 dots (easy to count) or 50 (finer tails)? Default 20, with 50 available in Settings.
3. Should "keep the money where it is" (savings or sweep rate) be a modelled baseline in every comparison? This needs a user-entered rate.

## 9. Sources (retrieved 2026-10-15; treat as references to recheck, not verified quotes)
- Kay, Kola, Hullman and Munson, *When (ish) is My Bus?*, CHI 2016. https://users.eecs.northwestern.edu/~jhullman/busUncertaintyVis.pdf · https://github.com/mjskay/when-ish-is-my-bus
- Padilla, Kay and Hullman, *Uncertainty Visualization* (2022). https://friendly.github.io/6135/papers/Uncertainty_Visualization_Padilla_Kay_Hullman_2020.pdf
- Fernandes et al., *Uncertainty displays using quantile dotplots or CDFs improve transit decision-making*, CHI 2018.
- FCA Handbook COBS 4.6. https://handbook.fca.org.uk/handbook/COBS/4/6.html · FG12/11 https://www.fca.org.uk/publication/finalised-guidance/fg12-11-fpia.pdf
- SEBI MF Master Circular (performance advertisement para; refreshed 2026-03-20, paragraph numbers to verify). https://www.sebi.gov.in · SEBI MF investor FAQ https://www.sebi.gov.in/sebi_data/faqfiles/sep-2024/1727242783639.pdf
- SEBI PRC matrix explainers: https://kuvera.in/blog/how-prc-matrix-of-debt-mutual-funds-works/ · https://www.bajajamc.com/knowledge-centre/a-brief-note-on-mutual-fund-prc-matrix
- TradingView lightweight-charts NOTICE and README (license section), via `gh api repos/tradingview/lightweight-charts`.
- WCAG 2.2: https://www.w3.org/TR/WCAG22/ · Okabe and Ito colour-universal design palette.
