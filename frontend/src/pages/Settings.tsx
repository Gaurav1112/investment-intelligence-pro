import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Loading } from "../components/States";
import { api } from "../lib/api";
import { groupIndian } from "../lib/format";
import { useProfile } from "../lib/profile";
import type { BackupResult, EraseResult, PrivacyInventory } from "../lib/types";
import { useApi } from "../lib/useApi";
import { apiMessage } from "./Watchlist";

/** The exact phrase the backend requires (services/portfolio.py EraseIn.confirm, Literal["ERASE ALL MY DATA"]). */
export const ERASE_PHRASE = "ERASE ALL MY DATA";

const TABLE_TEXT: Record<string, string> = {
  transactions: "Transactions",
  portfolios: "Portfolios",
  watchlist: "Watchlist entries",
  alerts: "Alerts",
  runs: "Saved analysis runs",
  audit_events: "Audit log entries",
  settings: "Settings (incl. alert rules and import previews)",
  profiles: "Objective profile",
  sources: "Data sources",
  ingestion_runs: "Ingestion runs",
  issuers: "Issuers",
  instruments: "Instruments",
  mf_schemes: "Mutual fund schemes",
  bond_terms: "Bond terms",
  deposit_terms: "Deposit terms",
  observations: "Observations (prices, NAVs, yields)",
};

