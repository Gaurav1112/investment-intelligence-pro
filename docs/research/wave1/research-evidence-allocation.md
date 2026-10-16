# Evidence Review: Asset Allocation and Risk Management for High-Growth Goals (India, INR)

Research wave 1 · topic `evidence-allocation` · Date: 2026-10-15 · Status: research complete; nothing here is implemented.
Companion documents: `docs/research/return-target-feasibility.md` (rolling-window base rates, which this report reuses rather
than recomputes), `docs/research/indian-instruments-and-tax.md` (tax rules), `docs/finance/risk-methodology.md`.

> **What this document is.** It reviews published evidence on strategic allocation, rebalancing, volatility targeting, drawdown
> control, stop-losses, position sizing (Kelly) and emergency funds. For each technique it decides whether the deterministic
> engine may turn it into a *signal* under the project's binding rule: **a signal exists only if a documented, out-of-sample,
> cost- and tax-aware backtest supports it; otherwise the engine abstains.** It is not investment advice and makes no forecast.

## Verification legend

| Tag | Meaning |
|---|---|
| **[P]** | Read in this session from the primary source (journal PDF, official factsheet, regulator page). |
| **[C]** | Computed in this session (method shown) or inherited from the companion feasibility report, which computed it from official NSE TRI series. |
| **[S]** | Secondary: a search-engine abstract, publisher landing page summary or third-party write-up. The primary text was not opened in this session. |
| **NOT VERIFIED** | Could not be confirmed. Must not be used as a number in the app. |

All access dates are **2026-10-15**. Full source list with quotes is in §11.

---

## 0. Executive summary

1. **Realistic long-run nominal returns (INR) are about 11–17 % for Indian equity indices, about 7–7.5 % for government debt and
   T-bills, and 11–15 % for gold, with inflation about 5–6 %.** Nifty 50 TRI: 12.12 % p.a. since 03-Nov-1995 with a 22.39 % standard
   deviation **[P]**. Nifty 500 TRI 10 y 12.77 %, Midcap 150 TRI 16.56 %, Smallcap 250 TRI 14.64 % (to 30-Sep-2026) **[C]**. Nifty
   Composite G-Sec 7.45 % since 2011, 91-day T-bill 7.11 % since 1993 **[P, via companion]**. Gold (ETF NAV) 15.57 % 10 y, 11.21 % 15 y
   **[C]**.
2. **20 % p.a. is common over 1 year, uncommon over 5, rare over 10, and 25 % p.a. over 10+ years has never happened** on Nifty 50,
   Nifty 500, Midcap 150 or Smallcap 250 TRIs. Share of rolling 10-year windows ≥ 20 %: 5.8 % (Nifty 50), 14.1 % (Nifty 500), 18.1 %
   (Midcap 150), 5.1 % (Smallcap 250); ≥ 25 %: 0 % on all four **[C]**. Gold: 0 % of 10-year windows ≥ 20 % **[C]**.
3. **Headline returns depend heavily on the end date.** Nifty 500 TRI 10-year return was **16.04 %** as of 27-Feb-2026 (NSE) **[P]**
   but **12.77 %** as of 30-Sep-2026 **[C]**. The app must always show the as-of date and a distribution, never one trailing number.
4. **Strategic allocation is the dominant, evidence-backed lever.** Policy allocation explains about 90 % of a fund's return
   variability over time and about 100 % of its return level on average (Ibbotson & Kaplan 2000) **[S]**. Out of sample, 14
   optimisation models did not consistently beat equal weighting (DeMiguel, Garlappi & Uppal 2009) **[S]**. **Implication:** the
   engine should compute the *consequences* of a user-chosen allocation, not optimise one from estimated returns.
5. **Rebalancing controls risk; it is not a return engine.** Vanguard: "The primary goal of a rebalancing strategy is to minimize risk
   relative to a target asset allocation, rather than to maximize returns" and "there is no optimal frequency or threshold" **[P]**.
   Its default: annual or semi-annual monitoring with 5 % bands. In India each sale can trigger 20 % STCG or 12.5 % LTCG above ₹1.25
   lakh, plus exit loads, so new cash flows should be used first **[P, via companion tax doc]**.
