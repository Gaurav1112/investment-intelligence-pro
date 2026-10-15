// Types for the Track 1 data-input endpoints (/api/inputs/*). Decimals are strings; dates are ISO.
// Kept separate from lib/types.ts on purpose (other tracks edit that file in parallel).

import type { CitationIn } from "./types";

export type FactsFreshness = "FRESH" | "STALE";

export interface FundFacts {
  fact_id: number;
  as_of_month: string; // YYYY-MM
  as_of_date: string; // month end
  modified_duration: string | null;
  macaulay_duration: string | null;
  ytm: string | null; // fraction
  average_maturity_years: string | null;
  expense_ratio: string | null; // fraction
  expense_ratio_kind: "TER" | "BER" | null;
  lowest_rating: string | null;
  share_below_aaa: string | null; // fraction
  share_sovereign_cash: string | null; // fraction
  citation_url: string;
  citation_note: string;
  verified_on: string;
  entered_at: string;
  age_days: number;
  freshness: FactsFreshness;
}

export interface FundFactsResponse {
  instrument_id: string;
  stale_after_days: number;
  latest: FundFacts | null;
  history: FundFacts[];
}

export interface FundFactsIn {
  as_of_month: string;
  modified_duration?: string;
  macaulay_duration?: string;
  ytm?: string;
  average_maturity_years?: string;
  expense_ratio?: string;
  expense_ratio_kind?: "TER" | "BER";
  lowest_rating?: string;
  share_below_aaa?: string;
  share_sovereign_cash?: string;
  citation: CitationIn;
}

export interface FundFactsOut {
  fact_id: number;
  instrument_id: string;
}

export type CpiBase = "2012" | "2024";

export interface CpiPoint {
  month: string;
  index: string;
  yoy_inflation_pct: string | null;
  provisional: boolean;
  source_id: string;
  source_url: string;
  retrieved_at: string;
  published_on: string;
}

export interface CpiSeries {
  series_id: string;
  base_year: CpiBase;
  points: CpiPoint[];
}

export interface CpiResponse {
  note: string;
  series: CpiSeries[];
}

export interface CpiIn {
  base_year: CpiBase;
  month: string;
  index: string;
  yoy_inflation_pct?: string;
  provisional: boolean;
  citation: CitationIn;
}

export type UpsertOutcome = "inserted" | "unchanged" | "corrected";

export interface SeriesUpsertOut {
  series_id: string;
  outcome: UpsertOutcome;
}

export interface RiskFreePoint {
  auction_date: string;
  yield_fraction: string;
  source_url: string;
  retrieved_at: string;
  quality_status: string;
}

export interface RiskFreeResponse {
  series_id: string;
  freshness: "FRESH" | "STALE" | "EXPIRED" | "UNAVAILABLE";
  latest: RiskFreePoint | null;
  points: RiskFreePoint[];
}

export interface RiskFreeIn {
  yield_fraction: string;
  citation: CitationIn;
}

// ------------------------------------------------------------------ FD card-rate tables (/api/inputs/fd-rates)

export type PrematureRateBasis = "period_card" | "min(booked,period_card)";

export interface FdRateBucket {
  min_days: number;
  max_days: number;
  rate: string; // fraction
}

export interface FdRateTable {
  table_id: number;
  institution: string;
  institution_key: string;
  as_of: string;
  premature_rate_basis: PrematureRateBasis;
  citation_url: string;
  citation_note: string;
  entered_at: string;
  buckets: FdRateBucket[];
  age_days: number;
  freshness: "MANUAL" | "STALE" | "UNKNOWN";
  current: boolean; // the table analysis uses for this bank today
}

export interface FdRatesResponse {
  as_of: string;
  stale_after_days: number;
  tables: FdRateTable[];
}

export interface FdRateTableIn {
  institution: string;
  buckets: FdRateBucket[];
  premature_rate_basis: PrematureRateBasis;
  citation: CitationIn;
}

export interface FdRateTableOut {
  table_id: number;
  institution_key: string;
}

// ------------------------------------------------------------------ MoSPI

export interface MospiFetchIn {
  base_year: 2012 | 2024;
  year: number;
  month: number;
}

export interface MospiFetchOut {
  status: "stored";
  series_id: string;
  outcome: UpsertOutcome;
  month: string; // YYYY-MM
  verified: false;
}

export interface MospiStatus {
  source_id: string;
  status: "REQUIRES_CONFIGURATION" | "CONFIGURED";
  method: "token" | "password" | null;
  env_vars: string[];
  message: string;
  verified: boolean;
}

export const RATING_CHOICES = [
  "SOVEREIGN", "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "C", "D",
  "UNRATED", "A1+", "A1", "A2+", "A2", "A3+", "A3", "A4+", "A4",
] as const;

export const SHORT_TERM_RATINGS = new Set(["A1+", "A1", "A2+", "A2", "A3+", "A3", "A4+", "A4"]);

/** Shape guards: a response that does not match the contract is treated as unavailable, never rendered as data. */
export const isFundFactsResponse = (x: unknown): x is FundFactsResponse =>
  typeof x === "object" && x !== null && "latest" in x && Array.isArray((x as FundFactsResponse).history);
export const isCpiResponse = (x: unknown): x is CpiResponse =>
  typeof x === "object" && x !== null && Array.isArray((x as CpiResponse).series);
export const isRiskFreeResponse = (x: unknown): x is RiskFreeResponse =>
  typeof x === "object" && x !== null && Array.isArray((x as RiskFreeResponse).points) && "freshness" in x;
export const isFdRatesResponse = (x: unknown): x is FdRatesResponse =>
  typeof x === "object" && x !== null && Array.isArray((x as FdRatesResponse).tables) && typeof (x as FdRatesResponse).as_of === "string";
export const isMospiStatus = (x: unknown): x is MospiStatus =>
  typeof x === "object" && x !== null && typeof (x as MospiStatus).status === "string" && Array.isArray((x as MospiStatus).env_vars);
