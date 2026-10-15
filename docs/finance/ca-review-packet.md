# Chartered Accountant Review Packet: Indian Tax Rules

| Field | Value |
|---|---|
| Prepared | 2026-10-15 (Track 6: verification against primary sources) |
| Rule table | `backend/src/iip/rules/tax/india.yaml`, `table_version: india-tax@2026-10-15.r2` (65 rules) |
| Scope | Resident individuals, **new regime only**, FY2024-25 to TY2026-27 (transfers up to 31-Mar-2027) |
| Status after Track 6 | **51 P** (verified against a primary text), **6 S** (secondary only), **8 NV** (not verified). Before Track 6: 31 P, 14 S, 20 NV |
| Requested of the reviewer | Tick Yes / No / Correction on every rule card in section 4, and answer the open questions in section 2 |

> **This packet is not tax advice.** It records what the app assumes and what the statute text says where it was read.
> The app is a personal tool. The worked examples use a **fictional** profile (30 % slab, no surcharge, unless stated).

## How to use this packet (about 1-2 hours)

1. Read **section 2** (open questions). Items marked OPEN need your answer. Items marked RESOLVED were answered from the
   statute text, but please confirm the reading.
2. Read **section 3** (corrections made in Track 6). These changed numbers in the app.
3. Go through the **rule cards in section 4**, grouped by instrument. Each card states:
   - what the app assumes, in plain English;
   - the 1961-Act and 2025-Act sections;
   - the transfer/income dates the rule covers;
   - the verification status and the citation (URL, section/clause, quoted phrase);
   - a worked example **computed by the app's engine** (`iip.engine.tax.compute_tax`), with exact rupee figures;
   - a line for your answer.
4. Return the packet. Section 5 explains how the developer applies your corrections.

Conventions on the cards:
- "Effective" dates are **transfer (or income) dates, inclusive**. "in force" means no end date as of 15-Oct-2026.
- Rates are **before** surcharge and the 4 % Health and Education Cess. Each example shows tax + surcharge + cess.
- "SLAB" means taxed at the investor's slab rate. Examples use 30 % for SLAB income.
- `Rs` amounts use Indian digit grouping.
- Where a section reads "-", the app records no specific section (the gain is taxed at slab under the general charge).

---

## 1. Primary texts read in Track 6

Every P status added or re-cited in Track 6 rests on one of these documents. Each was downloaded and its text searched;
the quoted phrases on the rule cards come from that text. SHA-256 prefixes identify the exact copies read.

| Short name | Document | URL read | SHA-256 (first 16) |
|---|---|---|---|
| [ITA25] | Income-tax Act 2025 (30 of 2025) **as amended by Finance Act 2026**, CBDT consolidated text | https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf. The direct fetch returns HTTP 403, so it was read via the Internet Archive capture of that exact URL (`web.archive.org/web/20260612085646id_/…`) | `d54a0ed6a91673d1` |
| [ITA25-G] | Income-tax Act 2025 **as enacted**, Gazette CG-DL-E-22082025-265620 (assent 21-Aug-2025) | https://resource.cdn.icai.org/87647dtc-aps2139-inceome-tax-act-2025.pdf (ICAI-hosted copy of the Gazette; used only to corroborate [ITA25]) | `7acfb16fd7f3db8b` |
| [FA26] | Finance Act 2026 (No. 4 of 2026), Gazette CG-DL-E-31032026-271439 (assent 30-Mar-2026) | https://www.incometaxindia.gov.in/documents/d/guest/finance-act-2026-pdf-1 (via Internet Archive capture 20261006014925) | `f01136356e61b253` |
| [FA25] | Finance Act 2025 (No. 7 of 2025), Gazette CG-DL-E-29032025-262125 (assent 29-Mar-2025) | https://thc.nic.in/Central%20Governmental%20Acts/Finance%20Act,%202025.pdf (Gazette copy on a government host; egazette.gov.in link not found) | `1b7c61b42a330291` |
| [FA24] | Finance (No. 2) Act 2024 (No. 15 of 2024), Gazette (assent 16-Aug-2024) | https://egazette.gov.in/WriteReadData/2024/256436.pdf | `16bf85c2bd66af15` |
| [ITA61] | Income-tax Act 1961, India Code consolidation | https://www.indiacode.nic.in/bitstream/123456789/2435/1/a1961-43.pdf (via Internet Archive capture 20260111174633; this consolidation **predates** the 2024-25 amendments, so it was used only for text those amendments did not touch, e.g. s.112A(6) and the pre-2024 wording of s.2(42A)) | `428b1b3cf2c3c09f` |
| [MEMO24] | Memorandum, Finance (No. 2) Bill 2024 | https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf | `e590279f98a9ec69` |
| [MEMO26] | Memorandum, Finance Bill 2026 (as introduced) | https://www.indiabudget.gov.in/doc/memo.pdf | `78f81425565e23b1` |

Not reachable or not read: the CBDT press release on commencement (HTTP 403, no archive copy fetched); the CBDT
section-wise HTML pages (HTTP 403); the Income-tax Rules 2026; any CBDT circular on T-bills or G-sec listing.

---

## 2. Open questions (research §9), with what the primary texts settle

Status key: **RESOLVED** = answered by statute text read in Track 6 (please confirm the reading);
**PARTLY** = part answered, rest open; **OPEN** = needs your view.