6. **Volatility targeting is contested.** Moreira & Muir (2017) report large alphas in-sample **[S]**. Cederburg et al. (2020), on 103
   strategies, found real-time versions "generally earn lower certainty equivalent returns and Sharpe ratios" than the unmanaged
   portfolios **[P]**. Harvey et al. (2018) find Sharpe gains only for "risk assets" (equities, credit) but fewer tail events in all
   classes **[S]**. **No out-of-sample, cost- and tax-aware Indian test was found → the engine must ABSTAIN from volatility-timing
   signals.**
7. **Stop-losses only help if returns trend.** Kaminski & Lo (2014): under a random walk, stop-loss rules "always decrease expected
   returns"; with momentum they can add value **[S]**. Trend-following has long-horizon multi-asset support (Moskowitz, Ooi & Pedersen
   2012; Hurst, Ooi & Pedersen 2017) **[S]**, but momentum also "crashes" in rebounds (Daniel & Moskowitz 2016) **[S]**. NSE's own
   momentum indices beat their parents by 300–600 bp since 2005 but had **68–73 % maximum drawdowns** **[P]**, and their pre-launch
   history is back-calculated. **Verdict: NOT ADMISSIBLE as a signal** until an India-specific, out-of-sample, after-tax backtest
   exists.
8. **Kelly sizing is unusable for an index allocation because its input is unknowable.** Using Nifty 50 TRI figures, full Kelly is
   about 1.5× (150 % equity, i.e. leverage). A ±2 standard-error band on the mean gives **−0.11× to 3.11×** **[C]**. Fractional Kelly
   reduces risk at a modest cost ("half the Kelly amount… about three-quarters of the return with half the volatility", Thorp)
   **[S]**. The engine may show Kelly only as a "you are over-betting" warning, never as a size recommendation.
9. **Emergency fund comes first.** The US SEC's Investor.gov suggests "three to six months of living expenses" **[S]**. No primary
   SEBI/RBI document stating a month count was found (**NOT VERIFIED**). DICGC insures bank deposits up to ₹5,00,000 per depositor per
   bank "in the same right and same capacity" **[P]**.
10. **Bottom line for the product.** The evidence supports a *policy* engine (allocation, bands, emergency-fund gate, drawdown budget,
    tax-aware rebalance arithmetic) much more than a *timing* engine. Every timing signal reviewed is either refuted out-of-sample,
    untested on Indian data after costs and tax, or carries crash risk equal to or worse than buy-and-hold. "No suitable signal" is the
    correct current answer for buy/sell timing.

---

## 1. Realistic long-run returns by asset class (INR, nominal)

| Asset (series) | 10 y | 15 y | Long run | Volatility | Status / source |
|---|---|---|---|---|---|
| Nifty 50 TRI | 11.48 % | 12.02 % | **12.12 %** since 03-Nov-1995 | 22.39 % SD since inception | Long run and SD **[P]** NSE factsheet as of 30-Sep-2026; 10/15 y **[C]** companion §2.1 |
| Nifty 500 TRI | 12.77 % | 13.33 % | 11.89 % since 01-Jan-1995 | 21.91 % | **[C]** / **[P]** companion §2.1 |
| Nifty Midcap 150 TRI | 16.56 % | 17.86 % | 16.75 % since 01-Apr-2005 (pre-2016 back-calculated) | 20.77 % | **[C]** / **[P]** companion |
| Nifty Smallcap 250 TRI | 14.64 % | 15.44 % | 15.63 % since 01-Apr-2005 (pre-2016 back-calculated) | 21.45 % | **[C]** / **[P]** companion |
| Gold, INR (Kotak Gold ETF NAV, net of expenses) | 15.57 % | 11.21 % | 14.73 % since 30-Jul-2007 | max drawdown −29.8 % | **[C]** companion; AMFI NAV via unofficial mirror |
| Nifty Composite G-Sec Index (total return) | — | — | **7.45 %** since 03-Jan-2011 | — | **[P]** companion (NSE factsheet) |
| Nifty 91-Day T-Bill Index | — | — | **7.11 %** since 08-Jan-1993 | — | **[P]** companion |
| India 10-year G-sec yield (a forward-looking anchor for debt, not a return) | — | — | 7.39 % on 15-Oct-2026 | — | **[S]** Trading Economics (OTC quote, not an RBI/FBIL publication) |
| CPI inflation (World Bank series) | 4.73 % (2016–25) | 5.80 % (2011–25) | 6.51 % (2006–25) | — | **[S]** companion |

