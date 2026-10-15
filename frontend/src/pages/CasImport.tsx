// CAS (CAMS/KFintech PDF) import: upload + password → preview (rows, rejections, reconciliation) → confirm → apply.
// Contract: backend/src/iip/services/cas.py. The password is held in component state only until the preview request is
// sent, then cleared; it is never written to storage. Results are reported only when the API says applied: true.

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, apiUpload } from "../lib/api";
import { dateLabel, inr, utcStamp } from "../lib/format";
import type { CasApplied, CasPreview, CasReconciliation } from "../lib/types-cas";
import { apiMessage } from "./Watchlist";
import "../styles/cas.css";

export const CAS_PRIVACY_TEXT =
  "Your PDF and its password are used only in memory to read the statement and are not stored or logged. Your name, PAN, email, address, phone and folio numbers are discarded; only ISINs, dates, transaction types, units, amounts and NAVs are kept.";

const CAS_REASON_TEXT: Record<string, string> = {
  UNKNOWN_ISIN: "unmatched: no stored instrument has this ISIN (names are never matched)",
  AMBIGUOUS_ISIN: "more than one stored instrument has this ISIN",
  NO_ISIN: "the statement prints no ISIN for this scheme",
  ISIN_BAD_FORMAT: "the ISIN on the statement is malformed",
  ISIN_BAD_CHECKSUM: "the ISIN on the statement fails its check digit",
  STAMP_DUTY_NOT_MODELLED: "stamp duty is not stored (no fee transaction in the ledger)",
  STT_NOT_MODELLED: "STT is not stored (no fee transaction in the ledger)",
  TDS_NOT_MODELLED: "TDS is not stored",
  INFORMATIONAL_ROW: "informational row (no units or amount)",
  SEGREGATED_PORTFOLIO: "segregated-portfolio allotment is not imported",
  GIFT_NOT_MODELLED: "gift transfers are not imported",
  REVERSAL_NOT_MODELLED: "reversals are not imported (check the reconciliation)",
  UNKNOWN_TRANSACTION_TYPE: "transaction type not recognised",
  UNCLASSIFIED_UNIT_MOVEMENT: "a unit movement that could not be classified",
  MISSING_UNITS: "units are missing",
  MISSING_AMOUNT: "amount is missing",
  UNITS_SIGN_UNEXPECTED: "units have the wrong sign for this transaction type",
  AMOUNT_SIGN_UNEXPECTED: "amount has the wrong sign for this transaction type",
  UNITS_PRECISION: "units have more than 6 decimals",
  AMOUNT_PRECISION: "amount has more than 2 decimals",
  FUTURE_DATE: "date is in the future",
  BAD_DATE: "date could not be read",
};

const CAUSE_TEXT: Record<string, string> = {
  SCHEME_UNMATCHED: "the scheme's ISIN is not in the local store, so none of its rows are imported",
  OPENING_BALANCE_NOT_IMPORTED: "the statement starts with an opening balance; units bought before the statement period are not imported",
  UNIT_ROWS_NOT_IMPORTED: "some rows that move units were rejected",
  TRANSACTIONS_DO_NOT_SUM_TO_CLOSING_BALANCE: "the transactions do not add up to the closing balance printed on the statement",
};

const TYPE_TEXT: Record<string, string> = { buy: "buy", sell: "sell", dividend: "dividend (IDCW payout)" };

function reason(code: string): string {
  return CAS_REASON_TEXT[code] ?? code;
}

function Recon({ r }: { r: CasReconciliation }) {
  return (
    <tr className={r.status === "OK" ? undefined : "cas-recon--bad"}>
      <td className="num">{r.scheme}</td>
      <td className="mono small">{r.isin ?? "—"}</td>
      <td className="num">{r.cas_opening_units}</td>
      <td className="num">{r.cas_closing_units}</td>
      <td className="num">{r.imported_net_units}</td>
      <td className="num">{r.difference}</td>
      <td>
        <span className={`cas-status cas-status--${r.status.toLowerCase()}`}>{r.status}</span>
      </td>
      <td className="small">{r.causes.map((c) => CAUSE_TEXT[c] ?? c).join("; ") || "—"}</td>
    </tr>
  );
}

