# Indian Short-Horizon Instruments and Taxation: Research Reference

- **Prepared:** 2026-10-15 (research snapshot; no rule here is guaranteed current after this date)
- **Scope:** Resident individual investors (not HUF, NRI, company, trust). Horizons of 1, 3, 6 and 12 months.
- **Author role:** Agent B (Indian investment domain research). **Not tax or investment advice.** Every tax rule must be signed off by a Chartered Accountant before the app uses it in a computation shown to users (see §9).
- **Fetched content was treated as untrusted data.** Numbers come only from cited sources; nothing was estimated.

## 0. How to read this document

### Verification status vocabulary (used everywhere below)

| Status | Meaning |
|---|---|
| `VERIFIED-PRIMARY` | Read directly in the official document at the cited URL (Budget memorandum, SEBI regulation/circular PDF, RBI FAQ, DICGC FAQ, NSI scheme rules) during this research session. |
| `VERIFIED-SECONDARY` | The official source is cited, but the text could not be fetched (HTTP 403 from incometaxindia.gov.in, pib.gov.in and some sebi.gov.in pages). The rule was confirmed through several independent secondary sources that agreed with each other and that quote the official text. |
| `NOT VERIFIED` | No authoritative confirmation was found, or the sources conflict. **The app must not compute with this rule** without CA sign-off. |

### Legal regime as of 2026-10-15 (critical context)

1. **The Income-tax Act, 2025 came into force on 1 April 2026 and replaces the Income-tax Act, 1961.** Income up to 31-Mar-2026 is taxed under the 1961 Act, and income from 1-Apr-2026 under the 2025 Act. The 2025 Act uses "tax year" in place of "previous year/assessment year". `VERIFIED-SECONDARY`: CBDT press release dated 1-Apr-2026 at https://www.incometaxindia.gov.in/documents/d/guest/press-release-income-tax-act-2025-comes-into-force-from-01-april-2026-pdf (HTTP 403 when fetched). The Finance Bill 2026 memorandum (`VERIFIED-PRIMARY`, https://www.indiabudget.gov.in/doc/memo.pdf) confirms this independently: it amends "the Income-tax Act, 2025" and sets rates "for the tax year 2026-27".
2. **The government states the 2025 Act renumbers and rewrites the law without changing tax policy.** Rates carried over. Section-number mapping used in this document:

   | 1961 Act | 2025 Act | Status |
   |---|---|---|
   | 111A (equity STCG) | 196 | `VERIFIED-PRIMARY` (FB2026 memo refers to "capital gains under sections 196, 197 and 198") |
   | 112 (other LTCG) | 197 | `VERIFIED-PRIMARY` (same) |
   | 112A (equity LTCG) | 198 | `VERIFIED-PRIMARY` (same) |
   | 115BAC (new regime) | 202 | `VERIFIED-PRIMARY` (FB2026 memo) |
   | 10(15)/47(viic) SGB redemption exemption | 70(1)(x) | `VERIFIED-PRIMARY` (FB2026 memo) |
   | 87A (rebate) | 156 | `VERIFIED-SECONDARY` (several mapping tables). Note that the FB2026 memo also uses "section 156" in an unrelated demand-notice context, so CA confirmation is needed. |
   | 50AA (specified MF, MLD, unlisted bonds) | 76 | `NOT VERIFIED` (secondary sources only; taxtmi ready reckoner) |
   | 194A (TDS on interest) | 393(1) Table Sl. 5 | `VERIFIED-SECONDARY` (the FB2026 memo cites s.393(4) for TDS exemptions; the threshold table itself was not read in primary) |
   | 194K (TDS on MF income) | 393(1) | `NOT VERIFIED` (exact Table serial number) |

3. **Budget 2026-27 (Finance Act 2026; Presidential assent 30-Mar-2026, `VERIFIED-SECONDARY`)** made no change to slab rates or to capital gains rates. It changed four investment-relevant items, all from 1-Apr-2026 (`VERIFIED-PRIMARY`, FB2026 memo):
   - STT on F&O increased.
   - Buyback consideration is now taxed as capital gains, not as dividend.
   - The SGB redemption exemption is restricted to original subscribers who hold continuously until maturity.
   - Interest expense is no longer deductible against dividend or MF income.
   - **Caveat:** 32 amendments were made to the Bill in the Lok Sabha. The memorandum describes the Bill as introduced, so a CA must confirm that no investment-relevant clause changed on passage.

---

## 1. Mutual funds: common mechanics

### 1.1 Regulatory base (changed in 2026)

- **SEBI (Mutual Funds) Regulations, 2026** replaced the 1996 Regulations from 1-Apr-2026. The version read here is amended up to 7-Jul-2026. Source: https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1783933012694.pdf (`VERIFIED-PRIMARY`).
- **Scheme categorisation:** SEBI circular HO/24/13/15(2)2026-IMD-RAC4/I/5764/2026 dated **26-Feb-2026** replaces the 2017 categorisation (SEBI/HO/IMD/DF3/CIR/P/2017/114, 6-Oct-2017). Existing schemes had **6 months from the circular date** to comply, so by about 26-Aug-2026. Source: https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1772079826878.pdf (`VERIFIED-PRIMARY`). Several debt categories were renamed: "Duration" became "Term". A May-2026 SEBI circular states this content is now consolidated as clause 3.7 of the MF Master Circular (`VERIFIED-SECONDARY`).
  - **Simplification flag:** Scheme names in AMFI data may still carry the old labels (e.g. "Low Duration") in historical NAV files. The app needs an old-name to new-name alias map (§1.3).

### 1.2 Costs

**Base Expense Ratio (BER).** BER replaces "TER" under the 2026 Regulations, reg. 66(7) (`VERIFIED-PRIMARY`). Statutory levies (GST, STT, stamp duty) and transaction costs are **excluded** from BER and charged separately, so BER cannot be compared like-for-like with historical TER.

| Scheme type (open-ended) | Max BER |
|---|---|
| Index fund / ETF | 0.90% |
| FoF investing in liquid/index/ETF schemes (incl. underlying) | 0.90% |
| FoF with ≥65% in equity-oriented schemes | 2.10% |
| Other FoF | 1.85% |
| Close-ended equity-oriented | 1.00% |
| Close-ended other than equity-oriented | 0.80% |

| AUM slab (open-ended, other schemes) | Equity-oriented | Other than equity-oriented (debt, liquid etc.) |
|---|---|---|
| First ₹500 cr | 2.10% | 1.85% |
| Next ₹250 cr | 1.90% | 1.65% |
| Next ₹1,250 cr | 1.60% | 1.40% |
| Next ₹3,000 cr | 1.50% | 1.25% |
| Next ₹5,000 cr | 1.40% | 1.15% |
| Next ₹40,000 cr | −0.05% per ₹5,000 cr increment | same |
| Balance | 0.95% | 0.70% |