Notes:

- **Primary re-check this session.** The Nifty 50 factsheet dated 30-Sep-2026 was downloaded and read: Total Return "Since Inception"
  **12.12**, price return 10.61, base date "November 03, 1995", launch date "April 22, 1996", SD since inception 22.39 **[P]**. The other
  index rows are inherited from the companion report and were not re-downloaded.
- **Real return.** With 5–6 % inflation, a 12 % nominal equity return is roughly 6–7 % real. 20 % nominal would be about 13–14 % real.
- **End-date sensitivity [P].** NSE's April-2026 momentum whitepaper gives Nifty 500 TRI 10-year return **16.04 %** and 15-year
  **13.23 %** as of 27-Feb-2026. Seven months later the companion computation gives 12.77 % and 13.33 %. A trailing 10-year number moved
  by over 3 percentage points in seven months. **Rule for the app:** never present a single trailing return as "the" return.
- **Back-calculated history.** Mid/small-cap and all strategy indices with a 2005 base date were launched later. Their early history
  could not have been bought.

## 2. How often has 20–25 % p.a. been achieved? [C]

Taken from the companion report §2.2–2.3 (month-end rolling windows of daily TRI closes up to 30-Sep-2026; windows overlap).

| Share of windows with CAGR ≥ 20 % | 1 y | 3 y | 5 y | 10 y | 15 y |
|---|---|---|---|---|---|
| Nifty 50 TRI | 34.5 % | 22.3 % | 19.0 % | 5.8 % | 0.0 % |
| Nifty 500 TRI | 39.6 % | 27.9 % | 22.7 % | 14.1 % | 5.2 % |
| Nifty Midcap 150 TRI | 43.1 % | 45.5 % | 36.9 % | 18.1 % | 9.0 % |
| Nifty Smallcap 250 TRI | 42.7 % | 41.0 % | 27.8 % | 5.1 % | 2.6 % |
| Gold (ETF NAV, from 2007) | 37.9 % | 24.1 % | 10.5 % | 0.0 % | — |

| Share of windows with CAGR ≥ 25 % | 1 y | 3 y | 5 y | 10 y | 15 y |
|---|---|---|---|---|---|
| Nifty 50 TRI | 29.4 % | 16.1 % | 12.7 % | **0.0 %** | **0.0 %** |
| Nifty 500 TRI | 34.0 % | 18.5 % | 12.8 % | **0.0 %** | **0.0 %** |
| Nifty Midcap 150 TRI | 35.8 % | 23.9 % | 12.1 % | **0.0 %** | **0.0 %** |
| Nifty Smallcap 250 TRI | 39.4 % | 23.9 % | 12.1 % | **0.0 %** | **0.0 %** |

- **Best-ever 10-year windows:** 22.1 % (Nifty 50), 23.4 % (Nifty 500), 23.2 % (Midcap 150), 21.6 % (Smallcap 250). A 25 % p.a.
  plan over 10 years assumes an outcome better than any observed.
- **"Every year" reading:** the share of start months from which each of the next five 12-month periods returned ≥ 20 % was 1.5 %
  (Nifty 50), 2.9 % (Nifty 500) and 0 % (Midcap 150, Smallcap 250).
- **Effective sample size is tiny.** A 10-year statistic over about 26 years of data has only 2 independent windows. Non-overlapping
  5-year hit rates range from 0 % to 40–100 % depending on the start month (companion §2.3).
- **Strategy indices.** NSE reports Nifty Midcap150 Momentum 50 at 23.00 % p.a. since April 2005 and 23.38 % over 10 years to
  27-Feb-2026 **[P]**. This is the only broad Indian index family found near 20–25 % over long windows. It is **back-calculated before
  launch** (launch date **NOT VERIFIED** this session), gross of fund costs and tax, and suffered a 73 % maximum drawdown **[P]**. It
  is not admissible as evidence that 20–25 % is attainable going forward (see §6).

