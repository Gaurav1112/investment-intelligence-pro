import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Empty, Loading } from "../components/States";
import { api } from "../lib/api";
import { fractionToPercent, percentToFraction, utcStamp } from "../lib/format";
import type { AlertEvaluation, AlertRow, AlertRules, AlertSeverity } from "../lib/types";
import { useApi } from "../lib/useApi";
import { FieldError, validationErrors } from "./FixedIncome";
import { apiMessage } from "./Watchlist";

// Severity is a word plus a glyph, never colour alone (ux-design §4.4).
export const SEVERITY: Record<AlertSeverity, { glyph: string; word: string; cls: string }> = {
  info: { glyph: "ⓘ", word: "Info", cls: "sev--info" },
  warning: { glyph: "⚠", word: "Warning", cls: "sev--warning" },
  critical: { glyph: "‼", word: "Critical", cls: "sev--critical" },
};

function Severity({ s }: { s: AlertSeverity }) {
  const m = SEVERITY[s] ?? { glyph: "?", word: s, cls: "" };
  return (
    <span className={`badge sev ${m.cls}`}>
      <span aria-hidden="true">{m.glyph}</span> {m.word}
    </span>
  );
}

function Ref({ a }: { a: AlertRow }) {
  const r = a.observation_ref;
  if (!r) return null;
  if (/^\d+$/.test(r) && a.kind !== "ingestion_failed")
    return (
      <Link to={`/evidence/${r}`} className="small">
        Evidence #{r}
      </Link>
    );
  return <span className="small subtle">Reference: {r}</span>;
}

function AckButton({ a, onDone }: { a: AlertRow; onDone: (msg: string) => void }) {
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setPending(true);
    setErr(null);
    try {
      await api(`/api/alerts/${encodeURIComponent(a.alert_id)}/ack`, { method: "POST", body: {} });
      onDone("Alert acknowledged.");
    } catch (e) {
      setErr(`Not acknowledged: ${apiMessage(e)}`);
      setPending(false);
    }
  }
  return (
    <>
      <button type="button" className="btn" onClick={go} disabled={pending}>
        {pending ? "Acknowledging…" : "Acknowledge"}
      </button>
      {err ? (
        <span className="field-error" role="alert">
          {err}
        </span>
      ) : null}
    </>
  );
}

// ------------------------------------------------------------------ rules editor

interface RuleForm {
  stale_data: boolean;
  maturity_on: boolean;
  maturity: string;
  hhi_on: boolean;
  hhi: string;
  decline_on: boolean;
  decline_pct: string;
  tax_on: boolean;
  tax: string;
  ingest_on: boolean;
  ingest: string;
}

function toForm(r: AlertRules): RuleForm {
  return {
    stale_data: r.stale_data,
    maturity_on: r.maturity_within_days !== null,
    maturity: r.maturity_within_days === null ? "30" : String(r.maturity_within_days),
    hhi_on: r.concentration_hhi_above !== null,
    hhi: r.concentration_hhi_above ?? "0.25",
    decline_on: r.decline_since_added_beyond !== null,
    decline_pct: r.decline_since_added_beyond === null ? "10" : fractionToPercent(r.decline_since_added_beyond),
    tax_on: r.tax_coverage_within_days !== null,
    tax: r.tax_coverage_within_days === null ? "90" : String(r.tax_coverage_within_days),
    ingest_on: r.ingestion_failed_lookback_days !== null,
    ingest: r.ingestion_failed_lookback_days === null ? "14" : String(r.ingestion_failed_lookback_days),
  };
}

const FRACTION = /^0\.[0-9]{1,6}$/;

function intIn(text: string, lo: number, hi: number): number | null {
  if (!/^\d{1,4}$/.test(text.trim())) return null;
  const n = Number.parseInt(text.trim(), 10);
  return n >= lo && n <= hi ? n : null;
}

/** Form → AlertRules, or field problems. Thresholds stay decimal strings end to end. */
export function rulesFromForm(f: RuleForm): { rules: AlertRules | null; problems: Record<string, string> } {
  const p: Record<string, string> = {};
  const maturity = f.maturity_on ? intIn(f.maturity, 1, 3650) : null;
  if (f.maturity_on && maturity === null) p["maturity_within_days"] = "Enter a whole number of days from 1 to 3650.";
  const hhi = f.hhi.trim();
  if (f.hhi_on && !FRACTION.test(hhi)) p["concentration_hhi_above"] = "Enter a decimal between 0 and 1 with up to 6 decimals, e.g. 0.25.";
  const decline = f.decline_on ? percentToFraction(f.decline_pct) : null;
  if (f.decline_on && (decline === null || decline === "invalid" || !FRACTION.test(decline)))
    p["decline_since_added_beyond"] = "Enter a percentage above 0 and below 100 with up to 4 decimals, e.g. 10.";
  const tax = f.tax_on ? intIn(f.tax, 1, 3650) : null;
  if (f.tax_on && tax === null) p["tax_coverage_within_days"] = "Enter a whole number of days from 1 to 3650.";
  const ingest = f.ingest_on ? intIn(f.ingest, 1, 365) : null;
  if (f.ingest_on && ingest === null) p["ingestion_failed_lookback_days"] = "Enter a whole number of days from 1 to 365.";
  if (Object.keys(p).length) return { rules: null, problems: p };
  return {
    rules: {
      stale_data: f.stale_data,
      maturity_within_days: maturity,
      concentration_hhi_above: f.hhi_on ? hhi : null,
      decline_since_added_beyond: f.decline_on && decline !== null && decline !== "invalid" ? decline : null,
      tax_coverage_within_days: tax,
      ingestion_failed_lookback_days: ingest,
    },
    problems: {},
  };
}