- **Brokerage** may be charged over BER up to **0.06%** (cash market) and **0.02%** (derivatives) of trade value (`VERIFIED-PRIMARY`).
- **Exit load cap:** an open-ended scheme's exit load "shall not exceed three per cent" (`VERIFIED-PRIMARY`, 2026 Regulations). Exit loads are scheme-specific and set out in each SID. **The app must read the actual exit load from the scheme document, not infer it from the category.**
- **Liquid fund graded exit load** (SEBI circular of 20-Sep-2019; rates agreed by SEBI in its letter to AMFI dated Oct-2019; effective about 20-Oct-2019):

  | Redemption on | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | Day 6 | Day 7+ |
  |---|---|---|---|---|---|---|---|
  | Load (% of redemption proceeds) | 0.0070% | 0.0065% | 0.0060% | 0.0055% | 0.0050% | 0.0045% | Nil |

  `VERIFIED-SECONDARY`. The figures match the HDFC Liquid Fund SID (https://files.hdfcfund.com/s3fs-public/2023-11/HDFC%20Liquid%20Fund.pdf) and press coverage. SEBI asked AMFI to review the structure annually. **Whether it is unchanged after the 2026 Regulations is `NOT VERIFIED`.**
- **Stamp duty:** 0.005% on issue of MF units, covering purchases, SIP/STP instalments, switch-ins and dividend reinvestment. Effective 1-Jul-2020 under the Indian Stamp Act as amended by Finance Act 2019. Redemptions are not charged. `VERIFIED-SECONDARY` (no government URL fetched; SEBI letter dated 29-Jun-2020 is referenced by AMCs).
- **STT:** 0.001% on redemption (sale to the MF) of units of an **equity-oriented** scheme, payable by the seller and collected by the MF. Nil on debt schemes. Nil on purchase. `VERIFIED-SECONDARY` (Finance (No.2) Act 2004 s.98; the FB2026 memo confirms MFs collect STT "in respect of equity-oriented schemes" and changed only F&O rates).

### 1.3 Debt scheme categories: SEBI circular of 26-Feb-2026, Section B

All rows are `VERIFIED-PRIMARY` (https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1772079826878.pdf). Macaulay duration (MD) is measured at portfolio level.

| # | Category (2026 name) | Old (2017) name | Definition |
|---|---|---|---|
| 1 | Overnight Fund | same | Overnight securities with 1-day maturity. Up to 5% may be held in G-secs/T-bills of ≤30 days residual maturity, for margin/collateral only. |
| 2 | Liquid Fund | same | Debt and money market securities with maturity up to 91 days. |
| 3 | Ultra Short Term Fund | Ultra Short Duration | MD 3–6 months |
| 4 | Ultra Short to Short Term Fund | Low Duration | MD 6–12 months |
| 5 | Money Market Fund | same | Money market instruments with maturity up to 1 year |
| 6 | Short Term Fund | Short Duration | MD 1–3 years |
| 7 | Medium Term Fund | Medium Duration | MD 3–4 years (1–4 years in an anticipated adverse situation) |
| 8 | Medium to Long Term Fund | Medium to Long Duration | MD 4–7 years (1–7 years adverse) |
| 9 | Long Term Fund | Long Duration | MD >7 years |
| 10 | Dynamic Term Fund | Dynamic Bond | Across durations |
| 11 | Corporate Bond Fund | same | ≥80% in corporate bonds rated AA+ and above |
| 12 | Credit Risk Fund | same | ≥65% in corporate bonds rated AA and below (excl. AA+) |
| 13 | Banking and PSU Debt Fund | Banking and PSU Fund | ≥80% in debt of banks, PSUs, PFIs and municipal bonds |
| 14 | Gilt Fund | same | ≥80% in G-secs, across maturity |
| 15 | 10-year Constant Maturity Gilt Fund | Gilt with 10y constant duration | ≥80% in G-secs, portfolio MD equal to 10 years |
| 16 | Floating Interest Rates Fund | Floater Fund | ≥65% in floating-rate instruments, including fixed-rate instruments swapped to floating |
| 17 | Sectoral (debt) Fund | *new* | ≥80% in one sector (Financial Services, Energy, Infrastructure, Housing or Real Estate), only AA+ and above |

- Residual portions may be invested in InvITs, **except** in Overnight, Liquid, Ultra-Short, Low-Duration and Money Market funds (`VERIFIED-PRIMARY`).
- **Short-horizon relevance:** categories 1–5 are the only ones whose stated mandate keeps interest-rate sensitivity at or below about 1 year. Categories 6–17 can lose money over 1–12 months when yields rise.

### 1.4 Hybrid, equity and other schemes (only those relevant here)

All `VERIFIED-PRIMARY`, same circular.

- **Arbitrage Fund:** ≥65% in equity and equity-related instruments, following an arbitrage strategy.
  - **New in 2026:** debt exposure is limited to G-secs with maturity under 1 year and repo of government bonds only. No InvITs.
- **Conservative Hybrid:** 10–25% equity, 75–90% debt.
- **Balanced Hybrid:** 40–60% each; no arbitrage.
- **Aggressive Hybrid:** 65–80% equity.
- **Equity Savings:** ≥65% equity incl. arbitrage, net equity 15–40%, ≥10% debt.
- **Multi Asset Allocation:** at least 3 asset classes, ≥10% each.
- **Index Funds/ETFs:** ≥95% in index constituents.
- **FoFs (overseas/domestic):** ≥95% in the underlying fund(s).
- **Gold ETF / Gold FoF** fall under "Other schemes"/passive. Their tax treatment is in §8, rule MF-OTHER-*.
- **International FoF:** a FoF with ≥95% in overseas fund(s). SEBI/RBI industry-wide overseas investment limits have repeatedly caused subscription suspensions in the past.
  - `NOT VERIFIED`: current status of overseas limits as of Oct-2026. The app must treat subscription availability as a live data input.
- Solution-oriented schemes were discontinued on 26-Feb-2026. Life Cycle Funds were introduced.

### 1.5 Transaction timing

- **Cut-off times and NAV applicability:** SEBI circulars SEBI/HO/IMD/DF2/CIR/P/2020/175 (17-Sep-2020) and /2020/253 (31-Dec-2020), effective **1-Feb-2021**. `VERIFIED-SECONDARY`.

  | Scheme type | Purchase cut-off | NAV if funds are realised before cut-off | Redemption cut-off |
  |---|---|---|---|
  | Liquid and Overnight | 1:30 pm | NAV of the day before the next business day (commonly described as "T-1" relative to allotment) | 3:00 pm |
  | All other schemes | 3:00 pm | Same-day NAV | 3:00 pm (same-day NAV) |

  - **For purchases, all amounts follow the realisation-of-funds rule:** NAV is set by when money reaches the MF's bank account. The earlier ₹2 lakh threshold was removed.
  - Platforms and exchanges often impose earlier cut-offs (e.g. 12:30 pm / 2:30 pm).
  - **Simplification flag:** the app should treat NAV date as "uncertain ±1 business day" unless it has the actual allotment date.
- **Redemption payout:** within **3 working days** of redemption, or 5 working days for schemes with ≥80% overseas assets. SEBI circular SEBI/HO/IMD/IMD-I DOF2/P/CIR/2022/161 dated 25-Nov-2022. Exceptions are listed in AMFI communication dated 16-Jan-2023. Delay interest is 15% p.a. `VERIFIED-SECONDARY`.
  - In practice, liquid/overnight funds usually pay T+1 and equity funds T+2. **Those are practice, not regulation.** The app must use the regulatory maximum (T+3 working days) for any "money available by" guarantee.
- **Dividend (IDCW) payout:** within 7 working days of record date (same circular). `VERIFIED-SECONDARY`.

### 1.6 Risk labelling

- **Riskometer:** six levels: Low, Low to Moderate, Moderate, Moderately High, High, Very High. Evaluated monthly and disclosed within 10 days of month end. SEBI/HO/IMD/DF3/CIR/P/2020/197 dated 5-Oct-2020, effective 1-Jan-2021. `VERIFIED-SECONDARY`.
- **Potential Risk Class (PRC) matrix** for debt schemes. SEBI/HO/IMD/IMD-II DOF3/P/CIR/2021/573 dated 7-Jun-2021, applicable from 1-Dec-2021. `VERIFIED-SECONDARY`. The PRC shows the **maximum** risk the scheme may take, not current risk.
  - **Interest-rate axis:**
    - Class I: MD ≤1 yr, every instrument ≤3 yrs residual maturity.
    - Class II: MD ≤3 yrs, every instrument ≤7 yrs residual maturity.
    - Class III: any MD.
  - **Credit axis (Credit Risk Value, CRV):**
    - Class A: CRV ≥12.
    - Class B: CRV ≥10.
    - Class C: CRV <10.
    - CRV per instrument: G-sec/SDL/T-bill/repo/TREPS/cash = 13, AAA = 12, AA+ = 11, AA = 10, AA- = 9, A+ = 8, A = 7, A- = 6, BBB+ = 5, BBB = 4, BBB- = 3, unrated = 2, below investment grade = 1.
  - **Cells** run from A-I (lowest) to C-III (highest). Moving above the chosen cell is a change of fundamental attributes.
  - **App rule suggestion:** for 1–12 month goals, show PRC alongside riskometer. A-I and B-I are the only cells structurally consistent with short horizons.

### 1.7 Debt funds are NOT risk-free: documented events

- **IL&FS default (2018):** IL&FS group defaults led to NAV write-downs in debt schemes holding its paper. SEBI then permitted **side-pocketing** (segregated portfolio) by circular dated **28-Dec-2018**:
  - A segregated portfolio can be created on a credit event (downgrade below investment grade).
  - Trustee approval is required within 1 day.
  - The segregated units are listed within 10 days.
  - Existing investors get units in both portfolios, and **new investors buy only the main portfolio**.
  - `VERIFIED-SECONDARY`.
- **Franklin Templeton (23-Apr-2020):** six debt schemes were wound up, citing illiquidity, which locked up more than ₹25,000–30,000 crore. Sources vary on the exact figure, so **no single number is asserted here**.
  - The schemes were Low Duration, Dynamic Accrual, Credit Risk, Short Term Income Plan, Ultra Short Bond and Income Opportunities.
  - The Supreme Court ordered distribution through SBI MF.
  - SEBI's order of 7-Jun-2021 imposed penalties and a 2-year ban on new debt schemes.
  - `VERIFIED-SECONDARY` (news coverage; SEBI order URL not fetched).
  - **Lesson for the app:** even "ultra-short" and "low duration" labels lost liquidity. Liquidity is not guaranteed by category.
- **Other risk drivers for debt funds:** interest-rate risk (duration), credit risk, liquidity risk (redemption pressure), concentration risk, and reinvestment risk.

---

## 2. Instrument cards: mutual funds

Card fields: **Mechanics · Liquidity · Costs · Risks · Tax rule IDs (§8) · Horizon suitability (1/3/6/12 m)**.

Suitability notes describe **structural fit only**. They are not recommendations. "Poor fit" means the instrument's normal risk or cost profile is mismatched to the horizon.

### 2.1 Overnight Fund
- **Mechanics:** 1-day instruments (TREPS, reverse repo). NAV accrues almost linearly.
- **Liquidity:** redemption is usually paid next business day; regulatory maximum is 3 working days. No exit load is typical (check SID).
- **Costs:** BER (other-than-equity slab). Stamp duty 0.005%.
- **Risks:** very low duration risk. Counterparty/settlement risk is mitigated by CCIL. Yield floats daily with the policy/overnight rate.
- **Tax:** MF-DEBT-SMF.
- **1m:** good fit · **3m:** fit · **6m:** fit (yield usually below liquid) · **12m:** fit but likely lower yield than alternatives.

### 2.2 Liquid Fund
- **Mechanics:** instruments up to 91 days. Valued on mark-to-market.
- **Liquidity:** 1:30 pm purchase cut-off. Graded exit load for 6 days (§1.2). Some AMCs offer instant redemption (up to a cap) as a scheme feature (`NOT VERIFIED` current cap).
- **Costs:** BER, exit load in the first 6 days, stamp duty.
- **Risks:** low but non-zero credit risk (CP/CD issuers). The IL&FS 2018 episode affected some liquid funds via CP holdings (`VERIFIED-SECONDARY`, general coverage).
- **Tax:** MF-DEBT-SMF.
- **1m:** good fit (after day 7) · **3m:** good fit · **6m:** fit · **12m:** fit.

### 2.3 Money Market Fund
- **Mechanics:** money market instruments up to 1-year maturity.
- **Liquidity:** T+3 maximum; exit load per SID.
- **Risks:** low duration, CP/CD credit risk.
- **Tax:** MF-DEBT-SMF.
- **1m:** acceptable · **3m:** fit · **6m:** good fit · **12m:** good fit.

### 2.4 Ultra Short Term (MD 3–6 m) and Ultra Short to Short Term (MD 6–12 m)
- **Mechanics:** duration-banded.
- **Risks:** more credit latitude than liquid funds (check PRC). Franklin's Ultra Short Bond and Low Duration funds were among the 2020 wound-up schemes.
- **Tax:** MF-DEBT-SMF.
- **1m:** poor fit (MTM noise vs tiny accrual) · **3m:** acceptable · **6m:** fit · **12m:** fit.

### 2.5 Short Term, Corporate Bond, Banking & PSU (MD roughly 1–4 years; CB/B&PSU duration not fixed by category)
- **Risks:** duration risk. A rate rise can produce negative returns over 1–6 months.
- **Tax:** MF-DEBT-SMF.
- **1m/3m:** poor fit · **6m:** caution · **12m:** acceptable only if the user tolerates MTM loss.

### 2.6 Credit Risk Fund
- **Risks:** by mandate ≥65% in AA-and-below. Default and liquidity events are concentrated here (Franklin's Credit Risk Fund was wound up in 2020).
- **Tax:** MF-DEBT-SMF.
- **1–12 m:** poor fit.

### 2.7 Gilt / 10-yr Constant Maturity Gilt / Dynamic Term / Medium-Long / Long Term
- **Risks:** no material credit risk for gilt funds, but **high** interest-rate risk. A 10-year constant-maturity fund's price moves by roughly MD × Δyield.
  - **Simplification flag:** the "MD × Δy" approximation ignores convexity and should strictly use modified duration.
- **Tax:** MF-DEBT-SMF.
- **1–12 m:** poor fit for capital-protection goals.

### 2.8 Floating Interest Rates Fund
- Coupon resets reduce duration risk; credit and swap-basis risk remain.
- **Tax:** MF-DEBT-SMF.
- **1m:** poor · **3–12m:** acceptable/caution.

### 2.9 Arbitrage Fund
- **Mechanics:** buys stock in the cash market and sells the equivalent futures, capturing the basis that converges at expiry. Returns track short-term money-market rates loosely and depend on the futures basis, which can compress.
- **Debt sleeve:** G-secs under 1 year and G-sec repo only, from 2026 (`VERIFIED-PRIMARY`).
- **Liquidity:** T+3 maximum. Exit loads of about 0.25% within 15–30 days are common.
  - `NOT VERIFIED` as a rule: each scheme sets its own load. Read the SID.
- **Costs:** BER (equity slab), brokerage, STT on underlying trades (borne inside NAV), 0.001% STT on redemption, stamp duty.
- **Risks:**
  - Basis compression can produce very low or occasionally negative short-period returns.
  - Rollover cost.
  - Execution risk.
  - Tax-status risk if equity exposure falls below 65% (gross, including hedged positions; hedged positions count toward 65% per prevailing practice, `NOT VERIFIED` as a statutory reading).
- **Tax:** MF-EQ-STCG / MF-EQ-LTCG (equity-oriented fund treatment). This is the main reason the category exists.
- **1m:** poor (exit load window + basis noise) · **3m:** acceptable · **6m:** fit · **12m:** fit (STCG at 20% if redeemed ≤12 months; LTCG only after >12 months).

### 2.10 Equity / Index fund / Equity ETF
- **Risks:** equity drawdown. Not suitable for capital-protection horizons ≤12 months.
- **Tax:** MF-EQ-*.
- **1–12 m:** poor fit for any goal needing the principal intact.

### 2.11 Hybrid funds
- **Conservative Hybrid:** 10–25% equity, so after 1-Apr-2025 it is **neither** equity-oriented **nor** a specified MF (provided debt is not >65%; at 75–90% debt it IS >65% debt, so it is likely a specified MF).
  - `NOT VERIFIED`: CA must classify.
- **Balanced / Multi-asset (35–65% equity, debt ≤65%):** "other" MF. See MF-OTHER-*.
- **Equity Savings (≥65% gross equity):** equity-oriented.

### 2.12 Gold ETF / Gold FoF; International FoF
- **Risks:** gold price and USD/INR. Not capital-protected. International FoF adds foreign market risk, FX and subscription-suspension risk.
- **Tax:** MF-OTHER-* (not a specified MF after 1-Apr-2025, provided ≤65% in debt).
- **1–12 m:** poor fit for capital protection.

---

## 3. Government securities

### 3.1 Treasury Bills (91/182/364-day)
- **Mechanics:** zero-coupon, issued at a discount and redeemed at face value. Auctioned weekly, usually Wednesday. Settlement T+1. Minimum ₹10,000 and multiples of ₹10,000. Source: RBI G-sec FAQ, https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=711 (`VERIFIED-PRIMARY`; FAQ appears dated around 2020, so re-check minimums on RBI Retail Direct).
- **Price/yield convention: actual/365, NOT 364.** `VERIFIED-PRIMARY` (same RBI FAQ: "Yield = [(FV − Price)/Price] × (365/Days to maturity) × 100").
  - **Correction to the brief:** the formula `price = 100/(1 + y·d/364)` is **wrong** for India. Use:
    - `price = 100 / (1 + y × d / 365)`
    - `y = (100 − P)/P × 365/d`
    - `d` = actual days from settlement to maturity.
  - The "364" in "364-day T-bill" is the tenor, not the day-count base.
- **Retail access:** RBI Retail Direct (launched Nov-2021) uses non-competitive bidding, at the weighted-average price of competitive bids. Auto-bidding and re-investment auto-bidding on T-bills were added in 2025 (re-investment announced 6-Aug-2025). Secondary trading is via NDS-OM odd-lot/RFQ. Portal: https://rbiretaildirect.org.in. `VERIFIED-SECONDARY`.
- **Liquidity:** hold to maturity is the realistic assumption. Secondary odd-lot liquidity for retail is thin (`NOT VERIFIED` quantitatively).
- **Risks:** sovereign credit (negligible in INR terms), MTM if sold early, and reinvestment risk.
- **Tax:** TBILL-01 (**classification unresolved; CA required**). No TDS on redemption (`VERIFIED-SECONDARY`).
- **1m:** not directly available (shortest tenor 91 days; secondary purchase of a near-maturity bill is possible but illiquid) · **3m:** good fit (91-day) · **6m:** good fit (182-day) · **12m:** good fit (364-day).

### 3.2 Dated G-Secs, SDLs
- **Mechanics:** fixed coupon paid **semi-annually** on face value.
- **Accrued interest day count: 30/360.** `VERIFIED-PRIMARY` (RBI FAQ: "The day count convention followed is 30/360").
  - Trades are quoted clean. Settlement amount = (clean + accrued) × FV/100.
  - **Simplification flag:** the precise 30/360 variant (end-of-month handling) is not specified in the FAQ, so the app should cite FIMMDA conventions before implementing.
  - **App rule suggestion:** keep the T-bill (actual/365, money-market yield) and dated G-sec (30/360, semi-annual compounding) conventions separate in code.
- **SDLs:** state government securities. Same structure; semi-annual interest (`VERIFIED-PRIMARY`, RBI FAQ).
- **Settlement:** T+1 (`VERIFIED-PRIMARY`).
- **Risks:** interest-rate (MTM) risk for any exit before maturity, and liquidity in off-the-run papers.
- **Tax:** interest is taxed at slab (INT-SLAB-01). Capital gains: GSEC-CG-ST / GSEC-CG-LT (listed security).
  - TDS on interest on Central Govt securities: generally exempt under the old s.193 proviso. `NOT VERIFIED` under the 2025 Act.
- **1–6m:** poor fit unless the residual maturity matches the horizon · **12m:** fit only if residual maturity ≈ 12 m.

### 3.3 STRIPS
- Coupon and principal flows of an existing G-sec, separated into zero-coupon securities. Created from existing securities, not auctioned (`VERIFIED-PRIMARY`, RBI FAQ).
- Retail liquidity is low.
- **Tax:** `NOT VERIFIED` (likely deep-discount/zero-coupon treatment). CA required.

### 3.4 Floating Rate Bonds (GoI FRB)
- Coupon reset at pre-announced intervals (`VERIFIED-PRIMARY`, RBI FAQ).
- Long tenor; not a short-horizon product.

### 3.5 Sovereign Gold Bonds
- **New issuance has stopped.** The last tranche was 2023-24 Series IV (Feb-2024). Discontinuation was confirmed at the post-Budget briefing on 1-Feb-2025. No tranche has been announced for FY2025-26 or FY2026-27 (`VERIFIED-SECONDARY`).
- Existing bonds pay 2.5% p.a. on the issue price and trade on exchanges (illiquid, discount/premium to gold).
- **Tax (changed from TY 2026-27):** the redemption-at-maturity CG exemption now applies **only** to original subscribers who held continuously until maturity, for all SGB series. Section 70(1)(x) of the 2025 Act; FB2026 memo (`VERIFIED-PRIMARY`). A secondary-market buyer redeeming at maturity is therefore taxable (SGB-02). Interest is taxed at slab.
- **1–12 m:** poor fit (gold price risk, illiquid).

### 3.6 RBI Floating Rate Savings Bonds, 2020 (Taxable)
- 7-year tenor. Coupon = NSC rate + 0.35%, reset each 1-Jan and 1-Jul.
- Coupon for Jul–Dec 2026 is **8.05%** (NSC 7.70% + 0.35%).
- Premature encashment is available only to senior citizens, after a 4/5/6-year lock-in (ages 80+/70–80/60–70), with a penalty of 50% of the last coupon.
- Operational guidelines: RBI/2026-27/06 dated 2-Apr-2026. Source: https://rbi.org.in/Scripts/NotificationUser.aspx?Id=13365&Mode=0 (`VERIFIED-SECONDARY`).
- **1–12 m:** not suitable (7-year lock).

---

## 4. Corporate bonds / NCDs

- **Face value:**
  - Reduced from ₹10 lakh to ₹1 lakh (Oct-2022).
  - Then to **₹10,000** for privately placed, plain-vanilla, interest/dividend-bearing NCDs/NCRPS, subject to merchant banker due diligence. SEBI circular SEBI/HO/DDHS/DDHS-PoD-1/P/CIR/2024/94 dated 3-Jul-2024.
  - Extended to zero-coupon NCDs on 18-Dec-2025.
  - `VERIFIED-SECONDARY`.
- **Online Bond Platform Providers (OBPP):**
  - Regulated by Regulation 51A of the NCS Regulations and SEBI circular SEBI/HO/DDHS/DDHS-RACPOD1/P/CIR/2022/154 dated 14-Nov-2022.
  - An OBPP must be registered as a stockbroker (debt segment).
  - Only listed debt securities or those proposed to be listed via public issue may be offered.
  - Trades are routed through the exchange RFQ platform and settled via NSCCL/ICCL, typically T+1.
  - SEBI consultation of 5-May-2026 proposes further changes.
  - `VERIFIED-SECONDARY`.
- **Credit ratings:** issued by SEBI-registered CRAs. A rating is an opinion of default probability, not a guarantee.
  - Recovery after default is uncertain and slow (IBC process). `NOT VERIFIED`: no authoritative recovery-rate statistic was sourced, so **the app must not display a recovery rate**.
- **Liquidity:** secondary market for retail lots is thin. Exit before maturity may be at a material discount (`NOT VERIFIED` quantitatively).
- **Risks:**
  - Credit and default risk.
  - Call risk.
  - Liquidity risk.
  - Interest-rate risk.
  - Platform mis-selling risk: SEBI warned in 2025 about unregistered platforms.
- **Tax:** interest at slab (INT-SLAB-01).
  - **Listed** bonds: STCG at slab if held ≤12 months; LTCG 12.5% without indexation if held >12 months (BOND-L-ST / BOND-L-LT).
  - **Unlisted** bonds/debentures: deemed STCG at slab regardless of holding period, for transfers/redemptions on or after 23-Jul-2024 (BOND-UL).
  - TDS on interest on listed debentures: s.193 threshold ₹10,000 (FB2025 memo, `VERIFIED-PRIMARY` for the 1961 Act).
- **1–6 m:** poor fit unless maturity matches the horizon · **12m:** caution (credit, liquidity).

---

## 5. Deposits

### 5.1 Bank fixed deposits
- **Premature withdrawal:**
  - Interest is paid at the rate applicable for the period the deposit actually ran, not the contracted rate.
  - No interest is paid if the deposit is withdrawn before the minimum tenor.
  - The penalty is set by each bank's Board-approved policy and must be disclosed at acceptance; otherwise no penalty can be charged.
  - Source: RBI Master Direction (Interest Rate on Deposits) Directions, 2025 (RBI/2025-26/134, 1-Apr-2025), https://rbidocs.rbi.org.in/rdocs/notification/PDFs/MD134346AD90D94CE4C2683A4CC4D6A6B5576.PDF (`VERIFIED-SECONDARY`).
  - **"Typical" penalty:** 0.5%–1% below the applicable rate is common market practice, but **this is not a regulatory number** (`NOT VERIFIED`). The app must take the penalty per bank as input.
- **DICGC insurance:**
  - **₹5,00,000 per depositor per bank**, covering principal **and** interest combined.
  - Deposits are aggregated across **all branches** of the same bank, held "in the same right and same capacity".
  - Different capacities (e.g. guardian, partner, joint account with a different name order) are insured separately.
  - The bank's dues are set off first.
  - In effect since 4-Feb-2020. Payout under All-Inclusive Directions is within 90 days; on liquidation, within 2 months of receiving the claim list.
  - Source: https://www.dicgc.org.in/FAQs (`VERIFIED-PRIMARY` for the limit, aggregation, principal+interest and capacity rule; the 4-Feb-2020 date is `VERIFIED-SECONDARY`).
  - No increase above ₹5 lakh was found as of Oct-2026.
- **Coverage scope:** covers commercial banks (incl. SFBs, RRBs, foreign bank branches in India) and cooperative banks. **NBFC/HFC deposits are NOT covered.**
- **Tax:** interest at slab (INT-SLAB-01).
  - TDS (TDS-INT-01): 10% where interest from one bank in a FY exceeds **₹50,000**, or **₹1,00,000 for senior citizens**. Applies from 1-Apr-2025 (FB2025 memo, `VERIFIED-PRIMARY`). Carried into s.393 of the 2025 Act (`VERIFIED-SECONDARY`).
  - Higher TDS applies without PAN (`NOT VERIFIED` rate under the 2025 Act). Form 15G/15H declarations are possible (form numbers under the 2025 Rules are `NOT VERIFIED`).
- **1m:** minimum tenors of 7 days are common · **3/6/12m:** good structural fit; principal certainty within the DICGC limit.

### 5.2 NBFC / HFC deposits
- Not DICGC-insured. Credit rating matters.
- **Premature withdrawal within 3 months of deposit** (from 1-Jan-2025; RBI circular on harmonisation of HFC/NBFC regulations, Aug-2024):
  - Deposits up to ₹10,000 are repayable in full without interest.
  - Critical illness: 100% of principal without interest.
  - Otherwise up to 50% of principal or ₹5 lakh, whichever is lower, without interest.
  - `VERIFIED-SECONDARY`.
- Rules after 3 months are per the RBI public-deposit directions and the company's terms (`NOT VERIFIED`).
- **Tax:** interest at slab. TDS threshold is ₹10,000 for non-bank payers ("other cases", FB2025 memo, `VERIFIED-PRIMARY`).
- **1–12 m:** caution (credit risk, no insurance).

### 5.3 Small savings schemes (long-horizon; NOT 1–12 month options)
- Rates are set **quarterly** by the Ministry of Finance (DEA).
- For **Q3 FY2026-27 (1-Oct to 31-Dec-2026), rates were unchanged** from the previous quarter (announced 30-Sep-2026; `VERIFIED-SECONDARY`, press coverage; DEA notification not fetched).

| Scheme | Rate Q3 FY27 | Lock-in / tenor (summary) | Status |
|---|---|---|---|
| PPF | 7.1% | 15 years. Withdrawals/premature closure only on specified grounds. | rate `VERIFIED-SECONDARY`; tenor from PPF Scheme rules (https://www.nsiindia.gov.in/writereaddata/FileUploads/PPF.pdf) `VERIFIED-SECONDARY` |
| NSC VIII | 7.7% | 5 years. Premature encashment only on death/court order/pledge forfeiture. | rate `VERIFIED-SECONDARY`; rules https://www.nsiindia.gov.in/writereaddata/SchemeRules/NationalSavingsCertificatesRule.pdf |
| SCSS | 8.2% | 5 years. Premature closure: <1 yr, interest paid is recovered; 1–2 yrs, 1.5% of deposit deducted; ≥2 yrs, 1% deducted. | penalty `VERIFIED-PRIMARY` (https://www.nsiindia.gov.in/writereaddata/SchemeRules/SeniorCitizensSavingsSchemeRule.pdf). The ₹15 lakh cap in that PDF is outdated; the **₹30 lakh** cap (Budget 2023) is `NOT VERIFIED` against current rule text. |
| POMIS | 7.4% | 5 years | rate `VERIFIED-SECONDARY`; premature rules `NOT VERIFIED` |
| KVP | 7.5% (matures in 115 months) | Premature encashment after a lock-in | rate `VERIFIED-SECONDARY`; lock-in `NOT VERIFIED` |
| SSY | 8.2% | 21 years; girl child only | rate `VERIFIED-SECONDARY` |
| PO Time Deposit 1 yr | 6.9% | 1 year | `VERIFIED-SECONDARY`. This is the only small-savings product near a 12-month horizon, and its premature rules are `NOT VERIFIED`. |

---

## 6. Arbitrage funds: mechanics and tax (summary)

- **Mechanics:** see §2.9. Gross equity exposure (hedged) ≥65% qualifies the scheme as an "equity-oriented fund" for tax.
- **Tax:**
  - Gains on redemption ≤12 months: **STCG 20%** (s.111A, now s.196) from 23-Jul-2024; 15% before.
  - >12 months: **LTCG 12.5%** above the ₹1.25 lakh annual exemption (s.112A, now s.198), shared with listed equity and equity MFs.
  - STT 0.001% on redemption.
  - Surcharge on these gains is capped at 15%, plus 4% cess.
  - The Section 87A rebate does **not** offset tax on these gains (§8 REBATE-01).
- **Simplification flag:** whether arbitrage positions satisfy the "65% in equity shares of domestic listed companies" test is a scheme-level fact. AMCs disclose the scheme's tax status, and the app should read it from the AMC rather than compute it.

---

## 7. Cross-cutting tax mechanics

### 7.1 New-regime slab rates (default regime)

Applies to FY2025-26 (1961 Act s.115BAC(1A)) and Tax Year 2026-27 (2025 Act s.202).

| Total income (₹) | Rate |
|---|---|
| 0 – 4,00,000 | Nil |
| 4,00,001 – 8,00,000 | 5% |
| 8,00,001 – 12,00,000 | 10% |
| 12,00,001 – 16,00,000 | 15% |
| 16,00,001 – 20,00,000 | 20% |
| 20,00,001 – 24,00,000 | 25% |
| > 24,00,000 | 30% |

- `VERIFIED-PRIMARY`: FB2025 memo introduced these slabs for AY 2026-27 (https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf). FB2026 memo restates them unchanged for TY 2026-27 (https://www.indiabudget.gov.in/doc/memo.pdf).
- The old regime is available by option (s.202(4)) and is **not modelled** here (simplification).

### 7.2 Rebate, surcharge and cess

- **Rebate (87A → s.156):** up to ₹60,000 where total income ≤ ₹12,00,000 under the new regime, with marginal relief. **The rebate is not available on tax at special rates (e.g. s.111A, s.112) and is capped at tax computed at slab rates.** From AY 2026-27 (FB2025 memo, `VERIFIED-PRIMARY`).
  - `NOT VERIFIED`: whether special-rate gains count toward the ₹12 lakh total-income ceiling (sources conflict).
  - `NOT VERIFIED`: treatment of s.112A gains for the rebate (the s.112A(6) carve-out).
- **Surcharge (new regime):**

  | Total income | Surcharge |
  |---|---|
  | >₹50 lakh to ₹1 cr | 10% |
  | >₹1 cr to ₹2 cr | 15% |
  | >₹2 cr | 25% (new-regime cap) |

  Surcharge on dividend income and on capital gains u/s 196/197/198 (old 111A/112/112A) is capped at **15%**, with marginal relief (FB2026 memo, `VERIFIED-PRIMARY`).
- **Health & Education Cess:** 4% on tax plus surcharge (FB2025/FB2026 memos, `VERIFIED-PRIMARY`).

### 7.3 Holding periods (transfers on/after 23-Jul-2024)

- **12 months** for listed securities (incl. units of equity-oriented funds); **24 months** for all other assets.
- Source: FB2024 memo, https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf (`VERIFIED-PRIMARY`).
- `NOT VERIFIED`: whether listed **non-equity** ETF units (gold ETF, international ETF) take the 12-month period. Secondary sources say yes; the statutory text of s.2(42A) as amended was not read.

### 7.4 TDS on MF income

- **TDS on MF dividends (IDCW):** 10% where income from units exceeds **₹10,000** in a FY (raised from ₹5,000 by Finance Act 2025, from 1-Apr-2025). FB2025 memo (`VERIFIED-PRIMARY`).
- **No TDS on MF redemption for residents** (`NOT VERIFIED` under the 2025 Act; generally the position under the 1961 Act).
- From TY 2025-26, **no deduction** is allowed for interest expense against dividend or MF income (FB2026 memo, `VERIFIED-PRIMARY`).

---

## 8. Tax rule table (machine-friendly)

Conventions:
- `rate` is the base rate before surcharge and cess.
- `SLAB` means taxed at the investor's applicable slab rate.
- Dates are ISO-8601.
- An empty `effective_to` means in force as of 2026-10-15.
- `holding_period_threshold` is the period that must be **exceeded** (">") for long-term treatment.
- `src:FB24` = https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- `src:FB25` = https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- `src:FB26` = https://www.indiabudget.gov.in/doc/memo.pdf
- `src:ITA25` = CBDT press release, Income-tax Act 2025 in force: https://www.incometaxindia.gov.in/documents/d/guest/press-release-income-tax-act-2025-comes-into-force-from-01-april-2026-pdf

| rule_id | instrument_class | condition | holding_period_threshold | rate | exemption | effective_from | effective_to | source_url | verification_status |
|---|---|---|---|---|---|---|---|---|---|
| LAW-ITA25 | ALL | Income arising on/after date governed by Income-tax Act 2025 (s.196/197/198/202 numbering) | n/a | n/a | n/a | 2026-04-01 | | src:ITA25; src:FB26 | VERIFIED-SECONDARY (commencement); VERIFIED-PRIMARY (FB26 references) |
| EQ-STCG-OLD | listed equity / equity-oriented MF / arbitrage MF (STT paid) | transfer ≤12m | 12m | 15% | none | (pre-2024) | 2024-07-22 | src:FB24 | VERIFIED-PRIMARY |
| EQ-STCG | listed equity / equity-oriented MF / arbitrage MF (STT paid) | transfer ≤12m; s.111A → s.196 | 12m | 20% | none | 2024-07-23 | | src:FB24; src:FB26 | VERIFIED-PRIMARY |
| EQ-LTCG-OLD | same | transfer >12m; s.112A | 12m | 10% | ₹1,00,000/yr | (pre-2024) | 2024-07-22 | src:FB24 | VERIFIED-PRIMARY |
| EQ-LTCG | same | transfer >12m; s.112A → s.198 | 12m | 12.5% | ₹1,25,000/yr aggregate (FY2024-25 onward) | 2024-07-23 | | src:FB24; src:FB26 | VERIFIED-PRIMARY |
| MF-DEBT-SMF | specified MF: >65% debt & money market (or FoF ≥65% in such funds) — overnight, liquid, money market, all debt categories, likely conservative hybrid | units acquired on/after 2023-04-01; deemed STCG regardless of holding (s.50AA → s.76?) | none (always ST) | SLAB | none | 2023-04-01 (s.50AA); definition >65% debt from AY2026-27 (FY2025-26) | | src:FB24 | VERIFIED-PRIMARY (definition, dates); NOT VERIFIED (2025 Act section no.) |
| MF-SMF-DEF-OLD | specified MF (old definition: ≤35% in domestic equity shares) | applies to AY up to 2025-26 (FY ≤2024-25) | n/a | SLAB | none | 2023-04-01 | 2025-03-31 | src:FB24 | VERIFIED-PRIMARY |
| MF-DEBT-PRE2023-ST | debt MF units acquired before 2023-04-01 | transfer ≤24m (from 23-Jul-2024; 36m earlier) | 24m | SLAB | none | 2024-07-23 | | src:FB24 | VERIFIED-SECONDARY (memo text on 24m for "all other assets"; application to MF units needs CA) |
| MF-DEBT-PRE2023-LT | debt MF units acquired before 2023-04-01 | transfer >24m; s.112 → s.197; no indexation | 24m | 12.5% | none | 2024-07-23 | | src:FB24 | VERIFIED-SECONDARY |
| MF-OTHER-ST | non-equity-oriented, non-specified MF (gold ETF/FoF, intl FoF, balanced/multi-asset with ≤65% debt) | transfer ≤ threshold | 24m (12m for listed ETF units — see note) | SLAB | none | 2025-04-01 (definition change) | | src:FB24 | NOT VERIFIED (12m vs 24m for listed ETFs; classification of each hybrid) |
| MF-OTHER-LT | same | transfer > threshold; s.112 → s.197 | 24m (12m listed ETF?) | 12.5% | none | 2025-04-01 | | src:FB24 | NOT VERIFIED (threshold); VERIFIED-PRIMARY (12.5% rate) |
| BOND-L-ST | listed bonds/debentures, listed G-sec/SDL, SGB sold on exchange | transfer ≤12m | 12m | SLAB | none | 2024-07-23 | | src:FB24 | VERIFIED-PRIMARY |
| BOND-L-LT | listed bonds/debentures (and listed G-sec) | transfer >12m; no indexation | 12m | 12.5% | none | 2024-07-23 | | src:FB24 | VERIFIED-PRIMARY |
| BOND-L-LT-OLD | listed bonds/debentures | transfer >12m, before 23-Jul-2024 | 12m | 10% w/o indexation (s.112 proviso) | none | (pre-2024) | 2024-07-22 | src:FB24 | NOT VERIFIED (old 10% rate not in memo excerpt read; memo says "20% without indexation" for bonds generally) |
| BOND-UL | unlisted bonds/debentures | transfer/redemption/maturity on/after 23-Jul-2024; deemed STCG (s.50AA) | none (always ST) | SLAB | none | 2024-07-23 | | src:FB24 | VERIFIED-PRIMARY |
| GSEC-CG | dated G-sec/SDL (listed) | follows BOND-L-ST/LT | 12m | SLAB / 12.5% | none | 2024-07-23 | | src:FB24 | NOT VERIFIED (whether G-secs bought via RBI Retail Direct are "listed" — CA) |
| TBILL-01 | Treasury bill (91/182/364d) | discount gain on maturity or sale | n/a (<12m always) | SLAB | none | — | | none authoritative found | NOT VERIFIED (head of income: capital gains vs interest/other sources vs deep-discount accrual; rate is SLAB under all readings) |
| INT-SLAB-01 | FD (bank/NBFC/HFC), PO TD, bond/G-sec coupon, FRSB, SGB 2.5% coupon | interest income | n/a | SLAB | none (new regime: no 80TTB) | — | | src:FB25 (TDS context) | VERIFIED-SECONDARY |
| TDS-INT-01 | bank / co-op bank / post office interest | TDS if interest per payer per FY > threshold | n/a | 10% TDS | threshold ₹50,000 (₹1,00,000 senior citizen) | 2025-04-01 | | src:FB25 | VERIFIED-PRIMARY (1961 Act); VERIFIED-SECONDARY (carried to s.393, 2025 Act) |
| TDS-INT-OLD | same | as above | n/a | 10% | ₹40,000 (₹50,000 senior) | (pre-2025) | 2025-03-31 | src:FB25 | VERIFIED-PRIMARY |
| TDS-INT-02 | interest from other payers (e.g., NBFC/HFC deposit) | per payer per FY | n/a | 10% | ₹10,000 | 2025-04-01 | | src:FB25 | VERIFIED-PRIMARY |
| TDS-SEC-01 | interest on securities (s.193), incl. listed debentures | per FY | n/a | 10% | ₹10,000 | 2025-04-01 | | src:FB25 | VERIFIED-PRIMARY |
| TDS-MF-01 | MF IDCW/dividend (s.194K) | per FY | n/a | 10% | ₹10,000 | 2025-04-01 | | src:FB25 | VERIFIED-PRIMARY |
| SGB-01 | SGB redemption at maturity by original subscriber held continuously | redemption on maturity | until maturity | exempt | full | 2026-04-01 (restriction) | | src:FB26 | VERIFIED-PRIMARY |
| SGB-02 | SGB acquired in secondary market, redeemed at maturity | TY2026-27 onward | 12m (listed) | SLAB / 12.5% | none | 2026-04-01 | | src:FB26 | VERIFIED-PRIMARY (no exemption); NOT VERIFIED (computation) |
| REBATE-01 | new-regime resident individual | total income ≤ ₹12,00,000; rebate ≤ ₹60,000; not on special-rate tax (111A/112 → 196/197) | n/a | rebate | up to ₹60,000 | AY2026-27 (FY2025-26) | | src:FB25 | VERIFIED-PRIMARY (rule); NOT VERIFIED (112A interplay; whether special-rate income counts toward ₹12 lakh limit) |
| SLAB-NEW-01 | new regime | slabs 0-4L nil / 4-8L 5% / 8-12L 10% / 12-16L 15% / 16-20L 20% / 20-24L 25% / >24L 30% | n/a | per slab | n/a | 2025-04-01 (FY2025-26) | | src:FB25; src:FB26 | VERIFIED-PRIMARY |
| SURCH-01 | new regime individual | 10% (>50L), 15% (>1cr), 25% (>2cr); capped at 15% on dividend & s.196/197/198 gains | n/a | surcharge | n/a | FY2025-26, TY2026-27 | | src:FB26 | VERIFIED-PRIMARY |
| CESS-01 | all | on tax + surcharge | n/a | 4% | none | (in force) | | src:FB26 | VERIFIED-PRIMARY |
| STT-MF-01 | equity-oriented MF redemption to fund | seller pays | n/a | 0.001% of value | none | (in force; not changed by FB26) | | src:FB26 (context) | VERIFIED-SECONDARY |
| STAMP-MF-01 | all MF unit issuance | purchase/SIP/switch-in/reinvest | n/a | 0.005% of amount | none | 2020-07-01 | | (Indian Stamp Act as amended by Finance Act 2019; no gov URL fetched) | VERIFIED-SECONDARY |
| DIV-INTEXP-01 | dividend/MF income | interest expense deduction | n/a | not allowed | n/a | TY2025-26 per memo text (sic) / 2026-04-01 | | src:FB26 | VERIFIED-PRIMARY (memo text says "apply for tax year 2025-26 onwards" — inconsistent; CA) |
| BUYBACK-01 | listed equity buyback (non-promoter) | consideration taxed as capital gains | 12m | 20% / 12.5% | per EQ rules | 2026-04-01 | | src:FB26 | VERIFIED-PRIMARY (as Bill); VERIFIED-SECONDARY (enacted) |

---

## 9. Open questions requiring Chartered Accountant review

1. **T-bill discount (TBILL-01):** is it taxed as capital gains (STCG at slab), as interest/income from other sources, or under deep-discount accrual? The rate is SLAB in all cases. Head of income matters for loss set-off, ITR schedule and FY-spanning bills.
2. **Section 50AA → 2025 Act section number** and confirmation that the >65% debt "specified mutual fund" definition was carried forward verbatim.
3. **Holding period for listed non-equity ETFs** (gold ETF, international ETF) after 23-Jul-2024: 12 or 24 months? And for unlisted FoFs (gold/international): 24 months?
4. **Hybrid classification:**
   - Conservative hybrid (75–90% debt) is likely a specified MF.
   - Balanced/multi-asset funds with 35–65% equity are "other".
   - The classification test uses the **annual average of daily closing** figures (FB2024 memo). How should the app handle a scheme whose average crosses 65% mid-year?
5. **87A rebate:**
   - Does special-rate capital gains income count toward the ₹12 lakh total-income ceiling?
   - What is the position for s.112A/198 gains?
   - Confirm the s.156 mapping under the 2025 Act.
6. **Debt MF units bought before 1-Apr-2023:** confirm the 24-month threshold and 12.5% without indexation for transfers on/after 23-Jul-2024.
7. **G-secs held in an RBI Retail Direct Gilt account:** "listed security" for the 12-month threshold? TDS position on G-sec interest under s.393?
8. **SGB secondary buyers redeeming at maturity from TY2026-27:** computation, cost basis and holding period.
9. **Effective-date anomaly** in the FB2026 memo for the interest-expense disallowance ("1st April 2026 … apply for tax year 2025-26 onwards").
10. **Finance Act 2026 as enacted:** confirm no investment-relevant change among the 32 Lok Sabha amendments versus the memorandum.
11. **Transition (FY2025-26 vs TY2026-27):** confirm the app should apply 1961-Act section labels to transfers up to 31-Mar-2026 and 2025-Act labels after. Confirm no change in carry-forward of capital losses across Acts.
12. **Arbitrage funds:** confirm that hedged (arbitrage) equity positions count toward the 65% equity-oriented test under the 2025 Act definition.
13. **Higher TDS without PAN, and Form 15G/15H equivalents** under the Income-tax Rules 2026.

---

## 10. Simplifications flagged (the app must surface these)

- Only resident individuals under the **new regime** are modelled. The old regime, HUF, NRI and corporate investors are out of scope.
- The ₹1.25 lakh LTCG exemption is a **single annual pool** shared across all listed equity, equity MF and arbitrage gains. The app must not apply it per holding.
- Surcharge marginal relief is not modelled in this document.
- Set-off and carry-forward of capital losses are not modelled (STCL may be set off against STCG/LTCG; LTCL only against LTCG; 8-year carry-forward under the 1961 Act — `NOT VERIFIED` under the 2025 Act).
- Riskometer and PRC labels are point-in-time or maximum-risk labels. Neither predicts returns.
- Exit loads, premature-withdrawal penalties, minimum FD tenors and instant-redemption caps are **scheme- or bank-specific inputs**, not constants.
- Redemption settlement uses the **regulatory maximum** (T+3 working days for domestic MFs), not observed practice.
- T-bill pricing uses the RBI actual/365 money-market yield. Dated G-sec accrual uses 30/360 (end-of-month variant `NOT VERIFIED`).

---

## 11. Source index

**Primary (read during this session):**
- Finance Bill 2026 memorandum: https://www.indiabudget.gov.in/doc/memo.pdf
- Finance Bill 2025 memorandum: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- Finance (No.2) Bill 2024 memorandum: https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- SEBI categorisation circular, 26-Feb-2026: https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1772079826878.pdf
- SEBI (Mutual Funds) Regulations 2026, amended to 7-Jul-2026: https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1783933012694.pdf
- RBI G-sec market FAQ: https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=711
- DICGC FAQs: https://www.dicgc.org.in/FAQs
- SCSS rules (NSI): https://www.nsiindia.gov.in/writereaddata/SchemeRules/SeniorCitizensSavingsSchemeRule.pdf

**Official URLs cited but not fetchable (403) or confirmed via secondary sources:**
- CBDT press release on the Income-tax Act 2025 (above)
- RBI MD Interest Rate on Deposits 2025: https://rbidocs.rbi.org.in/rdocs/notification/PDFs/MD134346AD90D94CE4C2683A4CC4D6A6B5576.PDF
- RBI FRSB 2020(T): https://rbi.org.in/Scripts/NotificationUser.aspx?Id=13365&Mode=0
- SEBI circulars cited by number: riskometer 2020/197; PRC 2021/573; cut-off 2020/175 and 2020/253; redemption timelines 2022/161; OBPP 2022/154; NCD face value 2024/94; side-pocketing 28-Dec-2018. Search each on https://www.sebi.gov.in
- NSI scheme rules: https://www.nsiindia.gov.in
- RBI Retail Direct: https://rbiretaildirect.org.in