## 3. Strategic allocation: what the evidence supports

| Claim | Evidence | Status |
|---|---|---|
| Allocation policy drives most of the outcome | Ibbotson & Kaplan (2000, *FAJ* 56(1):26–33): "about 90 percent of the variability in returns of a typical fund across time is explained by policy, about 40 percent of the variation of returns among funds is explained by policy, and on average about 100 percent of the return level is explained by the policy return level." | **[S]** abstract via RePEc/ResearchGate |
| Optimisers lose to simple weights out of sample | DeMiguel, Garlappi & Uppal (2009, *RFS* 22(5):1915–1953) evaluate "the out-of-sample performance of the sample-based mean-variance model, and its extensions"; reported finding: none of 14 models consistently beats 1/N. | **[S]**; the "3,000 months" estimate is NOT VERIFIED (search summary only) |
| Higher equity share raises both expected return and drawdown | Indian index max drawdowns: Nifty 50 TRI −59.5 %, Nifty 500 −67.0 %, Midcap 150 −72.9 %, Smallcap 250 −75.6 %, with peak-to-recovery up to 6.4 years. | **[C]** companion §2.4 |
| Active selection does not reliably add return | SPIVA India Mid-Year 2026: 74.0 % of large-cap, 80.5 % of ELSS, 81.7 % of mid/small-cap active funds underperformed over 10 years. | **[P]** companion §2.6 |

**Design implications (deterministic, no forecast):**

1. **The user chooses the allocation. The engine computes consequences:** historical CAGR distribution, worst window, in-window
   drawdown percentiles in % and in ₹, and recovery time for the blended portfolio from TRI and NAV series.
2. **No mean-variance optimiser** on estimated returns. If an optimiser is ever added, only estimation-light schemes (equal weight,
   inverse volatility or a user-set risk budget), each with a published out-of-sample comparison.
3. **Risk capacity first, aspiration second.** The equity share must be capped by the user's entered loss budget: if historical
   in-window drawdown for the chosen mix exceeds the loss budget in X of N windows, show that count before anything else (companion
   RT-12).

## 4. Rebalancing frequency and bands

**Evidence [P] — Vanguard, *Best practices for portfolio rebalancing* (Jaconetti, Kinniry & Zilbering, July 2010), read in full
this session:**

- "The primary goal of a rebalancing strategy is to minimize risk relative to a target asset allocation, rather than to maximize
  returns."
- "…there is no optimal frequency or threshold for rebalancing, since risk-adjusted returns" do not differ meaningfully between
  strategies.
- Rebalancing events on 1926–2009 US data: **1,068** monthly, **355** quarterly, **88** annually, 0 never.
- Conclusion: "annual or semiannual monitoring, with rebalancing at 5% thresholds, is likely to produce a reasonable balance between
  risk control and cost minimization for most investors. Annual rebalancing is likely to be preferred when taxes or substantial
  time/costs are involved."

**Limits:** US stock and bond data, a 50/50 base case, and US tax. No equivalent Indian study was found (**NOT VERIFIED** that the
result transfers).

**India frictions [P, companion tax doc `indian-instruments-and-tax.md`]:**

| Friction | Rule |
|---|---|
| Equity / equity-MF STCG (held ≤ 12 m) | 20 % (from 23-Jul-2024) |
| Equity / equity-MF LTCG (> 12 m) | 12.5 % above ₹1,25,000 per year aggregate exemption |
| Debt MF bought on/after 01-Apr-2023 | Slab rate regardless of holding period |
| Exit loads | Scheme-specific, read from the SID; cap 3 % |
| STT on equity-MF redemption | 0.001 % |

**Engine specification (admissible: arithmetic, not a forecast):**

- **Default policy:** annual review with ±5 percentage-point absolute bands (user-editable). This is a rebalancing *rule the user
  adopts*, not a signal. Alerts must read "your rule X triggered" (see `docs/security/regulatory-readiness.md` F15).