function Counts({ tables, caption }: { tables: Record<string, number>; caption: string }) {
  return (
    <div className="table-wrap">
      <table className="table table--compact">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">What</th>
            <th scope="col" className="num">Rows</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(tables).map(([k, n]) => (
            <tr key={k}>
              <td>{TABLE_TEXT[k] ?? k}</td>
              <td className="num">{groupIndian(String(n))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Inventory({ inv }: { inv: PrivacyInventory }) {
  return (
    <>
      <p className="small subtle">{inv.note}</p>
      <div className="grid grid--2">
        <div>
          <Counts tables={inv.user_data.tables} caption="Your data (erased by “Erase all”)" />
          <p className="small">Pending import previews (not applied): {inv.user_data.pending_import_previews}</p>
        </div>
        <Counts tables={inv.public_market_data_kept_on_erase.tables} caption="Public market data (kept on erase)" />
      </div>
      <p className="small">
        Backups on disk: {inv.backups.count} — {inv.backups.note}.
      </p>
    </>
  );
}

function Backup({ onDone }: { onDone: () => void }) {
  const [res, setRes] = useState<BackupResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const out = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (res || err) out.current?.focus();
  }, [res, err]);
  async function go() {
    setPending(true);
    setErr(null);
    setRes(null);
    try {
      setRes(await api<BackupResult>("/api/backup", { method: "POST", body: {} }));
      onDone();
    } catch (e) {
      setErr(`Backup failed; nothing was written. ${apiMessage(e)}`);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="card">
      <h2>Backup</h2>
      <p className="small">Writes a copy of the database to the local backups folder and checks its integrity.</p>
      <button type="button" className="btn" onClick={go} disabled={pending}>
        {pending ? "Backing up…" : "Back up now"}
      </button>
      <div ref={out} tabIndex={-1}>
        {res ? (
          <div className="callout" role="status">
            <p>Backup written. Integrity check: {res.integrity}.</p>
            <dl className="kv small">
              <dt>Path</dt>
              <dd className="mono break">{res.path}</dd>
              <dt>Size</dt>
              <dd>{groupIndian(String(res.bytes))} bytes</dd>
              <dt>SHA-256</dt>
              <dd className="mono break">{res.sha256}</dd>
              <dt>Schema version</dt>
              <dd>{res.schema_version}</dd>
            </dl>
          </div>
        ) : null}
        {err ? (
          <p className="callout callout--stale" role="alert">
            {err}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function Erase({ backups, onDone }: { backups: number | null; onDone: () => void }) {
  const [typed, setTyped] = useState("");
  const [deleteBackups, setDeleteBackups] = useState(false);
  const [res, setRes] = useState<EraseResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const out = useRef<HTMLDivElement>(null);
  const matches = typed === ERASE_PHRASE;
  useEffect(() => {
    if (res || err) out.current?.focus();
  }, [res, err]);
  async function go(e: FormEvent) {
    e.preventDefault();
    if (!matches) {
      setErr(`Type the phrase exactly, in capitals: ${ERASE_PHRASE}`);
      return;
    }
    setPending(true);
    setErr(null);
    setRes(null);
    try {
      const r = await api<EraseResult>("/api/privacy/erase", { method: "POST", body: { confirm: ERASE_PHRASE, delete_backups: deleteBackups } });
      setRes(r);
      setTyped("");
      onDone();
    } catch (ex) {
      setErr(`Nothing was erased. ${apiMessage(ex)}`);
    } finally {
      setPending(false);
    }
  }
  const total = res ? Object.values(res.deleted_rows).reduce((a, b) => a + b, 0) : 0;
  return (
    <form className="card danger-zone" onSubmit={go} noValidate aria-labelledby="erase-title">
      <h2 id="erase-title">Erase all my data</h2>
      <p className="small">
        Permanently deletes your profile, portfolios, transactions, watchlist, alerts, saved runs, settings and audit log from the
        database, then compacts the files so the bytes are gone. Public market data (instruments, prices, sources) is kept. This
        cannot be undone — export first if you may want the data back.
      </p>
      <p className="small">
        <strong>Backups are not erased</strong> unless you tick the box below. Existing backup files contain your data
        {backups !== null ? ` (currently ${backups} file${backups === 1 ? "" : "s"})` : ""}.
      </p>
      <div className="field">
        <label className="choice">
          <input type="checkbox" checked={deleteBackups} onChange={(e) => setDeleteBackups(e.target.checked)} /> Also delete every backup file
        </label>
      </div>
      <div className="field">
        <label htmlFor="erase-confirm">
          Type <code>{ERASE_PHRASE}</code> to confirm
        </label>
        <input id="erase-confirm" className="input-wide" autoComplete="off" spellCheck={false} value={typed}
          onChange={(e) => setTyped(e.target.value)} aria-describedby="erase-hint" />
        <div id="erase-hint" className="hint">
          {matches ? "Phrase matches." : "The button stays disabled until the phrase matches exactly (capitals, single spaces)."}
        </div>
      </div>
      <button type="submit" className="btn btn--danger" disabled={!matches || pending}>
        {pending ? "Erasing…" : "Erase all my data"}
      </button>
      <div ref={out} tabIndex={-1}>
        {res ? (
          <div className="callout" role="status">
            <p>
              Erased {groupIndian(String(total))} row(s) of your data. Backups deleted: {res.backups_deleted}; backups remaining:{" "}
              {res.backups_remaining}
              {res.backups_remaining > 0 ? " (these still contain your data)" : ""}.
            </p>
            <p className="small">Kept: {res.kept}.</p>
          </div>
        ) : null}
        {err ? (
          <p className="callout callout--stale" role="alert">
            {err}
          </p>
        ) : null}
      </div>
    </form>
  );
}

export default function Settings() {
  const inv = useApi<PrivacyInventory>("/api/privacy/inventory");
  const profile = useProfile();
  return (
    <section>
      <h1>Settings &amp; privacy</h1>

      <h2>Profile</h2>
      <p>
        Your amount, date, objective, loss tolerance and tax details are set on the objectives page.{" "}
        <Link to="/onboarding" className="btn">
          Edit objectives
        </Link>
      </p>

      <h2>What is stored</h2>
      {inv.loading ? (
        <Loading label="Loading the stored-data inventory" />
      ) : inv.error || !inv.data ? (
        <div className="state state--error" role="alert">
          <p>The inventory could not be loaded: {apiMessage(inv.error)}</p>
          <button type="button" className="btn" onClick={inv.reload}>
            Try again
          </button>
        </div>
      ) : (
        <Inventory inv={inv.data} />
      )}

      <h2>Export</h2>
      <p>
        <a className="btn" href="/api/privacy/export" download>
          Export everything (JSON)
        </a>{" "}
        <a className="btn" href="/api/privacy/export.csv" download>
          Export transactions (CSV)
        </a>
      </p>
      <p className="small subtle">
        The JSON file holds every user table with a checksum manifest; the CSV holds your transactions. Both download straight
        from this computer and contain your amounts — store them carefully.
      </p>

      <Backup onDone={inv.reload} />
      <Erase
        backups={inv.data?.backups.count ?? null}
        onDone={() => {
          inv.reload();
          profile.reload();
        }}
      />

      <h2>Local language model</h2>
      <p className="small">
        An optional local LLM for wording is not part of version 1. Nothing is sent to any AI service; every number and sentence
        comes from the deterministic engine and dated sources.
      </p>
    </section>
  );
}
