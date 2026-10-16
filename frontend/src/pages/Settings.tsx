import { useEffect, useRef, useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { Link } from "react-router-dom";
import { Loading } from "../components/States";
import { LlmSettings } from "../components/LlmSettings";
import { DataRightsPanel } from "../components/DataRightsPanel";
import { apiMessage } from "../components/watchCommon";
import { api } from "../lib/api";
import { groupIndian } from "../lib/format";
import { useProfile } from "../lib/profile";
import type { BackupResult, EraseResult, PrivacyInventory } from "../lib/types";
import type {
  NotificationSettings,
  NotificationSettingsIn,
  NotifyChannel,
  VocabularyMode,
  VocabularySettings,
  VocabularySettingsIn,
} from "../lib/types-settings";
import { useApi } from "../lib/useApi";

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
  import_snapshots: "Pre-import safety snapshots",
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

function Erase({ backups, onDone, hosted = false }: { backups: number | null; onDone: () => void; hosted?: boolean }) {
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
      {hosted ? (
        <p className="small">
          <strong>Hosted:</strong> the rows are deleted from your Turso database, but Turso&apos;s own point-in-time backups keep
          the deleted rows until they expire under Turso&apos;s retention. There are no backup files to delete here.
        </p>
      ) : (
        <>
          <p className="small">
            <strong>Backups are not erased</strong> unless you tick the box below. Existing backup files contain your data
            {backups !== null ? ` (currently ${backups} file${backups === 1 ? "" : "s"})` : ""}.
          </p>
          <div className="field">
            <label className="choice">
              <input type="checkbox" checked={deleteBackups} onChange={(e) => setDeleteBackups(e.target.checked)} /> Also delete every
              backup file
            </label>
          </div>
        </>
      )}
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

/** The ping text when the server does not supply one (design-risk-first.md §9.4): no amounts, names, verbs or prices. */
export const DEFAULT_PING = "IIP: daily report ready (data as of DD-Mon). Open the app.";

const CHANNELS: { id: NotifyChannel; label: string; note: string }[] = [
  { id: "off", label: "Off — no notifications (default)", note: "The Today page shows the latest report when you open the app." },
  {
    id: "webpush",
    label: "Web Push",
    note: "End-to-end encrypted to your browser. On iPhone it needs the app added to the Home Screen. Planned for v2.",
  },
  {
    id: "telegram",
    label: "Telegram bot to your own chat",
    note: "Content-free ping only. Telegram stores the message on its servers.",
  },
];

/** U-09 / design-risk-first.md §9.4. Off by default; a missing or failing endpoint means off, never "on". */
function Notifications() {
  const st = useApi<NotificationSettings>("/api/settings/notifications");
  const [choice, setChoice] = useState<NotifyChannel>("off");
  const [ack, setAck] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (st.data) setChoice(st.data.channel);
  }, [st.data]);
  const unavailable = !st.loading && !st.data;
  const available = new Set<NotifyChannel>(st.data ? ["off", ...st.data.available] : ["off"]);
  const current = st.data?.channel ?? "off";
  const needsAck = choice === "telegram";
  const canSave = !unavailable && !pending && choice !== current && (!needsAck || ack);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setPending(true);
    setMsg(null);
    setErr(null);
    try {
      const body: NotificationSettingsIn = { channel: choice, acknowledge_third_party_storage: needsAck && ack };
      await api<NotificationSettings>("/api/settings/notifications", { method: "PUT", body });
      setMsg(
        choice === "off"
          ? "Saved. Notifications are off."
          : `Saved. Pings go to ${choice === "telegram" ? "Telegram" : "Web Push"} only when your L1–L5 cards change.`,
      );
      st.reload();
    } catch (ex) {
      setErr(`Not saved; the previous setting stays. ${apiMessage(ex)}`);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="card" onSubmit={save} noValidate aria-labelledby="notify-title">
      <h2 id="notify-title">Notifications</h2>
      <p className="small">
        A notification only says a new daily report is ready. It never carries amounts, fund names, prices or buy/sell words, and
        it is sent only when the cards at layers L1–L5 change; a quiet day sends nothing.
      </p>
      <p className="small">
        Exact text: <q data-testid="ping-preview">{st.data?.ping_template ?? DEFAULT_PING}</q>
      </p>
      {unavailable ? (
        <p className="small subtle" role="status">
          Notification settings are not available on this server yet, so notifications stay off.
        </p>
      ) : null}
      <fieldset disabled={st.loading}>
        <legend>Notification channel</legend>
        {CHANNELS.map((c) => (
          <div className="field" key={c.id}>
            <label className="choice">
              <input
                type="radio"
                name="notify-channel"
                value={c.id}
                checked={choice === c.id}
                disabled={!available.has(c.id)}
                onChange={() => {
                  setChoice(c.id);
                  setAck(false);
                  setMsg(null);
                }}
              />{" "}
              {c.label}
              {!available.has(c.id) ? " (not available on this server)" : ""}
            </label>
            <div className="hint">{c.note}</div>
          </div>
        ))}
      </fieldset>
      {needsAck ? (
        <div className="field">
          <label className="choice">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand Telegram stores each ping
            on its servers
          </label>
        </div>
      ) : null}
      <p className="small subtle">
        Not offered: ntfy.sh public topics (anyone who knows the topic can read it and send fake alerts) and email through a Gmail
        app password (a long-lived credential).
      </p>
      <button type="submit" className="btn" disabled={!canSave}>
        {pending ? "Saving…" : "Save notification setting"}
      </button>
      <div aria-live="polite">
        {msg ? <p className="callout small">{msg}</p> : null}
        {err ? (
          <p className="callout callout--stale small" role="alert">
            {err}
          </p>
        ) : null}
      </div>
    </form>
  );
}