- **Order of operations:** (1) direct new SIP/lump-sum cash to the under-weight asset; (2) redeem from lots with the lowest tax and
  exit-load cost first (LTCG within the ₹1.25 lakh exemption, then long-term lots, never lots inside an exit-load window); (3) only
  then sell lots that create STCG, with the ₹ tax cost shown.
- **Show the trade-off:** ₹ tax and load cost of rebalancing now versus the drift in drawdown exposure of not rebalancing. Do not
  claim a "rebalancing bonus".

## 5. Volatility targeting

| Paper | Finding | Status |
|---|---|---|
| Moreira & Muir (2017), *JF* 72(4):1611–1644 | Portfolios that "take less risk when volatility is high produce large alphas, increase Sharpe ratios"; weight = c / last month's realised variance. | **[S]** Wiley abstract |
| Cederburg, O'Doherty, Wang & Yan (2020), *JFE* 138(1):95–117 | On 103 equity strategies, volatility-managed portfolios "do not systematically outperform"; spanning-regression strategies "are not implementable in real time, and reasonable out-of-sample versions generally earn lower certainty equivalent returns and Sharpe ratios than do simple investments in the original, unmanaged portfolios". The real-time combination earned a lower CER "in 72 of 103 cases". | **[P]** PDF read |
| Harvey et al. (2018), *JPM* 45(1):14–33 | Sharpe gains only for "risk assets" (equity, credit); for bonds, currencies and commodities the effect is "negligible"; volatility scaling reduces extreme returns in all classes. | **[S]** |
| DeMiguel, Martín-Utrera & Uppal (2024), *JF* | Confirms single-factor volatility management fails out of sample after costs; a conditional *multifactor* version survives. | **[S]** |
| Madras School of Economics WP 242 (2023), Indian factors | Volatility-managed Indian factors earn higher returns, strongest for momentum; excerpt shows in-sample spanning tests only. | **[S]**; out-of-sample / after-cost results **NOT VERIFIED** |

**Verdict for the engine:** volatility *targeting as a timing signal* is **NOT ADMISSIBLE**. The best out-of-sample test refutes the
single-asset version. No Indian out-of-sample test after STT, loads and capital-gains tax was found. Volatility can still be
**displayed** as risk context (risk-methodology §2). A pre-registered Indian test (rolling estimation, one-day lag, real costs and tax,
walk-forward splits, compared with buy-and-hold at equal average exposure) is a research backlog item, not a feature.

## 6. Drawdown control, stop-losses and trend rules

| Evidence | Finding | Status |
|---|---|---|
| Kaminski & Lo (2014), *J. Financial Markets* 18:234–254 | "If prices follow random walks, stop-loss rules always decrease expected returns. If prices exhibit momentum, such rules can add value by reducing losses." | **[S]** ScienceDirect highlights |
| Moskowitz, Ooi & Pedersen (2012), *JFE* 104(2):228–250 | "Significant 'time series momentum'" in all 58 futures; persistence 1–12 months, partial reversal later. | **[S]** |
| Hurst, Ooi & Pedersen (2017), *JPM* 44(1):15–29 | Trend-following positive in every decade since 1880; did well in 8 of the 10 largest 60/40 drawdowns. Diversified **long/short futures**, not a long-only Indian equity investor. | **[S]** |
| Faber (2007, updated 2013), *J. Wealth Mgmt* | 10-month moving-average rule: "equity-like returns with bond-like volatility and drawdown" on US and global asset classes. Critiqued by Marmi et al. with bootstrap tests. | **[S]** |
| Daniel & Moskowitz (2016), *JFE* 122(2):221–247 | Momentum suffers "infrequent and persistent strings of negative returns", in "panic states… when market volatility is high, and… coincide with market rebounds". | **[S]** |
| NSE momentum whitepaper (Apr 2026) | Since Apr-2005 to 27-Feb-2026: Nifty200 Momentum 30 19.19 % vs Nifty 200 15.08 %; Midcap150 Momentum 50 23.00 % vs 17.24 %. "The maximum drawdowns of Nifty200 Momentum 30, Nifty Midcap150 Momentum 50, and Nifty500 Momentum 50 were 68%, 73%, and 70%" vs parents 64 %, 73 %, 64 %. | **[P]** PDF read |

