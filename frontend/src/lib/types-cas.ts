// CAS (CAMS/KFintech PDF) import shapes — backend/src/iip/services/cas.py (preview_cas_import, apply_cas_import).
// The API never returns investor PII: no name, PAN, email, address, phone, folio number or scheme name from the file.

export type CasTxnType = "buy" | "sell" | "dividend";

export interface CasRowBase {
  row: number;
  scheme: number;
  cas_type: string;
  txn_date: string | null;
}

export interface CasWillStore extends CasRowBase {
  instrument_id: string;
  instrument_name: string;
  isin: string;
  txn_type: CasTxnType;
  units: string | null;
  amount: string;
  nav: string | null;
  flags: string[];
}

export interface CasRejected extends CasRowBase {
  reason: string;
}

export interface CasScheme {
  scheme: number;
  isin: string | null;
  isin_problem: string | null;
  rta: string;
  instrument_id: string | null;
  instrument_name: string | null;
  match: string;
  segregated_portfolio: boolean;
  transactions_in_statement: number;
}

export type CasReconStatus = "OK" | "MISMATCH" | "UNMATCHED";

export interface CasReconciliation {
  scheme: number;
  isin: string | null;
  instrument_id: string | null;
  cas_opening_units: string;
  cas_closing_units: string;
  imported_net_units: string;
  difference: string;
  status: CasReconStatus;
  causes: string[];
}

export interface CasBlocking {
  code: string;
  instrument_id: string;
  message: string;
}

export interface CasPreview {
  batch_id: string;
  status: "previewed";
  applied: false;
  kind: "cas_pdf";
  label: string;
  file_sha256: string;
  issuer: string;
  statement_period: { from: string; to: string };
  schemes: CasScheme[];
  will_store: CasWillStore[];
  rejected: CasRejected[];
  ignored: CasRejected[];
  reconciliation: CasReconciliation[];
  reconciliation_ok: boolean;
  blocking: CasBlocking[];
  warnings: string[];
  already_applied: boolean;
  confirm_with: { sha256: string; accept_reconciliation_mismatches: boolean };
  privacy: string;
  note: string;
  engine_version: string;
}

export interface CasApplied {
  batch_id: string;
  status: string;
  applied: boolean;
  portfolio_id?: string;
  transactions_created?: number;
  rows_rejected?: number;
  rows_ignored?: number;
  reconciliation_mismatches_accepted?: number;
  applied_at?: string;
}
