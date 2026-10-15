// G-secs, SDLs and corporate bonds: request/response shapes of backend api/routes_bonds.py and
// services/instruments.py (GsecIn, CorporateBondIn). Decimals travel as strings; field names match the API exactly.
import type { CitationIn, Freshness } from "./types";

export type BondKind = "gsec" | "sdl" | "corp_bond";

/** Corporate rating symbols accepted by the API (engine CREDIT_SCALE without SOVEREIGN / UNRATED), strongest first. */
export const CORPORATE_RATINGS = [
  "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "C", "D",
] as const;
export type CorporateRating = (typeof CORPORATE_RATINGS)[number];

/** SEBI-registered credit rating agencies accepted by the API. */
export const RATING_AGENCIES = ["CRISIL", "ICRA", "CARE", "India Ratings", "Acuite", "Brickwork", "Infomerics"] as const;
export type RatingAgency = (typeof RATING_AGENCIES)[number];

export type YieldCompounding = "annual" | "semiannual" | "quarterly" | "monthly";

interface BondQuoteFieldsIn {
  issuer: string;
  isin: string; // 12 characters, ISO 6166 check digit
  coupon_rate: string; // fraction
  issue_date: string;
  maturity: string;
  face_value: string; // ₹ per bond
  clean_price?: string | null; // per ₹100 face — exactly one of clean_price / ytm
  ytm?: string | null; // fraction
  quote_date: string;
  transaction_spread?: string | null; // fraction of the clean price; null = unknown (flagged)
  citation: CitationIn;
}

export interface GsecIn extends BondQuoteFieldsIn {
  kind: "gsec" | "sdl";
  frequency: 2;
}

export interface CallIn {
  call_date: string;
  call_price: string; // per ₹100 face
}

export interface CorporateBondIn extends BondQuoteFieldsIn {
  frequency: 1 | 2 | 4 | 12;
  ytm_compounding?: YieldCompounding | null; // required with ytm
  rating: CorporateRating;
  rating_agency: RatingAgency;
  rating_date: string;
  rating_citation: CitationIn;
  listed: boolean;
  secured: boolean;
  record_date_days: number;
  call_schedule: CallIn[];
}

export interface BondQuote {
  kind: "clean_price" | "ytm";
  value: string;
  convention: string | null;
  quote_date: string;
  age_days: number;
  freshness: Freshness;
  citation_url: string;
  source_id: string;
}

export interface BondTermsView {
  issuer: string | null;
  coupon_rate: string;
  frequency: number;
  issue_date: string;
  maturity: string;
  face_value: string;
  listed: boolean;
  secured: boolean | null;
  record_date_days: number;
  calls: CallIn[];
  transaction_spread: string | null;
  day_count: "30E/360" | "ACT/ACT-SEBI";
}

export interface BondRatingView {
  rating: string;
  agency: string | null;
  rating_date: string;
  age_days: number;
  stale: boolean;
  citation_url: string | null;
}

export interface BondListItem {
  instrument_id: string;
  kind: BondKind;
  name: string;
  isin: string | null;
  origin: "manual" | "fixture" | "source";
  fixture: boolean;
  quote: BondQuote | null;
  quote_problem: string | null;
  terms: BondTermsView | null;
  rating: BondRatingView | null;
}

export interface BondList {
  as_of: string;
  quote_stale_after_days: number;
  rating_stale_after_days: number;
  items: BondListItem[];
}