**What this means:**

- A **fixed percentage stop-loss on a diversified Indian index fund** has no Indian evidence of adding value after tax. Each stop
  realises gains (20 % STCG if ≤ 12 months) and requires a re-entry rule, which is itself a timing signal. **Not admissible.**
- **Trend and momentum tilts** have the strongest global evidence among timing approaches. The Indian momentum indices did *not*
  reduce drawdown (68–73 % vs 64–73 %). Their excess return is mostly in back-calculated history and is gross of cost and tax.
  **Not admissible as a signal** until the engine can run its own walk-forward, after-tax test on officially sourced data with
  explicit rights.
- **Admissible drawdown control is structural, not predictive:** choose the equity share so that the historical worst in-window
  drawdown in ₹ fits the user's loss budget, and hold the emergency fund outside the portfolio. This is arithmetic on history.

## 7. Position sizing: Kelly and fractional Kelly

**Evidence:**

- MacLean, Thorp & Ziemba (2010), *Quantitative Finance* 10:681–687: Kelly maximises long-run growth, but "its suggested wagers may be
  very large", it "can be very risky in the short term", and full-Kelly wealth does not stochastically dominate fractional-Kelly
  wealth **[S]**.
- Thorp, interview with Schwager: "if you bet half the Kelly amount, you get about three-quarters of the return with half the
  volatility"; "overbetting is really punishing—you get both a lower growth rate and much higher variability" **[S]**, quotes read on
  valueinvestingworld.com.

**Computed illustration [C]** (continuous-time Kelly for one risky asset, f* = (μ − r) / σ²; floats; for exposition only, not an
engine output):

| Input | Value | Source |
|---|---|---|
| Nifty 50 TRI geometric return | 12.12 % | factsheet **[P]** |
| σ | 22.39 % | factsheet **[P]** |
| Arithmetic mean ≈ g + σ²/2 | 14.63 % | formula |
| r (91-day T-bill index since 1993) | 7.11 % | companion **[P]** |
| Sample length | 30.9 years | 03-Nov-1995 → 30-Sep-2026 |
| **Full Kelly f*** | **1.50** (150 % equity, i.e. leverage) | formula |
| Half Kelly | 0.75 | formula |
| Standard error of the mean, σ/√T | 4.03 pp | formula |
| **f* at mean ± 2 SE** | **−0.11 to 3.11** | formula |

**Verdict:** the plausible range spans "hold no equity" to "lever 3×", so Kelly cannot set an allocation. For single stocks the
uncertainty is larger. **Admissible use:** a warning only — "your planned equity exposure exceeds even an optimistic full-Kelly
estimate; overbetting lowers long-run growth" — computed in Decimal with inputs and their sources displayed. Never a recommended size.
Leverage and F&O stay out of scope (companion RT-6; SEBI found 87.7–92.8 % of individual F&O traders lost money).

## 8. Emergency fund

| Item | Evidence | Status |
|---|---|---|
| Size | Investor.gov (US SEC): "set a savings goal, such as three to six months of living expenses"; emergency savings help you avoid "turning to credit or selling investments when you don't want to". | **[S]** (page returned HTTP 403 to fetch; quote from search extract) |
| Indian regulator guidance on months | A planner's blog attributes "3 to 6 months" to SEBI investor-education guidelines without a document link. | **NOT VERIFIED** — do not attribute to SEBI |
| Bank deposit insurance | "Each depositor in a bank is insured upto a maximum of ₹ 5,00,000 (Rupees Five Lakhs) for both principal and interest amount held by him in the same right and same capacity"; balances across branches of one bank are aggregated. | **[P]** dicgc.org.in/FAQs |
| Liquid funds as a reserve | Graded exit load for 6 days; redemption usually next business day; some AMCs offer instant redemption up to a cap (cap NOT VERIFIED). | **[P]/[S]** companion tax doc |
| Tax | Debt MF units bought on/after 01-Apr-2023 are taxed at slab rate regardless of holding period. | **[P]** companion tax doc |

**Engine specification:**