function RuleRow({
  id,
  on,
  setOn,
  label,
  value,
  setValue,
  unit,
  hint,
  error,
}: {
  id: string;
  on: boolean;
  setOn: (b: boolean) => void;
  label: string;
  value: string;
  setValue: (s: string) => void;
  unit: string;
  hint: string;
  error: string | undefined;
}) {
  return (
    <div className="field">
      <label className="choice">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} /> {label}
      </label>
      <div className="row-tight">
        <label htmlFor={id} className="sr-only">
          {label} — threshold ({unit})
        </label>
        <input id={id} inputMode="decimal" value={value} disabled={!on} onChange={(e) => setValue(e.target.value)} size={10}
          aria-invalid={Boolean(error)} aria-describedby={`${id}-hint ${id}-err`} />
        <span className="small">{unit}</span>
      </div>
      <div id={`${id}-hint`} className="hint">
        {hint}
      </div>
      <FieldError id={`${id}-err`} msg={error} />
    </div>
  );
}

function RulesEditor() {
  const rules = useApi<AlertRules>("/api/alerts/rules");
  const [form, setForm] = useState<RuleForm | null>(null);
  const [local, setLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const okRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (rules.data) setForm(toForm(rules.data));
  }, [rules.data]);
  useEffect(() => {
    if (ok) okRef.current?.focus();
  }, [ok]);
  if (rules.loading) return <Loading label="Loading your alert rules" />;
  if (rules.error)
    return (
      <p className="callout callout--stale" role="alert">
        Rules could not be loaded: {apiMessage(rules.error)}
      </p>
    );
  if (!form) return null;
  const fieldErrs = validationErrors(error);
  const server = fieldErrs && Object.keys(fieldErrs).length ? fieldErrs : null;
  const errs = { ...(server ?? {}), ...local };
  const set = (patch: Partial<RuleForm>) => setForm({ ...form, ...patch });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setOk(null);
    const { rules: body, problems } = rulesFromForm(form);
    setLocal(problems);
    if (!body) return;
    setPending(true);
    setError(null);
    try {
      const saved = await api<AlertRules>("/api/alerts/rules", { method: "PUT", body });
      setForm(toForm(saved));
      setOk("Rules saved. They apply the next time rules are evaluated.");
    } catch (ex) {
      setError(ex);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} noValidate aria-labelledby="rules-title">
      <h2 id="rules-title">Your rules</h2>
      <p className="small subtle">
        Starting values are defaults you can change, not advice. Untick a rule to turn it off. Rules look at actual portfolios
        and your watchlist; hypothetical portfolios are never checked.
      </p>
      <div className="field">
        <label className="choice">
          <input type="checkbox" checked={form.stale_data} onChange={(e) => set({ stale_data: e.target.checked })} /> Stale data for
          held or watched instruments
        </label>
      </div>
      <RuleRow id="r-maturity" on={form.maturity_on} setOn={(b) => set({ maturity_on: b })} label="Maturity within"
        value={form.maturity} setValue={(v) => set({ maturity: v })} unit="days" hint="Deposits and bonds maturing within this many days."
        error={errs["maturity_within_days"]} />
      <RuleRow id="r-hhi" on={form.hhi_on} setOn={(b) => set({ hhi_on: b })} label="Concentration (HHI) above"
        value={form.hhi} setValue={(v) => set({ hhi: v })} unit="index, 0 to 1"
        hint="A decimal such as 0.25 (the band edge used in the risk methodology). 1 means everything in one holding."
        error={errs["concentration_hhi_above"]} />
      <RuleRow id="r-decline" on={form.decline_on} setOn={(b) => set({ decline_on: b })} label="Decline since added beyond"
        value={form.decline_pct} setValue={(v) => set({ decline_pct: v })} unit="% (absolute, not annualised)"
        hint="For watched funds: NAV change since the day you added it, e.g. 10 for a fall of more than 10 %."
        error={errs["decline_since_added_beyond"]} />
      <RuleRow id="r-tax" on={form.tax_on} setOn={(b) => set({ tax_on: b })} label="Tax rule set coverage ending within"
        value={form.tax} setValue={(v) => set({ tax: v })} unit="days" hint="Notifies before the loaded tax rules stop covering dates."
        error={errs["tax_coverage_within_days"]} />
      <RuleRow id="r-ingest" on={form.ingest_on} setOn={(b) => set({ ingest_on: b })} label="Failed data ingestion in the last"
        value={form.ingest} setValue={(v) => set({ ingest: v })} unit="days" hint="Any data-source run that failed in this window."
        error={errs["ingestion_failed_lookback_days"]} />
      {ok ? (
        <p ref={okRef} tabIndex={-1} className="callout" role="status">
          {ok}
        </p>
      ) : null}
      {error ? (
        <p className="callout callout--stale" role="alert">
          Not saved: {server ? `the server rejected ${Object.keys(server).length} field(s) (marked above).` : apiMessage(error)}
        </p>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={pending}>
        {pending ? "Saving…" : "Save rules"}
      </button>
    </form>
  );
}