| # | Question | Status | What the primary text says | Rules affected | Your answer |
|---|---|---|---|---|---|
| 1 | **T-bill discount**: capital gains, interest/other sources, or deep-discount accrual? | **OPEN** | No provision read names T-bills. [ITA25] s.2(112) limits "zero coupon bond" to bonds "issued by any infrastructure capital company or infrastructure capital fund or infrastructure debt fund or public sector company or scheduled bank", so a T-bill is not one. s.2(59) defines interest as "interest payable in any manner for moneys borrowed or debt incurred", which may cover the discount, but nothing says so expressly. The app taxes the discount at SLAB under every reading. | TBILL-01/* | |
| 2 | **s.50AA → 2025 Act section**, and is the >65 % debt definition carried forward verbatim? | **RESOLVED** | [ITA25] **s.76**. s.76(2)(a): "a unit of a Specified Mutual Fund acquired on or after the 1st April, 2023"; s.76(2)(b): unlisted bonds/debentures from 23-Jul-2024; s.76(5)(b): "invests more than 65% of its total proceeds in debt and money market instruments or a fund which invests 65% or more of its total proceeds in units of such Mutual Fund", on "the annual average of the daily closing figures". Same substance as s.50AA after [FA24] s.21. | MF-DEBT-SMF/ITA2025, BOND-UL/ITA2025 | |
| 3 | **Holding period for listed non-equity ETFs** (gold, international) after 23-Jul-2024: 12 or 24 months? Unlisted FoFs: 24? | **RESOLVED** | 1961 Act: [FA24] s.3(b)(i) changed "thirty-six months" to "twenty-four months" and s.3(b)(ii)(A) **omitted "(other than a unit)"** from the 12-month proviso, whose base text [ITA61] reads "a security (other than a unit) listed in a recognised stock exchange". [MEMO24]: "For all listed securities, the holding period is proposed to be 12 months and for all other assets, it shall be 24 months". 2025 Act: s.2(101)(b)(i) gives 12 months to a "security listed in a recognised stock exchange in India". So **listed ETF units: 12 months; unlisted FoF units: 24 months**. The app encodes only the unlisted case; listed non-equity ETFs **abstain** (no rule). | MF-OTHER-*, MF-DEBT-PRE2023-* | |
| 4 | **Hybrid classification** (conservative hybrid; balanced/multi-asset 35-65 % equity); a scheme whose average crosses 65 % mid-year | **PARTLY** | The tests are statutory and measured on annual averages: specified fund = debt > 65 % (daily closing figures, s.76(5)(b)(i)); equity-oriented = ≥ 65 % domestic listed equity (s.198(8), "annual average of the monthly averages of the opening and closing figures"). Which side a given scheme falls on is a **data** question for each scheme and year. OPEN: what the app should do before the year's average is known (today it uses the category default and labels it `TAX_CLASS_INFERRED_FROM_CATEGORY`). | MF-*, candidates | |
| 5 | **87A / s.156 rebate**: do special-rate gains count toward the Rs 12 lakh ceiling? s.112A/198 gains? s.156 mapping? | **PARTLY** | Mapping: **s.156** (rebate "in case of certain individuals"). TY2026-27: s.156(2)(a) "the income does not exceed twelve lakh rupees, 100% of the income-tax payable or ₹ 60000, whichever is less"; s.156(3) "shall not exceed income-tax payable as per the rates provided in section 202(1)"; s.198(7) "the rebate under section 156 shall be allowed from the income-tax on the total income as reduced by tax payable on such capital gains". FY2025-26: [FA25] s.20 (87A second proviso, cap at tax under s.115BAC(1A) rates) and [ITA61] s.112A(6). So **no rebate against tax on s.111A/112/112A (196/197/198) gains**. Ceiling: the text uses "total income", which on our reading includes those gains. **Please confirm the ceiling reading.** The engine does not apply the rebate. | REBATE-01/* | |
| 6 | **Debt MF units bought before 1-Apr-2023**: 24 months and 12.5 % without indexation from 23-Jul-2024? | **RESOLVED** (unlisted) | [FA24] s.3(b) (24 months), s.30 (12.5 % "for any transfer which takes place on or after the 23rd day of July, 2024"), [MEMO24] (indexation removed). [ITA25] s.2(101)(a), s.197(1)(b). s.50AA/s.76 reach only units acquired on or after 1-Apr-2023. **Listed** units (debt ETFs) take 12 months, so the app now abstains for them (correction C3). | MF-DEBT-PRE2023-* | |
| 7 | **G-secs in an RBI Retail Direct Gilt account**: "listed security"? TDS on G-sec interest under s.393? | **PARTLY** | TDS **RESOLVED**: [ITA25] s.393(4) Table Sl. No. 6(a)(iii): no TDS on interest on "any security of the Central Government or a State Government" other than the 8 % and 7.75 % Savings (Taxable) Bonds and "Floating Rate Savings Bonds, 2020 (Taxable)". Listed status **OPEN**: s.2(101)(b)(i) turns on "listed in a recognised stock exchange in India"; no primary text read says whether a Retail-Direct G-sec qualifies. **Note the risk**: if it is not listed, it is held 24 months for LTCG, and it may be an "unlisted bond" under s.76(2)(b), making every gain short-term at slab. | GSEC-CG-*, TDS-SEC-01/ITA2025 | |
| 8 | **SGB secondary buyers redeeming at maturity** from TY2026-27: computation, cost basis, holding period | **PARTLY** | No exemption **RESOLVED**: [ITA25] s.70(1)(x) as substituted by [FA26] s.43 covers only a bond "held by an individual from the date of original issue till maturity". OPEN: whether an SGB is a "security listed in a recognised stock exchange" (12 vs 24 months), and the cost basis (purchase price on the exchange?). The RBI SGB FAQ read says only that bonds "are tradable" and "only bonds held in de-mat form … can be traded in stock exchanges", and its tax text is out of date. | SGB-02-* | |
| 9 | **Effective-date anomaly** for the interest-expense disallowance ("1st April 2026 … tax year 2025-26 onwards") | **RESOLVED** | Enacted text: [FA26] s.44(b) substitutes s.93(2): "in respect of any dividend income or income from units of a Mutual Fund … no deduction shall be allowed"; CBDT footnote "Substituted by the Finance Act, 2026, w.e.f. 1-4-2026"; [FA26] s.1(2)(a) brings ss.2-129 into force on 1-Apr-2026. The 2025 Act governs only tax years from 1-Apr-2026, so the memo's "2025-26" has no practical effect. | DIV-INTEXP-01 | |
| 10 | **Finance Act 2026 as enacted**: any investment-relevant change versus the memorandum? | **PARTLY** | Read in the enacted Act: SGB exemption restriction (s.43), dividend/MF deduction bar (s.44), buyback promoter tax (s.42, s.69(2)), s.202 slabs unchanged (s.56 amends only s.202(2)), surcharge and cess tables (s.2). No difference from the memorandum was found **for the rules in this table**. A full clause-by-clause comparison was not done. | all ITA2025 rows | |
| 11 | **Transition**: 1961-Act labels up to 31-Mar-2026, 2025-Act labels after? Capital-loss carry-forward across Acts? | **RESOLVED** (reading) | [ITA25] s.536(1) repeals the 1961 Act; s.536(2)(c) keeps it for "any tax year beginning before the 1st April, 2026"; s.536(2)(n): capital losses "brought forward from the tax year beginning before the 1st April, 2026 … shall be carried forward and set off, in accordance with the manner provided in the repealed Income-tax Act". (The engine does not model loss set-off.) | LAW-*, all split rows | |
| 12 | **Arbitrage funds**: do hedged equity positions count toward the 65 % test under the 2025 Act? | **OPEN** | s.198(8)(ii) counts proceeds "invested in the equity shares of domestic companies listed on a recognised stock exchange"; it says nothing about derivative hedges. | MF-EQ-* | |
| 13 | **Higher TDS without PAN; Form 15G/15H equivalents** under the Income-tax Rules 2026 | **OPEN** | Not read (the Rules 2026 were not fetched). The app does not compute TDS. | TDS-* (information only) | |

Additional questions raised in Track 6:

| # | Question | Your answer |
|---|---|---|
| 14 | FY2024-25 equity LTCG: the Rs 1.25 lakh limit applies "on aggregate" of pre- and post-23-Jul-2024 gains ([FA24] s.31). How should it be allocated between 10 % and 12.5 % gains? (The app abstains when a year mixes both.) | |
| 15 | Equity-oriented **fund of funds** (s.198(8)(i): ≥ 90 % in a listed fund that itself holds ≥ 90 % domestic equity). The app tests only the 65 % limb on the disclosed equity share. Should FoFs be excluded until look-through data exists? | |
| 16 | Listed non-equity ETFs (gold/international/debt ETFs): should the app add 12-month rows now that the statute text is clear, or keep abstaining? | |
| 17 | Buyback (BUYBACK-01): s.69(1) makes the consideration capital gains. Is a tender-offer buyback "chargeable to securities transaction tax" so that s.196 (20 %) and s.198 (12.5 % above Rs 1.25 lakh) apply? | |
| 18 | Surcharge for TY2026-27: the app uses the Finance Act 2026 advance-tax table (s.2(12)). Confirm that is the right working assumption until the Finance Act 2027 fixes final rates. | |

---

## 3. Corrections made in Track 6 (value changes, each with a regression test)

| Id | Rule(s) | Before | After | Primary evidence | Test |
|---|---|---|---|---|---|
| C1 | EQ-LTCG-OLD, MF-EQ-LTCG-OLD (transfers 1-Apr-2024 to 22-Jul-2024) | annual exemption Rs 1,00,000 | **Rs 1,25,000** | [FA24] s.31 substituting s.112A(2)(i): "the limit of one lakh twenty-five thousand rupees shall apply on aggregate of the long-term capital gains under sub-clauses (a) and (b)", clause (a) being transfers "before the 23rd day of July, 2024" | `test_fy_2024_25_pre_23_jul_equity_ltcg_gets_1_25_lakh_exemption` (Rs 1,50,000 gain → Rs 2,600 tax, was Rs 5,200) |
| C2 | REBATE-01/FY2025-26, REBATE-01/TY2026-27 | excluded sections 111A, 112 / 196, 197 | **111A, 112, 112A / 196, 197, 198** | [ITA61] s.112A(6); [ITA25] s.198(7) | `test_rebate_exclusions_cover_every_special_rate_section` (information only; the engine does not apply the rebate) |
| C3 | MF-DEBT-PRE2023-ST/LT (both Acts) | no listed condition (24 months applied to listed debt ETFs too) | **`listed: false`**; listed units abstain | [FA24] s.3(b)(ii)(A) (omits "(other than a unit)"); [ITA25] s.2(101)(b)(i) | `test_pre_2023_debt_unit_listed_status_decides_the_threshold` |

No rate, slab, threshold or date was changed. The table version moved from (unversioned) to `india-tax@2026-10-15.r2`.

---

## 4. Rule cards

### 4.1 Which Act applies

#### `LAW-ITA61`

- **What the app assumes:** ITA1961 governs income in this period.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** - to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.536(1): "The Income-tax Act, 1961 (43 of 1961) is hereby repealed."; s.536(2)(c) keeps the repealed Act for "any tax year beginning before the 1st April, 2026". Income up to 31-Mar-2026 therefore stays under the 1961 Act. Start date not recorded (precedes every rule in this file).
- **Worked example:** Not a computation.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `LAW-ITA25`

- **What the app assumes:** ITA2025 governs income in this period.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.1(3): "Save as otherwise provided in this Act, it shall come into force on the 1st April, 2026." Corroborated by the Gazette text as enacted (Act 30 of 2025, assent 21-Aug-2025, Gazette CG-DL-E-22082025-265620). "Tax year" replaces previous/assessment year.
- **Worked example:** Not a computation.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.2 Listed equity shares (STT paid)

#### `EQ-STCG-OLD`

- **What the app assumes:** LISTED_EQUITY_SHARE STCG taxed at 15 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2024-04-01 to 2024-07-22 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.29 (s.111A(1) as substituted): "at the rate of fifteen per cent. for any transfer which takes place before the 23rd day of July, 2024". Research effective_from "(pre-2024)"; narrowed to 2024-04-01.
- **Worked example:** Input: LISTED_EQUITY_SHARE; acquired 2024-01-10, transfer/income date 2024-07-22; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `EQ-STCG-OLD` (ITA1961 s.111A), rate 15 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 15,000.00 + surcharge Rs 0.00 + cess Rs 600.00 = **Rs 15,600.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `EQ-STCG/ITA1961`

- **What the app assumes:** LISTED_EQUITY_SHARE STCG taxed at 20 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.29 (s.111A(1)): "at the rate of twenty per cent. for any transfer which takes place on or after the 23rd day of July, 2024".
- **Worked example:** Input: LISTED_EQUITY_SHARE; acquired 2024-08-01, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `EQ-STCG/ITA1961` (ITA1961 s.111A), rate 20 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 20,000.00 + surcharge Rs 0.00 + cess Rs 800.00 = **Rs 20,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `EQ-STCG/ITA2025`

- **What the app assumes:** LISTED_EQUITY_SHARE STCG taxed at 20 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.196(1)(i): "income-tax calculated on such short-term capital gains at the rate of 20%" (equity share / unit of an equity oriented fund, sale chargeable to STT). Short-term = held "not more than ... twelve months" for a listed security or equity-oriented-fund unit, s.2(101)(b).
- **Worked example:** Input: LISTED_EQUITY_SHARE; acquired 2025-06-01, transfer/income date 2026-05-04; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `EQ-STCG/ITA2025` (ITA2025 s.196), rate 20 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 20,000.00 + surcharge Rs 0.00 + cess Rs 800.00 = **Rs 20,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `EQ-LTCG-OLD`

- **What the app assumes:** LISTED_EQUITY_SHARE (acquisition_date_from=2018-02-01) LTCG taxed at 10 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2024-04-01 to 2024-07-22 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** CORRECTED in table r2 (was 100000). PRIMARY [FA24] s.31 (s.112A(2)(i) as substituted): tax on LTCG "exceeding one lakh twenty-five thousand rupees" at "(a) ... ten per cent. for any transfer which takes place before the 23rd day of July, 2024", and "the limit of one lakh twenty-five thousand rupees shall apply on aggregate of the long-term capital gains under sub-clauses (a) and (b)". So FY2024-25 transfers before 23-Jul-2024 share the same Rs 1.25 lakh pool. Research effective_from "(pre-2024)"; narrowed to 2024-04-01. Lots acquired on/before 31-Jan-2018 abstain (grandfathering not modelled). A FY2024-25 mix of 10 % and 12.5 % lots still abstains: how the pool is allocated between the two rates is not in the statute text (CA question).
- **Worked example:** Input: LISTED_EQUITY_SHARE; acquired 2023-01-02, transfer/income date 2024-07-01; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `EQ-LTCG-OLD` (ITA1961 s.112A), rate 10 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 7,500.00 + surcharge Rs 0.00 + cess Rs 300.00 = **Rs 7,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `EQ-LTCG/ITA1961`

- **What the app assumes:** LISTED_EQUITY_SHARE (acquisition_date_from=2018-02-01) LTCG taxed at 12.5 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.31 (s.112A(2)(i)(b)): "at the rate of twelve and one-half per cent. for any transfer which takes place on or after the 23rd day of July, 2024", on gains "exceeding one lakh twenty-five thousand rupees". Rs 1,25,000/yr aggregate exemption shared by listed equity, equity-oriented MF and arbitrage gains.
- **Worked example:** Input: LISTED_EQUITY_SHARE; acquired 2024-01-01, transfer/income date 2025-06-02; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `EQ-LTCG/ITA1961` (ITA1961 s.112A), rate 12.5 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 9,375.00 + surcharge Rs 0.00 + cess Rs 375.00 = **Rs 9,750.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `EQ-LTCG/ITA2025`

- **What the app assumes:** LISTED_EQUITY_SHARE (acquisition_date_from=2018-02-01) LTCG taxed at 12.5 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.198(2)(a): "income-tax calculated on such long-term capital gains exceeding ₹ 125000 at the rate of 12.5%" (STT conditions in s.198(1)(c)).
- **Worked example:** Input: LISTED_EQUITY_SHARE; acquired 2025-01-02, transfer/income date 2026-06-01; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `EQ-LTCG/ITA2025` (ITA2025 s.198), rate 12.5 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 9,375.00 + surcharge Rs 0.00 + cess Rs 375.00 = **Rs 9,750.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.3 Equity-oriented mutual funds (incl. arbitrage, equity ETF)

#### `MF-EQ-STCG-OLD`

- **What the app assumes:** MUTUAL_FUND (domestic_equity_share_min=0.65) STCG taxed at 15 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2024-04-01 to 2024-07-22 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.29 (s.111A(1)): 15 % "for any transfer which takes place before the 23rd day of July, 2024". Research effective_from "(pre-2024)"; narrowed to 2024-04-01.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.80, debt_share=0.10, listed=None); acquired 2024-01-10, transfer/income date 2024-07-22; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-EQ-STCG-OLD` (ITA1961 s.111A), rate 15 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 15,000.00 + surcharge Rs 0.00 + cess Rs 600.00 = **Rs 15,600.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-EQ-STCG/ITA1961`

- **What the app assumes:** MUTUAL_FUND (domestic_equity_share_min=0.65) STCG taxed at 20 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.29 (s.111A(1)): "twenty per cent. for any transfer which takes place on or after the 23rd day of July, 2024".
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.80, debt_share=0.10, listed=None); acquired 2024-08-01, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-EQ-STCG/ITA1961` (ITA1961 s.111A), rate 20 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 20,000.00 + surcharge Rs 0.00 + cess Rs 800.00 = **Rs 20,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-EQ-STCG/ITA2025`

- **What the app assumes:** MUTUAL_FUND (domestic_equity_share_min=0.65) STCG taxed at 20 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.196(1)(i) 20 %; equity oriented fund per s.198(8)(ii): "a minimum of 65% of the total proceeds of such fund is invested in the equity shares of domestic companies listed on a recognised stock exchange", averaged per s.198(8)(I). NOT MODELLED: the fund-of-funds limb s.198(8)(i) (90 % in a listed equity fund that itself holds 90 %); whether hedged arbitrage positions count toward 65 % is CA question 12.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.80, debt_share=0.10, listed=None); acquired 2025-06-01, transfer/income date 2026-05-04; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-EQ-STCG/ITA2025` (ITA2025 s.196), rate 20 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 20,000.00 + surcharge Rs 0.00 + cess Rs 800.00 = **Rs 20,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-EQ-LTCG-OLD`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_from=2018-02-01, domestic_equity_share_min=0.65) LTCG taxed at 10 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2024-04-01 to 2024-07-22 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** CORRECTED in table r2 (was 100000); same primary text as EQ-LTCG-OLD: [FA24] s.31, "the limit of one lakh twenty-five thousand rupees shall apply on aggregate of the long-term capital gains under sub-clauses (a) and (b)". Research effective_from "(pre-2024)"; narrowed to 2024-04-01. Pre-1-Feb-2018 lots abstain.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.80, debt_share=0.10, listed=None); acquired 2023-01-02, transfer/income date 2024-07-01; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-EQ-LTCG-OLD` (ITA1961 s.112A), rate 10 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 7,500.00 + surcharge Rs 0.00 + cess Rs 300.00 = **Rs 7,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-EQ-LTCG/ITA1961`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_from=2018-02-01, domestic_equity_share_min=0.65) LTCG taxed at 12.5 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.31 (s.112A(2)(i)(b)): 12.5 % on gains above Rs 1,25,000 for transfers on/after 23-Jul-2024.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.80, debt_share=0.10, listed=None); acquired 2024-01-01, transfer/income date 2025-06-02; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-EQ-LTCG/ITA1961` (ITA1961 s.112A), rate 12.5 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 9,375.00 + surcharge Rs 0.00 + cess Rs 375.00 = **Rs 9,750.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-EQ-LTCG/ITA2025`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_from=2018-02-01, domestic_equity_share_min=0.65) LTCG taxed at 12.5 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.198(2)(a): "exceeding ₹ 125000 at the rate of 12.5%"; equity oriented fund per s.198(8) (see MF-EQ-STCG/ITA2025).
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.80, debt_share=0.10, listed=None); acquired 2025-01-02, transfer/income date 2026-06-01; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-EQ-LTCG/ITA2025` (ITA2025 s.198), rate 12.5 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 9,375.00 + surcharge Rs 0.00 + cess Rs 375.00 = **Rs 9,750.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.4 Specified (debt) mutual funds, s.50AA / s.76

#### `MF-SMF-DEF-OLD`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_from=2023-04-01, domestic_equity_share_max=0.35) STCG taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act 50AA / 2025 Act 76
- **Effective (transfer/income dates):** 2023-04-01 to 2025-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- **Citation / notes:** Old definition (<=35 % in domestic equity shares), AY up to 2025-26 (FY <= 2024-25). The replacing definition applies "with effect from the 1st day of April, 2026" (= AY2026-27) per [FA24] s.21(b), which confirms the end date.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.10, debt_share=0.90, listed=None); acquired 2023-04-01, transfer/income date 2024-10-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-SMF-DEF-OLD` (ITA1961 s.50AA), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-DEBT-SMF/ITA1961`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_from=2023-04-01, debt_share_above=0.65) STCG taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act 50AA / 2025 Act 76
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.21 (s.50AA as substituted): "is a unit of a Specified Mutual Fund acquired on or after the 1st day of April, 2023" -> deemed short-term; s.21(b) new Explanation (ii) w.e.f. 1-Apr-2026 (AY2026-27 = FY2025-26): "invests more than sixty-five per cent. of its total proceeds in debt and money market instruments", or a fund investing "sixty-five per cent. or more" in such funds, measured on "the annual average of the daily closing figures". Overnight, liquid, money market and all debt categories; conservative hybrid depends on its annual-average debt share (CA question 4). The fund-of-funds limb needs look-through data the app does not have.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0, debt_share=0.90, listed=False); acquired 2023-04-01, transfer/income date 2025-06-30; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-DEBT-SMF/ITA1961` (ITA1961 s.50AA), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-DEBT-SMF/ITA2025`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_from=2023-04-01, debt_share_above=0.65) STCG taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act 50AA / 2025 Act 76
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.76(1)-(2)(a): gains on "a unit of a Specified Mutual Fund acquired on or after the 1st April, 2023" "shall be treated as short-term capital gains" "Irrespective of anything contained in section 2(101)"; s.76(5)(b): "invests more than 65% of its total proceeds in debt and money market instruments or a fund which invests 65% or more of its total proceeds in units of such Mutual Fund", on "the annual average of the daily closing figures". Resolves CA question 2: s.50AA -> s.76, definition carried forward. The fund-of-funds limb needs look-through data the app does not have.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0, debt_share=0.90, listed=False); acquired 2023-04-01, transfer/income date 2026-06-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-DEBT-SMF/ITA2025` (ITA2025 s.76), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.5 Debt mutual fund units acquired before 1-Apr-2023

#### `MF-DEBT-PRE2023-ST/ITA1961`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_to=2023-03-31, listed=False, debt_share_above=0.65) STCG taxed at the slab rate; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.3(b)(i) (s.2(42A)): "for the words 'thirty-six months', the words 'twenty-four months' shall be substituted" w.e.f. 23-Jul-2024; s.3(b)(ii)(A) omits "(other than a unit)" from the 12-month first proviso, whose base text [ITA61] covers "a security (other than a unit) listed in a recognised stock exchange". So from 23-Jul-2024 an UNLISTED debt-fund unit is short-term up to 24 months, a LISTED one (debt ETF) up to 12. CORRECTED in table r2: condition listed: false added; listed pre-2023 debt units now abstain instead of wrongly using 24 months. Units acquired before 1-Apr-2023 are outside s.50AA ("acquired on or after the 1st day of April, 2023"). 36 months earlier - not modelled; earlier transfers abstain.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0, debt_share=0.90, listed=False); acquired 2023-03-01, transfer/income date 2024-09-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-DEBT-PRE2023-ST/ITA1961` (ITA1961 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-DEBT-PRE2023-ST/ITA2025`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_to=2023-03-31, listed=False, debt_share_above=0.65) STCG taxed at the slab rate; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.2(101)(a): "held by an assessee for not more than twenty-four months"; the 12-month list in s.2(101)(b) is a listed security, a UTI unit, an equity-oriented-fund unit or a zero-coupon bond. s.76(2)(a) reaches only units "acquired on or after the 1st April, 2023". CORRECTED in table r2: listed: false (listed units take 12 months; they abstain).
- **Worked example:** No example exists: a unit acquired on or before 31-Mar-2023 and transferred on or after 1-Apr-2026 has been held more than 36 months, so it is always long-term. The row exists for completeness.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-DEBT-PRE2023-LT/ITA1961`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_to=2023-03-31, listed=False, debt_share_above=0.65) LTCG taxed at 12.5 %; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.30 (s.112(1)(a)(ii)(B)): "at the rate of twelve and one-half per cent. for any transfer which takes place on or after the 23rd day of July, 2024"; no indexation ([MEMO24]: "indexation available under second proviso to section 48 is proposed to be removed"). Holding period as MF-DEBT-PRE2023-ST/ITA1961; listed: false added in r2.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0, debt_share=0.90, listed=False); acquired 2023-03-01, transfer/income date 2025-06-30; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-DEBT-PRE2023-LT/ITA1961` (ITA1961 s.112), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-DEBT-PRE2023-LT/ITA2025`

- **What the app assumes:** MUTUAL_FUND (acquisition_date_to=2023-03-31, listed=False, debt_share_above=0.65) LTCG taxed at 12.5 %; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.197(1)(b): "income-tax calculated on such long-term capital gains at the rate of 12.5%"; indexation survives only for land/building acquired before 23-Jul-2024 (s.197(3)). Holding period s.2(101)(a) 24 months; listed: false added in r2.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0, debt_share=0.90, listed=False); acquired 2023-03-01, transfer/income date 2026-06-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-DEBT-PRE2023-LT/ITA2025` (ITA2025 s.197), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.6 Other mutual funds (gold/international FoF, hybrids with <= 65 % debt)

#### `MF-OTHER-ST/ITA1961`

- **What the app assumes:** MUTUAL_FUND (listed=False, domestic_equity_share_below=0.65, debt_share_max=0.65) STCG taxed at the slab rate; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.3(b) (s.2(42A)): 24 months for assets outside the 12-month proviso; [MEMO24]: "For all listed securities, the holding period is proposed to be 12 months and for all other assets, it shall be 24 months". An unlisted non-equity, non-specified fund unit (e.g. gold or international FoF) is therefore short-term up to 24 months. Classification follows s.50AA Explanation (ii) ([FA24] s.21(b)): not specified when debt <= 65 % (annual average of daily closing figures). Resolves CA question 3 for UNLISTED units; LISTED non-equity ETF units take 12 months under the same text but have no rule here (they abstain).
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.10, debt_share=0.30, listed=False); acquired 2024-06-01, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-OTHER-ST/ITA1961` (ITA1961 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-OTHER-ST/ITA2025`

- **What the app assumes:** MUTUAL_FUND (listed=False, domestic_equity_share_below=0.65, debt_share_max=0.65) STCG taxed at the slab rate; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.2(101)(a): "not more than twenty-four months"; s.2(101)(b)(i)-(iv) gives 12 months only to a "security listed in a recognised stock exchange in India", a UTI unit, a "unit of an equity-oriented fund" or a "zero-coupon bond". Specified-fund test s.76(5)(b) (>65 % debt). Resolves CA question 3 for UNLISTED units; listed non-equity ETF units (12 months) abstain. Whether a particular hybrid crosses 65 % depends on the scheme's annual average (CA question 4: data, not law).
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.10, debt_share=0.30, listed=False); acquired 2025-06-01, transfer/income date 2026-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `MF-OTHER-ST/ITA2025` (ITA2025 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-OTHER-LT/ITA1961`

- **What the app assumes:** MUTUAL_FUND (listed=False, domestic_equity_share_below=0.65, debt_share_max=0.65) LTCG taxed at 12.5 %; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.30 (s.112(1)(a)(ii)(B)): 12.5 % "for any transfer which takes place on or after the 23rd day of July, 2024"; holding period as MF-OTHER-ST/ITA1961.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.10, debt_share=0.30, listed=False); acquired 2023-01-02, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-OTHER-LT/ITA1961` (ITA1961 s.112), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `MF-OTHER-LT/ITA2025`

- **What the app assumes:** MUTUAL_FUND (listed=False, domestic_equity_share_below=0.65, debt_share_max=0.65) LTCG taxed at 12.5 %; long-term only if held more than 24 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.197(1)(b): "at the rate of 12.5%"; holding period as MF-OTHER-ST/ITA2025.
- **Worked example:** Input: MUTUAL_FUND (domestic_equity_share=0.10, debt_share=0.30, listed=False); acquired 2024-01-02, transfer/income date 2026-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `MF-OTHER-LT/ITA2025` (ITA2025 s.197), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.7 Bonds and debentures

#### `BOND-L-ST/ITA1961`

- **What the app assumes:** BOND (listed=True) STCG taxed at the slab rate; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- **Citation / notes:** Listed bonds/debentures. PRIMARY [MEMO24]: "For all listed securities, the holding period is proposed to be 12 months"; [ITA61] s.2(42A) first proviso (12 months for a listed security). Research also lists listed G-sec/SDL and SGB sold on exchange (see GSEC-CG).
- **Worked example:** Input: BOND (listed=True); acquired 2024-08-01, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `BOND-L-ST/ITA1961` (ITA1961 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BOND-L-ST/ITA2025`

- **What the app assumes:** BOND (listed=True) STCG taxed at the slab rate; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.2(101)(b)(i): twelve months for a "security listed in a recognised stock exchange in India"; slab via s.202(1).
- **Worked example:** Input: BOND (listed=True); acquired 2025-08-01, transfer/income date 2026-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `BOND-L-ST/ITA2025` (ITA2025 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BOND-L-LT/ITA1961`

- **What the app assumes:** BOND (listed=True) LTCG taxed at 12.5 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.30 (s.112(1)(a)(ii)(B)): "twelve and one-half per cent. for any transfer which takes place on or after the 23rd day of July, 2024". No indexation.
- **Worked example:** Input: BOND (listed=True); acquired 2024-08-01, transfer/income date 2025-09-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `BOND-L-LT/ITA1961` (ITA1961 s.112), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BOND-L-LT/ITA2025`

- **What the app assumes:** BOND (listed=True) LTCG taxed at 12.5 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.197(1)(b): "at the rate of 12.5%". No indexation.
- **Worked example:** Input: BOND (listed=True); acquired 2025-01-02, transfer/income date 2026-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `BOND-L-LT/ITA2025` (ITA2025 s.197), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BOND-L-LT-OLD`

- **What the app assumes:** BOND (listed=True) LTCG taxed at 10 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2024-04-01 to 2024-07-22 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.30, proviso to s.112(1) as substituted: "where the tax payable in respect of any income arising from the transfer of a long-term capital asset which takes place before the 23rd day of July, 2024, being listed securities (other than a unit) or zero coupon bond, exceeds ten per cent. of the amount of capital gains before giving effect to the provisions of the second proviso to section 48, then, such excess shall be ignored". With [MEMO24] ("For bonds and debentures, rate for taxation of long-term capital gains was 20% without indexation") the effective rate on a listed bond is 10 % without indexation, which this row encodes. Research effective_from "(pre-2024)"; narrowed to 2024-04-01.
- **Worked example:** Input: BOND (listed=True); acquired 2023-01-02, transfer/income date 2024-07-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `BOND-L-LT-OLD` (ITA1961 s.112), rate 10 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 10,000.00 + surcharge Rs 0.00 + cess Rs 400.00 = **Rs 10,400.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BOND-UL/ITA1961`

- **What the app assumes:** BOND (listed=False) STCG taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act 50AA / 2025 Act 76
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://egazette.gov.in/WriteReadData/2024/256436.pdf
- **Citation / notes:** PRIMARY [FA24] s.21 (s.50AA): "is an unlisted bond or an unlisted debenture which is transferred or redeemed or matures on or after the 23rd day of July, 2024" -> deemed short-term at slab.
- **Worked example:** Input: BOND (listed=False); acquired 2024-08-01, transfer/income date 2025-09-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `BOND-UL/ITA1961` (ITA1961 s.50AA), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BOND-UL/ITA2025`

- **What the app assumes:** BOND (listed=False) STCG taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act 50AA / 2025 Act 76
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.76(2)(b): "an unlisted bond or an unlisted debenture which is transferred or redeemed or matures on or after the 23rd July, 2024"; s.76(1): "shall be treated as short-term capital gains". Resolves the s.50AA -> s.76 mapping.
- **Worked example:** Input: BOND (listed=False); acquired 2024-08-01, transfer/income date 2026-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `BOND-UL/ITA2025` (ITA2025 s.76), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.8 Government securities (dated G-secs, SDLs)

#### `GSEC-CG-ST/ITA1961`

- **What the app assumes:** GSEC STCG taxed at the slab rate; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** NV - source: https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- **Citation / notes:** NOT VERIFIED. Statute read: [ITA61] s.2(42A) first proviso and [MEMO24] give 12 months to a security "listed in a recognised stock exchange in India". Whether a G-sec held in an RBI Retail Direct Gilt account (or bought on NDS-OM) is such a listed security is a FACT the statute does not settle and no primary RBI/SEBI text was read (CA question 7). If not listed: 24 months, and it may even be an "unlisted bond" under s.50AA (deemed STCG at slab) - CA must confirm.
- **Worked example:** Input: GSEC; acquired 2024-09-02, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `GSEC-CG-ST/ITA1961` (ITA1961 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `GSEC-CG-ST/ITA2025`

- **What the app assumes:** GSEC STCG taxed at the slab rate; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** NV - source: https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- **Citation / notes:** NOT VERIFIED. [ITA25] s.2(101)(b)(i) (12 months for a "security listed in a recognised stock exchange in India") read; listed status of Retail-Direct G-secs not settled by any primary text read (CA question 7). If not listed: 24 months, and s.76(2)(b) ("an unlisted bond") could make every gain short-term at slab.
- **Worked example:** Input: GSEC; acquired 2025-09-01, transfer/income date 2026-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `GSEC-CG-ST/ITA2025` (ITA2025 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `GSEC-CG-LT/ITA1961`

- **What the app assumes:** GSEC LTCG taxed at 12.5 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2024-07-23 to 2026-03-31 (ITA1961)
- **Status:** NV - source: https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
- **Citation / notes:** NOT VERIFIED. 12.5 % rate is primary ([FA24] s.30); the 12-month threshold depends on "listed" status (CA question 7, see GSEC-CG-ST/ITA1961).
- **Worked example:** Input: GSEC; acquired 2024-01-02, transfer/income date 2025-06-02; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `GSEC-CG-LT/ITA1961` (ITA1961 s.112), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `GSEC-CG-LT/ITA2025`

- **What the app assumes:** GSEC LTCG taxed at 12.5 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** NV - source: https://www.indiabudget.gov.in/doc/memo.pdf
- **Citation / notes:** NOT VERIFIED. 12.5 % rate is primary ([ITA25] s.197(1)(b)); threshold depends on "listed" status and s.76(2)(b) may apply (CA question 7).
- **Worked example:** Input: GSEC; acquired 2025-01-02, transfer/income date 2026-06-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `GSEC-CG-LT/ITA2025` (ITA2025 s.197), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.9 Treasury bills

#### `TBILL-01/ITA1961`

- **What the app assumes:** TBILL INCOME taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2024-04-01 to 2026-03-31 (ITA1961)
- **Status:** NV - source: https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=711
- **Citation / notes:** NOT VERIFIED. No provision of [ITA61] or [ITA25] read names Treasury bills. The "zero coupon bond" definition ([ITA25] s.2(112)) is limited to bonds "issued by any infrastructure capital company or infrastructure capital fund or infrastructure debt fund or public sector company or scheduled bank", so T-bills are not zero coupon bonds. [ITA25] s.2(59) defines interest as "interest payable in any manner for moneys borrowed or debt incurred", which may reach the discount, but no primary text says so. Head of income unresolved (capital gains vs other sources); SLAB under every reading (CA question 1). source_url is the RBI G-sec FAQ (instrument facts only). Research gives no start date; narrowed to 2024-04-01.
- **Worked example:** Input: TBILL; transfer/income date 2025-11-05; gain Rs 10,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: INCOME under `TBILL-01/ITA1961` (ITA1961 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 10,000.00; tax Rs 3,000.00 + surcharge Rs 0.00 + cess Rs 120.00 = **Rs 3,120.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TBILL-01/ITA2025`

- **What the app assumes:** TBILL INCOME taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** NV - source: https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=711
- **Citation / notes:** NOT VERIFIED. See TBILL-01/ITA1961 (same reading of [ITA25] s.2(59) and s.2(112); CA question 1).
- **Worked example:** Input: TBILL; transfer/income date 2026-07-01; gain Rs 10,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: INCOME under `TBILL-01/ITA2025` (ITA2025 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 10,000.00; tax Rs 3,000.00 + surcharge Rs 0.00 + cess Rs 120.00 = **Rs 3,120.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.10 Interest (FD, PO TD, coupons, FRSB, SGB coupon)

#### `INT-SLAB-01/ITA1961`

- **What the app assumes:** INTEREST INCOME taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2024-04-01 to 2026-03-31 (ITA1961)
- **Status:** S - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** FD (bank/NBFC/HFC), PO TD, bond/G-sec coupon, FRSB, SGB 2.5 % coupon. New regime: no 80TTB. Taxed on accrual each year (methodology §2.12). Research gives no start date; narrowed to 2024-04-01.
- **Worked example:** Input: INTEREST; transfer/income date 2025-12-31; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: INCOME under `INT-SLAB-01/ITA1961` (ITA1961 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `INT-SLAB-01/ITA2025`

- **What the app assumes:** INTEREST INCOME taxed at the slab rate; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** S - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** See INT-SLAB-01/ITA1961.
- **Worked example:** Input: INTEREST; transfer/income date 2026-12-31; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: INCOME under `INT-SLAB-01/ITA2025` (ITA2025 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.11 Sovereign Gold Bonds (redemption at maturity)

#### `SGB-01`

- **What the app assumes:** SGB (redemption_at_maturity=True, original_subscriber_held_continuously=True) LTCG fully exempt; no holding-period test, before surcharge and 4 % cess.
- **Sections:** 1961 Act 10(15)/47(viic) / 2025 Act 70(1)(x)
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.70(1)(x) as substituted by [FA26] s.43 w.e.f. 1-4-2026: transfer "by way of redemption, of Sovereign Gold Bond ... if held by an individual from the date of original issue till maturity" is not a transfer. Applies to the 2015 scheme "or any subsequent Sovereign Gold Bond Scheme".
- **Worked example:** Input: SGB (redemption_at_maturity=True, original_subscriber_held_continuously=True); acquired 2018-08-01, transfer/income date 2026-08-01; gain Rs 3,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `SGB-01` (ITA2025 s.70(1)(x)), rate EXEMPT; exemption applied Rs 0.00; taxable Rs 0.00; tax Rs 0.00 + surcharge Rs 0.00 + cess Rs 0.00 = **Rs 0.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `SGB-02-ST`

- **What the app assumes:** SGB (redemption_at_maturity=True, original_subscriber_held_continuously=False) STCG taxed at the slab rate; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** NV - source: https://www.indiabudget.gov.in/doc/memo.pdf
- **Citation / notes:** NOT VERIFIED (computation). PRIMARY for the no-exemption part: [ITA25] s.70(1)(x) exempts only a bond "held by an individual from the date of original issue till maturity" ([FA26] s.43), so a secondary buyer's redemption is a taxable transfer. NOT VERIFIED: that an SGB is a "security listed in a recognised stock exchange" (s.2(101)(b)(i), 12 months) - the RBI SGB FAQ read says only that bonds "are tradable" and "only bonds held in de-mat form ... can be traded in stock exchanges" and is out of date on tax; cost basis for a secondary buyer (CA question 8).
- **Worked example:** Input: SGB (redemption_at_maturity=True, original_subscriber_held_continuously=False); acquired 2025-12-01, transfer/income date 2026-08-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `SGB-02-ST` (ITA2025 s.-), rate SLAB (30 % in this profile); exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 30,000.00 + surcharge Rs 0.00 + cess Rs 1,200.00 = **Rs 31,200.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `SGB-02-LT`

- **What the app assumes:** SGB (redemption_at_maturity=True, original_subscriber_held_continuously=False) LTCG taxed at 12.5 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112 / 2025 Act 197
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** NV - source: https://www.indiabudget.gov.in/doc/memo.pdf
- **Citation / notes:** NOT VERIFIED (computation). 12.5 % rate primary ([ITA25] s.197(1)(b)); no exemption primary (s.70(1)(x)); 12-month threshold depends on listed status (see SGB-02-ST; CA question 8).
- **Worked example:** Input: SGB (redemption_at_maturity=True, original_subscriber_held_continuously=False); acquired 2024-01-02, transfer/income date 2026-08-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `SGB-02-LT` (ITA2025 s.197), rate 12.5 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 12,500.00 + surcharge Rs 0.00 + cess Rs 500.00 = **Rs 13,000.00**. Unverified flag: True.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.12 Listed-equity buyback (from 1-Apr-2026)

#### `BUYBACK-01-ST`

- **What the app assumes:** LISTED_EQUITY_BUYBACK STCG taxed at 20 %; long-term only if held more than 12 months, before surcharge and 4 % cess.
- **Sections:** 1961 Act 111A / 2025 Act 196
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** S - source: https://www.indiabudget.gov.in/doc/memo.pdf
- **Citation / notes:** Non-promoter listed-equity buyback. PRIMARY (enacted) [ITA25] s.69(1): consideration less cost "shall be deemed to be the 'Capital gains'"; s.69(2) ([FA26] s.42) adds extra tax only for promoters. NOT READ in primary: that the buyback transaction is chargeable to STT, which s.196(1)(b) requires for the 20 % rate. Status stays S.
- **Worked example:** Input: LISTED_EQUITY_BUYBACK; acquired 2025-10-01, transfer/income date 2026-06-01; gain Rs 1,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: STCG under `BUYBACK-01-ST` (ITA2025 s.196), rate 20 %; exemption applied Rs 0.00; taxable Rs 1,00,000.00; tax Rs 20,000.00 + surcharge Rs 0.00 + cess Rs 800.00 = **Rs 20,800.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `BUYBACK-01-LT`

- **What the app assumes:** LISTED_EQUITY_BUYBACK (acquisition_date_from=2018-02-01) LTCG taxed at 12.5 %; long-term only if held more than 12 months; first Rs 1,25,000.00 a year of such gains (one shared pool) is exempt, before surcharge and 4 % cess.
- **Sections:** 1961 Act 112A / 2025 Act 198
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** S - source: https://www.indiabudget.gov.in/doc/memo.pdf
- **Citation / notes:** Per EQ rules (shares the annual equity LTCG exemption). [ITA25] s.69(1) read (capital gains); s.198(1)(c) STT condition on the buyback not verified in primary. Status stays S.
- **Worked example:** Input: LISTED_EQUITY_BUYBACK; acquired 2024-01-02, transfer/income date 2026-06-01; gain Rs 2,00,000.00; profile 30 % slab, no surcharge (fictional).  
  Engine: LTCG under `BUYBACK-01-LT` (ITA2025 s.198), rate 12.5 %; exemption applied Rs 1,25,000.00; taxable Rs 75,000.00; tax Rs 9,375.00 + surcharge Rs 0.00 + cess Rs 375.00 = **Rs 9,750.00**. Unverified flag: False.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.13 New-regime slab tables

#### `SLAB-NEW-01/FY2025-26`

- **What the app assumes:** New-regime slabs 0-400000: 0; 400000-800000: 0.05; 800000-1200000: 0.10; 1200000-1600000: 0.15; 1600000-2000000: 0.20; 2000000-2400000: 0.25; 2400000-above: 0.30.
- **Sections:** 1961 Act 115BAC(1A) / 2025 Act 202
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://thc.nic.in/Central%20Governmental%20Acts/Finance%20Act,%202025.pdf
- **Citation / notes:** PRIMARY [FA25] s.25 inserting s.115BAC(1A)(iii) "for any previous year relevant to the assessment year beginning on or after the 1st April, 2026": "Upto Rs. 4,00,000 Nil" ... "Above Rs. 24,00,000 30 per cent.". Old regime is available by option and is not modelled.
- **Worked example:** slab_tax (before cess): Rs 4,00,000.00 -> Rs 0.00, Rs 12,00,000.00 -> Rs 60,000.00, Rs 15,00,000.00 -> Rs 1,05,000.00, Rs 25,00,000.00 -> Rs 3,30,000.00.  
  Stacking: other income Rs 11,00,000 + interest Rs 2,00,000 in 2025-26: engine tax on the interest = **Rs 26,000.00** (1 lakh at 10 % + 1 lakh at 15 % = 25,000, + 4 % cess); warning REBATE_NOT_APPLIED.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `SLAB-NEW-01/TY2026-27`

- **What the app assumes:** New-regime slabs 0-400000: 0; 400000-800000: 0.05; 800000-1200000: 0.10; 1200000-1600000: 0.15; 1600000-2000000: 0.20; 2000000-2400000: 0.25; 2400000-above: 0.30.
- **Sections:** 1961 Act 115BAC(1A) / 2025 Act 202
- **Effective (transfer/income dates):** 2026-04-01 to 2027-03-31 (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.202(1) Table: "Upto ₹ 400000 Nil", "From ₹ 400001 to ₹ 800000 5%" ... "Above ₹ 2400000 30%" - identical to the FY2025-26 slabs; [FA26] s.56 amends only s.202(2).
- **Worked example:** slab_tax (before cess): Rs 4,00,000.00 -> Rs 0.00, Rs 12,00,000.00 -> Rs 60,000.00, Rs 15,00,000.00 -> Rs 1,05,000.00, Rs 25,00,000.00 -> Rs 3,30,000.00.  
  Stacking: other income Rs 11,00,000 + interest Rs 2,00,000 in 2026-27: engine tax on the interest = **Rs 26,000.00** (1 lakh at 10 % + 1 lakh at 15 % = 25,000, + 4 % cess); warning REBATE_NOT_APPLIED.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.14 Surcharge

#### `SURCH-01/FY2025-26`

- **What the app assumes:** Surcharge bands >5000000: 0.10, >10000000: 0.15, >20000000: 0.25; capped at 0.15 on dividend and on gains under 111A, 112, 112A.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/finance-act-2026-pdf-1
- **Citation / notes:** PRIMARY [FA26] s.2(4)(b) Table Sl. No. 10 ("115BAC (1A)", assessment year commencing 1-Apr-2026 = FY2025-26): 10 % above Rs 50,00,000; 15 % above Rs 1,00,00,000; "twenty-five per cent." above Rs 2,00,00,000 (excluding dividend and s.111A/112/112A gains); "the rate of surcharge on the income-tax in respect of that part of income shall not exceed fifteen per cent.". Marginal relief (s.2(5)) not modelled (engine warns).
- **Worked example:** Band 25 % (total income above Rs 2 crore). Equity STCG Rs 1,00,000 on 2025-06-02: surcharge capped at 0.15 -> tax Rs 20,000.00 + surcharge Rs 3,000.00 + cess Rs 920.00 = **Rs 23,920.00**. Interest Rs 1,00,000: surcharge 0.25 (not capped) -> **Rs 39,000.00**. Marginal relief not modelled (warning).
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `SURCH-01/TY2026-27`

- **What the app assumes:** Surcharge bands >5000000: 0.10, >10000000: 0.15, >20000000: 0.25; capped at 0.15 on dividend and on gains under 196, 197, 198.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to 2027-03-31 (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/finance-act-2026-pdf-1
- **Citation / notes:** PRIMARY [FA26] s.2(12)(b) Table Sl. No. 10 (persons taxed "under section 202", tax year 2026-27): 10 % / 15 % / 25 %; "the rate of surcharge on the 'advance tax' in respect of that part of income shall not exceed 15%" for dividend and s.196/197/198 gains. These are the Finance Act 2026 rates for advance tax and TDS; the final rates for TY2026-27 are fixed by the Finance Act 2027 (not yet enacted). Marginal relief (s.2(13)) not modelled.
- **Worked example:** Band 25 % (total income above Rs 2 crore). Equity STCG Rs 1,00,000 on 2026-06-02: surcharge capped at 0.15 -> tax Rs 20,000.00 + surcharge Rs 3,000.00 + cess Rs 920.00 = **Rs 23,920.00**. Interest Rs 1,00,000: surcharge 0.25 (not capped) -> **Rs 39,000.00**. Marginal relief not modelled (warning).
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.15 Health and Education Cess

#### `CESS-01/ITA1961`

- **What the app assumes:** Health & Education Cess 0.04 on (tax + surcharge).
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2024-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/finance-act-2026-pdf-1
- **Citation / notes:** PRIMARY [FA26] s.2(6) (AY2026-27 = FY2025-26) and [FA25] s.2(11) (AY2025-26 = FY2024-25): "Health and Education Cess on income-tax", "calculated at the rate of four per cent. of such income-tax and surcharge". Research says "(in force)"; narrowed to 2024-04-01.
- **Worked example:** Equity STCG Rs 1,00,000 on 2025-06-02: tax Rs 20,000.00 + surcharge Rs 0.00; cess 0.04 x (tax + surcharge) = **Rs 800.00**; total Rs 20,800.00.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `CESS-01/ITA2025`

- **What the app assumes:** Health & Education Cess 0.04 on (tax + surcharge).
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/finance-act-2026-pdf-1
- **Citation / notes:** PRIMARY [FA26] s.2(15)-(16) (tax year 2026-27): "calculated at the rate of 4% of such income-tax and surcharge".
- **Worked example:** Equity STCG Rs 1,00,000 on 2026-06-02: tax Rs 20,000.00 + surcharge Rs 0.00; cess 0.04 x (tax + surcharge) = **Rs 800.00**; total Rs 20,800.00.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.16 Rebate (s.87A / s.156)

#### `REBATE-01/FY2025-26`

- **What the app assumes:** Rebate up to Rs 60,000.00 when total income <= Rs 12,00,000.00; never against tax under 111A, 112, 112A. NOT applied by the engine.
- **Sections:** 1961 Act 87A / 2025 Act 156
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://thc.nic.in/Central%20Governmental%20Acts/Finance%20Act,%202025.pdf
- **Citation / notes:** PRIMARY [FA25] s.20 (s.87A w.e.f. 1-4-2026 = AY2026-27): "twelve hundred thousand rupees" and "sixty thousand rupees" substituted, and "the deduction under the first proviso, shall not exceed the amount of income-tax payable as per the rates provided in sub-section (1A) of section 115BAC" - so no rebate against tax at special rates (s.111A, s.112). [ITA61] s.112A(6): "the rebate under section 87A shall be allowed from the income-tax on the total income as reduced by tax payable on such capital gains". CORRECTED in table r2: "112A" added to excluded_sections. The ceiling is on "total income", which includes capital gains (CA to confirm, question 5). The engine does NOT apply the rebate (warns REBATE_NOT_APPLIED), so tax is never understated.
- **Worked example:** Engine (rebate NOT applied): other income Rs 9,00,000 + interest Rs 2,00,000 -> tax on the interest **Rs 20,800.00**, warnings ['REBATE_NOT_APPLIED'].  
  Statute, by hand (not engine): total income Rs 11,00,000 <= Rs 12,00,000, slab tax Rs 50,000.00 <= rebate cap Rs 60,000.00 -> rebate Rs 50,000.00, tax nil. The engine overstates by the rebate; it never understates. Excluded (special-rate) sections: 111A, 112, 112A.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `REBATE-01/TY2026-27`

- **What the app assumes:** Rebate up to Rs 60,000.00 when total income <= Rs 12,00,000.00; never against tax under 196, 197, 198. NOT applied by the engine.
- **Sections:** 1961 Act 87A / 2025 Act 156
- **Effective (transfer/income dates):** 2026-04-01 to 2027-03-31 (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.156(2)(a): "the income does not exceed twelve lakh rupees, 100% of the income-tax payable or ₹ 60000, whichever is less" (with marginal relief in s.156(2)(b)); s.156(3): "shall not exceed income-tax payable as per the rates provided in section 202(1)"; s.198(7): "the rebate under section 156 shall be allowed from the income-tax on the total income as reduced by tax payable on such capital gains". Resolves the 87A -> s.156 mapping. CORRECTED in table r2: "198" added to excluded_sections. Not applied by the engine.
- **Worked example:** Engine (rebate NOT applied): other income Rs 9,00,000 + interest Rs 2,00,000 -> tax on the interest **Rs 20,800.00**, warnings ['REBATE_NOT_APPLIED'].  
  Statute, by hand (not engine): total income Rs 11,00,000 <= Rs 12,00,000, slab tax Rs 50,000.00 <= rebate cap Rs 60,000.00 -> rebate Rs 50,000.00, tax nil. The engine overstates by the rebate; it never understates. Excluded (special-rate) sections: 196, 197, 198.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.17 Tax deducted at source (information only)

#### `TDS-INT-OLD`

- **What the app assumes:** TDS 0.10 on bank / co-operative bank / post office interest, per payer per FY above Rs 40,000.00.
- **Sections:** 1961 Act 194A / 2025 Act -
- **Effective (transfer/income dates):** 2024-04-01 to 2025-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** Research effective_from "(pre-2025)"; narrowed to 2024-04-01.
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 40,000.00 in the year -> no TDS; Rs 40,001.00 -> TDS on the whole amount at 0.10 = Rs 4,000.10 (senior citizen threshold Rs 50,000.00).
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-INT-01/ITA1961`

- **What the app assumes:** TDS 0.10 on bank / co-operative bank / post office interest, per payer per FY above Rs 50,000.00.
- **Sections:** 1961 Act 194A / 2025 Act 393(1) Table Sl. 5
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** -
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 50,000.00 in the year -> no TDS; Rs 50,001.00 -> TDS on the whole amount at 0.10 = Rs 5,000.10 (senior citizen threshold Rs 1,00,000.00).
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-INT-01/ITA2025`

- **What the app assumes:** TDS 0.10 on bank / co-operative bank / post office interest, per payer per tax year above Rs 50,000.00.
- **Sections:** 1961 Act 194A / 2025 Act 393(1) Table Sl. 5(ii)
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.393(1) Table Sl. No. 5(ii) (banking company / co-operative bank / post office): "₹ 1,00,000 in the case of a senior citizen; ₹ 50,000 in case of person other than senior citizen", rate "Rates in force"; [FA26] Part II item 1(a)(i): "on income by way of interest other than 'Interest on securities' 10%".
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 50,000.00 in the year -> no TDS; Rs 50,001.00 -> TDS on the whole amount at 0.10 = Rs 5,000.10 (senior citizen threshold Rs 1,00,000.00).
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-INT-02/ITA1961`

- **What the app assumes:** TDS 0.10 on interest from other payers (e.g. NBFC/HFC deposit), per payer per FY above Rs 10,000.00.
- **Sections:** 1961 Act 194A / 2025 Act 393(1) Table Sl. 5
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** -
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 10,000.00 in the year -> no TDS; Rs 10,001.00 -> TDS on the whole amount at 0.10 = Rs 1,000.10.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-INT-02/ITA2025`

- **What the app assumes:** TDS 0.10 on interest from other payers (e.g. NBFC/HFC deposit), per payer per tax year above Rs 10,000.00.
- **Sections:** 1961 Act 194A / 2025 Act 393(1) Table Sl. 5(iii)
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.393(1) Table Sl. No. 5(iii): interest other than on securities paid by a "Specified person" (s.402(37): any person not an individual/HUF, or a large individual/HUF business), "Threshold limit: ₹ 10,000"; rate 10 % per [FA26] Part II item 1(a)(i).
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 10,000.00 in the year -> no TDS; Rs 10,001.00 -> TDS on the whole amount at 0.10 = Rs 1,000.10.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-SEC-01/ITA1961`

- **What the app assumes:** TDS 0.10 on interest on securities incl. listed debentures, per FY above Rs 10,000.00.
- **Sections:** 1961 Act 193 / 2025 Act -
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** -
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 10,000.00 in the year -> no TDS; Rs 10,001.00 -> TDS on the whole amount at 0.10 = Rs 1,000.10.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-SEC-01/ITA2025`

- **What the app assumes:** TDS 0.10 on interest on securities incl. listed debentures, per tax year above Rs 10,000.00.
- **Sections:** 1961 Act 193 / 2025 Act 393(1) Table Sl. 5(i)
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.393(1) Table Sl. No. 5(i): "Interest on securities", "Threshold limit: ₹ 10,000"; rate 10 % per [FA26] Part II item 1(a)(vi)-(vii). G-sec interest: s.393(4) Table Sl. No. 6(a)(iii) - no TDS on "any security of the Central Government or a State Government" other than the 8 %/7.75 % Savings (Taxable) Bonds and "Floating Rate Savings Bonds, 2020 (Taxable)" (resolves the G-sec TDS part of CA question 7).
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 10,000.00 in the year -> no TDS; Rs 10,001.00 -> TDS on the whole amount at 0.10 = Rs 1,000.10.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-MF-01/ITA1961`

- **What the app assumes:** TDS 0.10 on MF IDCW/dividend, per FY above Rs 10,000.00.
- **Sections:** 1961 Act 194K / 2025 Act 393(1)
- **Effective (transfer/income dates):** 2025-04-01 to 2026-03-31 (ITA1961)
- **Status:** P - source: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
- **Citation / notes:** -
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 10,000.00 in the year -> no TDS; Rs 10,001.00 -> TDS on the whole amount at 0.10 = Rs 1,000.10.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `TDS-MF-01/ITA2025`

- **What the app assumes:** TDS 0.10 on MF IDCW/dividend, per tax year above Rs 10,000.00.
- **Sections:** 1961 Act 194K / 2025 Act 393(1) Table Sl. 4(i)
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.393(1) Table Sl. No. 4(i): income in respect of "units of a Mutual Fund specified under Schedule VII", "Rate: 10%", "Threshold limit: ₹ 10,000". s.393(4) Table Sl. No. 4: no deduction "If income is of the nature of capital gain" (no TDS on resident redemptions).
- **Worked example:** Not computed by the engine (TDS is information only). By hand from the row: payments of Rs 10,000.00 in the year -> no TDS; Rs 10,001.00 -> TDS on the whole amount at 0.10 = Rs 1,000.10.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.18 Deductions (information only)

#### `DIV-INTEXP-01`

- **What the app assumes:** interest expense against dividend / MF income: allowed = False.
- **Sections:** 1961 Act - / 2025 Act -
- **Effective (transfer/income dates):** 2026-04-01 to in force (ITA2025)
- **Status:** P - source: https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf
- **Citation / notes:** PRIMARY [ITA25] s.93(2) as substituted by [FA26] s.44(b), footnote "Substituted by the Finance Act, 2026, w.e.f. 1-4-2026": "in respect of any dividend income or income from units of a Mutual Fund specified under Schedule VII ... no deduction shall be allowed." [FA26] s.1(2)(a) brings ss.2-129 into force on 1-Apr-2026. Because the 2025 Act governs only tax years from 1-Apr-2026, the memo's "tax year 2025-26 onwards" has no effect before TY2026-27 (resolves CA question 9). Information only; the engine does not use this rule.
- **Worked example:** Information only; the engine does not use this rule.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

### 4.19 Transaction levies (STT, stamp duty)

#### `STT-MF-01`

- **What the app assumes:** redemption (sale to the fund) of units of an equity-oriented scheme; base redemption value; payer seller (collected by the MF); rate 0.00001.
- **Statute:** Finance (No.2) Act 2004, s.98 (Securities Transaction Tax)
- **Effective (transfer/income dates):** 2024-04-01 to in force
- **Status:** S - source: https://www.indiabudget.gov.in/doc/memo.pdf
- **Citation / notes:** 0.001 %. Nil on debt schemes and on purchase. Research says "(in force)"; narrowed to 2024-04-01.
- **Worked example:** Engine: redemption value Rs 1,00,000 at rate 0.00001 -> **Rs 1.00**.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

#### `STAMP-MF-01`

- **What the app assumes:** issue of MF units (purchase, SIP/STP instalment, switch-in, IDCW reinvestment); base amount that buys units (duty-inclusive gross → use inclusive computation, methodology §2.10); payer investor; rate 0.00005.
- **Statute:** Indian Stamp Act 1899 as amended by Finance Act 2019
- **Effective (transfer/income dates):** 2020-07-01 to in force
- **Status:** S - source: doc:docs/research/indian-instruments-and-tax.md#12-costs
- **Citation / notes:** 0.005 %. Not charged on redemption. No government URL was fetched by the research (SEBI letter 29-Jun-2020 referenced by AMCs; methodology §2.10 cross-checks against HDFC/LIC/ABSL MF FAQs), so the source is the research document itself. Status stays S.
- **Worked example:** Engine: duty-inclusive gross Rs 1,00,000 (duty = gross x r/(1+r)) at rate 0.00005 -> **Rs 5.00**.
- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________

---

## 5. How the developer applies your corrections

Each correction follows the same four steps. Nothing in the engine code changes; tax logic is data (ADR-0009).

1. **Edit the YAML row** in `backend/src/iip/rules/tax/india.yaml`.
   - A value that was always wrong: change it in place and say so in `notes` ("CORRECTED in table rN (was X)").
   - A value that changed on a date: set `effective_to` on the old row and add a new row with the new
     `effective_from` and a new `rule_id` suffix. Never edit history silently.
   - Status: set `verification_status: P` and add to `notes` the CA's name/firm, the date, and the section relied on
     (for example `CA sign-off <name>, <date>: s.76(2)(a)`). A CA "No" with no correction sets the row to `NV`.
   - Keep decimals as quoted strings (`"0.125"`); the loader rejects floats and unknown fields.
2. **Bump the table version** at the top of the file: `table_version: india-tax@<date>.r<N+1>`. The version is shown
   on the Methodology page (`/api/methodology` → `tax.table_version`), so every result can be traced to the table that
   produced it.
3. **Add a regression test** in `backend/tests/unit/test_tax.py` that computes one disposal with the corrected rule
   and asserts the exact rupee result (see `test_fy_2024_25_pre_23_jul_equity_ltcg_gets_1_25_lakh_exemption`). If a
   row leaves or joins NV, update `KNOWN_NV` / `UPGRADED_FROM_NV` in `backend/tests/unit/test_rules_loader.py`.
4. **Run the gates** from `backend/`: `.venv/bin/pytest -q -p no:warnings`, `.venv/bin/ruff check src tests`,
   `.venv/bin/mypy`. Then regenerate the worked examples with `backend/scripts/ca_packet_examples.py` (one section at a time, e.g.
   `.venv/bin/python scripts/ca_packet_examples.py rules EQ-LTCG-OLD`) and paste the new card, so the packet shows the
   new figures.

Example (Rs 1.25 lakh correction, C1):

```yaml
  - rule_id: EQ-LTCG-OLD
    ...
    annual_exemption_inr: "125000"        # was "100000"
    notes: >-
      CORRECTED in table r2 (was 100000). PRIMARY [FA24] s.31 ... "shall apply on aggregate of the
      long-term capital gains under sub-clauses (a) and (b)".
```

```python
def test_fy_2024_25_pre_23_jul_equity_ltcg_gets_1_25_lakh_exemption(rules):
    report = compute_tax([equity(date(2023, 1, 2), date(2024, 7, 1), "150000")], rules, profile())
    assert report.classifications[0].exemption_applied_inr == D("125000")
    assert only_total(report) == D("2600.00")  # 10 % = 2,500 + 100 cess
```

---

## 6. Reviewer sign-off

| Field | Entry |
|---|---|
| Name, membership no. | |
| Firm | |
| Date | |
| Rules reviewed (all / list) | |
| Overall: rule table fit for illustrative after-tax comparisons for a resident individual under the new regime? | [ ] Yes  [ ] Yes, with the corrections marked  [ ] No |
| Comments | |