- The **emergency-fund gate** runs before any growth allocation view. Inputs: monthly essential expenses (user-entered), number of
  months (user-chosen; default range 3–6 shown with the Investor.gov citation, labelled as US-regulator guidance), and current liquid
  reserves (savings, sweep FDs, liquid/overnight funds).
- If reserves are below target, the growth views still render but carry a top banner with the ₹ shortfall. The engine never
  recommends a product for the reserve. It shows each holding's liquidity ladder (companion requirement C), including locked
  instruments such as ELSS treated as illiquid (see `docs/audit/ecc-panel/python-reviewer.md`).
- Flag concentration above ₹5,00,000 per bank as outside DICGC cover.

## 9. Signal admissibility summary

| Technique | Evidence quality (global) | India, out-of-sample, after cost and tax | Engine status |
|---|---|---|---|
| User-chosen strategic allocation + consequences | Strong | Historical arithmetic available | **ALLOWED** (policy analytics, not a signal) |
| Calendar + band rebalancing rule | Strong for risk control | Tax arithmetic available | **ALLOWED** as the user's rule; alert wording "your rule triggered" |
| Emergency-fund gate | Consensus guidance | n/a | **ALLOWED** |
| Loss-budget-constrained equity share | Arithmetic on history | Available | **ALLOWED** |
| Mean-variance optimisation | Weak out of sample | None | **ABSTAIN** |
| Volatility targeting / timing | Contested; fails single-asset out-of-sample | None found | **ABSTAIN** |
| Stop-loss rules | Theoretical: value only under momentum | None found | **ABSTAIN** |
| Trend / momentum timing or tilts | Strongest global timing evidence; crash risk | None found (NSE data back-calculated, gross) | **ABSTAIN** pending own walk-forward test |
| Kelly sizing | Sound theory; inputs unknowable | n/a | **WARNING ONLY** |
| Leverage / F&O | Regulator data: most retail traders lose | SEBI studies | **BLOCKED** |

**Minimum bar for promoting any ABSTAIN row to a signal** (consistent with `docs/forecasting/validation-methodology.md`):
pre-registered rule and parameters; officially sourced data with recorded rights; walk-forward or expanding-window out-of-sample
period of at least one full cycle including 2008 and 2020; one-period execution lag; STT, exit loads, expense ratio and capital-gains
tax under the rule tables in force at each date; benchmark = buy-and-hold at equal average exposure; report CAGR, max drawdown,
turnover, after-tax terminal wealth and the count of independent periods; a multiple-testing adjustment for every variant tried.

## 10. User decisions and open items

- **Loss budget:** the largest ₹ fall (and duration) the user will sit through without selling. This, not the 20–25 % aim, should set
  the equity share.
- **Emergency-fund months** (3, 6 or other) and essential monthly expenses.
- **Rebalancing rule:** keep the 5 pp / annual default or set custom bands; whether to allow tax-triggering sales or rebalance with
  cash flows only.
- **Whether to fund research** into an India-specific out-of-sample test of trend/momentum and volatility rules, accepting that a
  valid result may be "no improvement".
- Open (NOT VERIFIED): Nifty momentum index launch dates; any SEBI/AMFI primary document on emergency-fund sizing; an Indian
  rebalancing-frequency study; the MSE WP-242 out-of-sample results.

---

## 11. Sources (all accessed 2026-10-15)