export function CasImport({ portfolioId, natureTag, onApplied }: { portfolioId: string; natureTag: ReactNode; onApplied: (msg: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [preview, setPreview] = useState<CasPreview | null>(null);
  const [ack, setAck] = useState(false);
  const [result, setResult] = useState<{ kind: "status" | "alert"; msg: string } | null>(null);
  const [pending, setPending] = useState<"preview" | "apply" | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const resultRef = useRef<HTMLParagraphElement>(null);
  const previewHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);
  useEffect(() => {
    if (preview) previewHeading.current?.focus();
  }, [preview]);

  async function doPreview(e: FormEvent) {
    e.preventDefault();
    setResult(null);
    setPreview(null);
    setAck(false);
    if (!file) {
      setResult({ kind: "alert", msg: "Choose your CAS PDF first." });
      return;
    }
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("portfolio_id", portfolioId);
    form.append("password", password);
    setPassword(""); // the password leaves component state as soon as the request is built
    setPending("preview");
    try {
      setPreview(await apiUpload<CasPreview>("/api/holdings/import-cas", form));
    } catch (ex) {
      setResult({ kind: "alert", msg: `The statement was refused; nothing was stored. ${apiMessage(ex)}` });
    } finally {
      setPending(null);
    }
  }

  async function apply() {
    if (!preview) return;
    setPending("apply");
    try {
      const out = await api<CasApplied>(`/api/holdings/import-cas/${encodeURIComponent(preview.batch_id)}/apply`, {
        method: "POST",
        body: { sha256: preview.confirm_with.sha256, accept_reconciliation_mismatches: ack },
      });
      if (out.applied === true && typeof out.transactions_created === "number" && out.applied_at) {
        const mism = out.reconciliation_mismatches_accepted ?? 0;
        const msg =
          `CAS import applied: ${out.transactions_created} transaction(s) stored at ${utcStamp(out.applied_at)}; ` +
          `${out.rows_rejected ?? 0} row(s) rejected and ${out.rows_ignored ?? 0} ignored were not stored` +
          (mism ? `; ${mism} reconciliation mismatch(es) were accepted by you` : "") +
          ". A backup was taken before the change.";
        setPreview(null);
        setFile(null);
        setAck(false);
        setInputKey((k) => k + 1);
        setResult({ kind: "status", msg });
        onApplied(msg);
      } else {
        setResult({ kind: "alert", msg: "The server did not confirm that the import was applied. Do not assume anything was stored; check the transactions list." });
      }
    } catch (ex) {
      setResult({ kind: "alert", msg: `Not applied; nothing was stored. ${apiMessage(ex)}` });
    } finally {
      setPending(null);
    }
  }

  const mismatches = preview ? preview.reconciliation.filter((r) => r.status !== "OK").length : 0;
  const blocked = preview ? preview.blocking.length > 0 : false;
  const canApply = preview !== null && pending === null && preview.will_store.length > 0 && !preview.already_applied && !blocked && (mismatches === 0 || ack);

  return (
    <div className="card cas-import">
      <h3>Import CAS statement (PDF)</h3>
      <p className="small">
        A CAMS or KFintech <strong>detailed</strong> Consolidated Account Statement. Purchases, SIPs and switch-ins become buys;
        redemptions and switch-outs become sells; IDCW payouts become dividends. Schemes are matched only by the exact ISIN
        printed on the statement.
      </p>
      <p className="callout cas-privacy small" role="note">
        {CAS_PRIVACY_TEXT}
      </p>
      <form onSubmit={doPreview} noValidate autoComplete="off">
        <div className="field">
          <label htmlFor="cas-file">CAS statement (.pdf)</label>
          <input key={inputKey} id="cas-file" type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="field">
          <label htmlFor="cas-pw">PDF password</label>
          <input id="cas-pw" type="password" autoComplete="off" spellCheck={false} value={password}
            onChange={(e) => setPassword(e.target.value)} aria-describedby="cas-pw-hint" />
          <p id="cas-pw-hint" className="hint">
            Usually set by CAMS/KFintech from your PAN and date of birth. Sent once with the file, used in memory to open it, then
            discarded.
          </p>
        </div>
        <button type="submit" className="btn" disabled={pending !== null}>
          {pending === "preview" ? "Reading statement…" : "Preview CAS import"}
        </button>
      </form>
      {result ? (
        <p ref={resultRef} tabIndex={-1} className={result.kind === "alert" ? "callout callout--stale" : "callout"} role={result.kind}>
          {result.msg}
        </p>
      ) : null}
      {preview ? (
        <section aria-labelledby="cas-prev-title" className="import-preview cas-preview">
          <h4 id="cas-prev-title" ref={previewHeading} tabIndex={-1}>
            Preview of {preview.issuer} statement {preview.statement_period.from} to {preview.statement_period.to} — nothing stored yet
          </h4>
          <p className="small">
            {preview.note} Into: {natureTag}
          </p>
          <p className="small">{preview.privacy}</p>
          <p className="small mono break">SHA-256 {preview.file_sha256}</p>
          {preview.already_applied ? (
            <p className="callout callout--warn" role="alert">
              This exact statement has already been imported into this portfolio; applying it again will be refused.
            </p>
          ) : null}
          {blocked ? (
            <div className="callout callout--stale" role="alert">
              <strong>Cannot be applied</strong>
              <ul className="small">
                {preview.blocking.map((b) => (
                  <li key={`${b.code}-${b.instrument_id}`}>
                    {b.code === "OVERSELL" ? "A sale in this statement exceeds the units held: " : ""}
                    {b.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {preview.warnings.length ? (
            <div className="callout callout--warn">
              <strong>Warnings</strong>
              <ul className="small">
                {preview.warnings.map((w, i) => (
                  <li key={`${i}-${w}`}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <h4>Reconciliation: closing units on the statement vs units imported</h4>
          <div className="table-wrap table-wrap--scroll">
            <table className="table table--compact">
              <caption className="sr-only">Reconciliation per scheme</caption>
              <thead>
                <tr>
                  <th scope="col" className="num">Scheme</th>
                  <th scope="col">ISIN</th>
                  <th scope="col" className="num">Opening (CAS)</th>
                  <th scope="col" className="num">Closing (CAS)</th>
                  <th scope="col" className="num">Imported net</th>
                  <th scope="col" className="num">Difference</th>
                  <th scope="col">Status</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {preview.reconciliation.map((r) => (
                  <Recon key={r.scheme} r={r} />
                ))}
              </tbody>
            </table>
          </div>
          {mismatches ? (
            <p className="callout callout--warn small" role="alert">
              {mismatches} scheme(s) do not reconcile. Importing them leaves units in this app that differ from your statement.
            </p>
          ) : (
            <p className="small">Every matched scheme reconciles to its closing balance.</p>
          )}

          <h4>Rows that will be stored ({preview.will_store.length})</h4>
          {preview.will_store.length === 0 ? (
            <p className="small">No row can be stored from this statement.</p>
          ) : (
            <div className="table-wrap table-wrap--scroll">
              <table className="table table--compact">
                <caption className="sr-only">CAS rows that will be stored</caption>
                <thead>
                  <tr>
                    <th scope="col" className="num">Row</th>
                    <th scope="col">Matched instrument</th>
                    <th scope="col">ISIN</th>
                    <th scope="col">Type</th>
                    <th scope="col">Date</th>
                    <th scope="col" className="num">Units</th>
                    <th scope="col" className="num">Amount</th>
                    <th scope="col" className="num">NAV</th>
                    <th scope="col">Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.will_store.map((r) => (
                    <tr key={r.row}>
                      <td className="num">{r.row}</td>
                      <td>
                        {r.instrument_name} <span className="mono small subtle">{r.instrument_id}</span>
                      </td>
                      <td className="mono small">{r.isin}</td>
                      <td>
                        {TYPE_TEXT[r.txn_type] ?? r.txn_type} <span className="small subtle">({r.cas_type})</span>
                      </td>
                      <td>{r.txn_date ? dateLabel(r.txn_date) : "—"}</td>
                      <td className="num">{r.units ?? "—"}</td>
                      <td className="num">{inr(r.amount)}</td>
                      <td className="num">{r.nav ?? "—"}</td>
                      <td className="small">{r.flags.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h4>Rows rejected ({preview.rejected.length})</h4>
          {preview.rejected.length === 0 ? (
            <p className="small">None.</p>
          ) : (
            <ul className="plain-list small" aria-label="Rejected CAS rows">
              {preview.rejected.map((r) => (
                <li key={`r-${r.row}`}>
                  Row {r.row} (scheme {r.scheme}, {r.cas_type}): {reason(r.reason)} <span className="mono subtle">({r.reason})</span>
                </li>
              ))}
            </ul>
          )}
          <h4>Rows ignored ({preview.ignored.length})</h4>
          {preview.ignored.length === 0 ? (
            <p className="small">None.</p>
          ) : (
            <ul className="plain-list small" aria-label="Ignored CAS rows">
              {preview.ignored.map((r) => (
                <li key={`i-${r.row}`}>
                  Row {r.row} (scheme {r.scheme}): {reason(r.reason)} <span className="mono subtle">({r.reason})</span>
                </li>
              ))}
            </ul>
          )}
          {mismatches && !blocked ? (
            <div className="field cas-ack">
              <input id="cas-ack" type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />{" "}
              <label htmlFor="cas-ack">I have reviewed the {mismatches} reconciliation mismatch(es) and want to import anyway</label>
            </div>
          ) : null}
          <div className="row">
            <button type="button" className="btn btn--primary" onClick={apply} disabled={!canApply}>
              {pending === "apply" ? "Applying…" : `Confirm and store ${preview.will_store.length} row(s)`}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setPreview(null)} disabled={pending !== null}>
              Discard preview
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