// ------------------------------------------------------------------ page

export default function Alerts() {
  const [showAcked, setShowAcked] = useState(true);
  const list = useApi<{ items: AlertRow[] }>(`/api/alerts?include_acknowledged=${showAcked ? "true" : "false"}`);
  const [status, setStatus] = useState<{ kind: "status" | "alert"; msg: string } | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (status) statusRef.current?.focus();
  }, [status]);

  async function evaluate() {
    setEvaluating(true);
    setStatus(null);
    try {
      const r = await api<AlertEvaluation>("/api/alerts/evaluate", { method: "POST", body: {} });
      const skipped = r.skipped_portfolios.length ? ` Skipped portfolios: ${r.skipped_portfolios.join("; ")}.` : "";
      setStatus({
        kind: "status",
        msg: `Rules evaluated at ${utcStamp(r.evaluated_at)}: ${r.triggered} condition(s) met, ${r.created.length} new alert(s), ${r.already_present} already listed. Delivery: ${r.delivery}.${skipped}`,
      });
      list.reload();
    } catch (e) {
      setStatus({ kind: "alert", msg: `Rules could not be evaluated: ${apiMessage(e)}` });
    } finally {
      setEvaluating(false);
    }
  }

  const items = list.data?.items ?? [];
  return (
    <section>
      <h1>Alerts</h1>
      <p className="muted">
        Each alert means one of your own rules was met; it reports what was observed and when. Alerts are stored on this computer
        only and never suggest a trade.
      </p>
      <div className="row">
        <button type="button" className="btn btn--primary" onClick={evaluate} disabled={evaluating}>
          {evaluating ? "Evaluating…" : "Evaluate rules now"}
        </button>
        <label className="choice">
          <input type="checkbox" checked={showAcked} onChange={(e) => setShowAcked(e.target.checked)} /> Show acknowledged alerts
        </label>
      </div>
      {status ? (
        <p ref={statusRef} tabIndex={-1} className={status.kind === "alert" ? "callout callout--stale" : "callout"} role={status.kind}>
          {status.msg}
        </p>
      ) : null}
      {list.loading ? (
        <Loading label="Loading alerts" />
      ) : list.error ? (
        <div className="state state--error" role="alert">
          <p>Alerts could not be loaded: {apiMessage(list.error)}</p>
          <button type="button" className="btn" onClick={list.reload}>
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <Empty title={showAcked ? "No alerts yet" : "No unacknowledged alerts"}>
          <p>
            Alerts appear here when you press “Evaluate rules now” and one of your rules below is met. Data problems are also listed
            on <Link to="/data-health">Data health</Link>.
          </p>
        </Empty>
      ) : (
        <ul className="plain-list alert-list" aria-label="Alerts">
          {items.map((a) => (
            <li key={a.alert_id} className={`card alert${a.acknowledged_at ? " is-acked" : ""}`}>
              <div className="row-tight">
                <Severity s={a.severity} />
                <span className="small subtle">{a.kind.replace(/_/g, " ")}</span>
                <span className="small subtle">raised {utcStamp(a.created_at)}</span>
              </div>
              <p className="alert__msg">{a.message}</p>
              <div className="row-tight small">
                <span>Source: {a.source_id ?? "not recorded"}</span>
                <Ref a={a} />
                {a.acknowledged_at ? (
                  <span className="subtle">Acknowledged {utcStamp(a.acknowledged_at)}</span>
                ) : (
                  <AckButton
                    a={a}
                    onDone={(m) => {
                      setStatus({ kind: "status", msg: m });
                      list.reload();
                    }}
                  />
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <RulesEditor />
    </section>
  );
}