/** U-11 / design-risk-first.md §7.3: neutral wording by default; badges are a private-view opt-in only. */
function Vocabulary() {
  const st = useApi<VocabularySettings>("/api/settings/vocabulary");
  const [choice, setChoice] = useState<VocabularyMode>("neutral");
  const [ack, setAck] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (st.data) setChoice(st.data.mode === "badges" ? "badges" : "neutral");
  }, [st.data]);
  const unavailable = !st.loading && !st.data;
  const current: VocabularyMode = st.data?.mode === "badges" ? "badges" : "neutral";
  const needsAck = choice === "badges";
  const canSave = !unavailable && !pending && choice !== current && (!needsAck || ack);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setPending(true);
    setMsg(null);
    setErr(null);
    try {
      const body: VocabularySettingsIn = { mode: choice, acknowledge_private_only: needsAck && ack };
      await api<VocabularySettings>("/api/settings/vocabulary", { method: "PUT", body });
      setMsg(choice === "neutral" ? "Saved. Neutral wording everywhere." : "Saved. Badges appear only in your logged-in view.");
      st.reload();
    } catch (ex) {
      setErr(`Not saved; the previous wording stays. ${apiMessage(ex)}`);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="card" onSubmit={save} noValidate aria-labelledby="vocab-title">
      <h2 id="vocab-title">Wording of signals</h2>
      <p className="small">
        Policy cards always say “your rule says”. A rule that has passed its evidence gates is shown as “entry condition met” or
        “exit condition met”, next to its rule id, version and as-of date. Exports, shares and any page without a login always keep
        the neutral wording.
      </p>
      {unavailable ? (
        <p className="small subtle" role="status">
          The wording setting is not available on this server yet, so the neutral wording is used.
        </p>
      ) : null}
      <fieldset disabled={st.loading}>
        <legend>Wording in your private view</legend>
        <div className="field">
          <label className="choice">
            <input type="radio" name="vocab" value="neutral" checked={choice === "neutral"}
              onChange={() => { setChoice("neutral"); setAck(false); setMsg(null); }} />{" "}
            Neutral wording — “entry/exit condition met” (default; your decision U-11)
          </label>
        </div>
        <div className="field">
          <label className="choice">
            <input type="radio" name="vocab" value="badges" checked={choice === "badges"} disabled={unavailable}
              onChange={() => { setChoice("badges"); setAck(false); setMsg(null); }} />{" "}
            BUY/SELL badges in my logged-in view (opt-in)
          </label>
          <div className="hint">
            Personal decision-support tool. Output of rules you configured. Not investment advice or research; not registered with
            SEBI.
          </div>
        </div>
      </fieldset>
      {needsAck ? (
        <div className="field">
          <label className="choice">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I want badges only inside my logged-in
            view; they are never exported or shared
          </label>
        </div>
      ) : null}
      <button type="submit" className="btn" disabled={!canSave}>
        {pending ? "Saving…" : "Save wording"}
      </button>
      <div aria-live="polite">
        {msg ? <p className="callout small">{msg}</p> : null}
        {err ? (
          <p className="callout callout--stale small" role="alert">
            {err}
          </p>
        ) : null}
      </div>
    </form>
  );
}

export default function Settings() {
  const inv = useApi<PrivacyInventory>("/api/privacy/inventory");
  const me = useApi<{ deploy?: string }>("/api/me");
  const hosted = me.data?.deploy === "vercel";
  const where = hosted ? "in your hosted database (Turso)" : "on this computer";
  const profile = useProfile();
  return (
    <section>
      <PageHeader title="Settings & privacy" purpose={`Your profile, what is stored ${where}, and how to export or erase it.`} />

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
        from {hosted ? "the hosted app" : "this computer"} and contain your amounts — store them carefully.
      </p>

      {hosted ? (
        <>
          <h2>Backups</h2>
          <p className="small">
            The hosted app keeps no backup files. Turso keeps point-in-time backups of your database for its retention period
            (restore from the Turso dashboard into a new database); for a copy you hold yourself, use “Export everything” above.
          </p>
        </>
      ) : (
        <Backup onDone={inv.reload} />
      )}
      <Erase
        hosted={hosted}
        backups={inv.data?.backups.count ?? null}
        onDone={() => {
          inv.reload();
          profile.reload();
        }}
      />

      <Notifications />
      <Vocabulary />
      <DataRightsPanel />

      <LlmSettings />
    </section>
  );
}