| # | Source | URL | Short quote / what was used | Status |
|---|---|---|---|---|
| 1 | NSE Indices, Nifty 50 factsheet, 30-Sep-2026 | https://www.niftyindices.com/Factsheet/ind_nifty50.pdf | "Base Date November 03, 1995"; Total Return since inception "12.12"; Std. Deviation since inception "22.39" | [P] |
| 2 | NSE Indices, "The Science of Momentum" whitepaper, Apr-2026 | https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf | "The Nifty200 Momentum 30 has returned 19.19% versus 15.08% for Nifty 200"; "maximum drawdowns … were 68%, 73%, and 70%" | [P] |
| 3 | Companion report (this repo) | docs/research/return-target-feasibility.md | Rolling-window tables, drawdowns, gold, G-sec, T-bill, SPIVA, SEBI F&O | [C]/[P] as tagged there |
| 4 | Companion tax report (this repo) | docs/research/indian-instruments-and-tax.md | STCG 20 %, LTCG 12.5 % above ₹1.25 lakh, debt MF slab, exit-load cap | [P] as tagged there |
| 5 | Vanguard, Best practices for portfolio rebalancing (2010) | https://www.financieelonafhankelijkblog.nl/wp-content/uploads/2021/11/Vanguard-ISGPORE.pdf (mirror; original vanguard.com URL not reached) | "The primary goal of a rebalancing strategy is to minimize risk…"; "annual or semiannual monitoring, with rebalancing at 5% thresholds" | [P] (mirror copy) |
| 6 | Cederburg, O'Doherty, Wang & Yan (2020) JFE 138(1) | https://www.lehigh.edu/~xuy219/research/COWY.pdf ; https://doi.org/10.1016/j.jfineco.2020.04.015 | "reasonable out-of-sample versions generally earn lower certainty equivalent returns and Sharpe ratios" | [P] |
| 7 | Moreira & Muir (2017) JF 72(4) | https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513 | "take less risk when volatility is high produce large alphas" | [S] |
| 8 | Harvey et al. (2018) JPM 45(1) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538 | Sharpe gains only for "risk assets"; fewer tail events | [S] |
| 9 | DeMiguel, Martín-Utrera & Uppal (2024) JF | https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13395 | Single-factor volatility management fails OOS; multifactor survives | [S] |
| 10 | Madras School of Economics WP 242 (2023) | https://www.mse.ac.in/wp-content/uploads/2023/09/WORKING-PAPER-242.pdf | Volatility-managed Indian factors, in-sample | [S] |
| 11 | Kaminski & Lo (2014) J. Financial Markets 18 | https://www.sciencedirect.com/science/article/abs/pii/S138641811300030X | "If prices follow random walks, stop-loss rules always decrease expected returns" | [S] |
| 12 | Moskowitz, Ooi & Pedersen (2012) JFE 104(2) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463 | "significant 'time series momentum' … for each of the 58 liquid instruments" | [S] |
| 13 | Hurst, Ooi & Pedersen (2017) JPM 44(1) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026 | "performed well in 8 out of 10 of the largest crisis periods" | [S] |
| 14 | Faber (2007/2013) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461 | "equity-like returns with bond-like volatility and drawdown" | [S] |
| 15 | Daniel & Moskowitz (2016) JFE 122(2) | https://econpapers.repec.org/RePEc:eee:jfinec:v:122:y:2016:i:2:p:221-247 | "infrequent and persistent strings of negative returns" | [S] |
| 16 | Ibbotson & Kaplan (2000) FAJ 56(1) | https://ideas.repec.org/a/taf/ufajxx/v56y2000i1p26-33.html | "about 90 percent… about 40 percent… about 100 percent" | [S] |
| 17 | DeMiguel, Garlappi & Uppal (2009) RFS 22(5) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1376199 | "out-of-sample performance of the sample-based mean-variance model" | [S] |
| 18 | MacLean, Thorp & Ziemba (2010) Quant. Finance 10 | https://www.researchgate.net/publication/227623956 | Kelly "can be very risky in the short term" | [S] |
| 19 | Thorp quotes (Schwager interview) | https://www.valueinvestingworld.com/2013/05/ed-thorp-jack-schwager-and-kelly.html | "half the Kelly amount… about three-quarters of the return with half the volatility" | [S] (page read) |
| 20 | Investor.gov, World Investor Week 2023 bulletin | https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/WorldInvestorWeek2023 | "three to six months of living expenses" | [S] |
| 21 | DICGC FAQs | https://www.dicgc.org.in/FAQs | "insured upto a maximum of ₹ 5,00,000 (Rupees Five Lakhs)" | [P] |
| 22 | Trading Economics, India 10Y yield | https://tradingeconomics.com/india/government-bond-yield | 7.39 % on 15-Oct-2026 (OTC quote) | [S] |
| 23 | Morningstar India, fund vs investor return | https://www.morningstar.in/posts/68668/fund-return-versus-investor-return.aspx | Behaviour gap, larger for volatile/thematic funds (context only; no number used) | [S] |
