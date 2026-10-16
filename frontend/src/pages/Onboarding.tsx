// Setup (C02, PLAN.md wave 2): one CAS upload and about six answers — tax, emergency fund, goals, a loss limit in ₹ per
// goal (shown next to the crash history, before any return figure), recovery time, and optional extras. A return aim is
// never asked here: it appears only on the Goals page's feasibility view, as a historical frequency (PLAN §2.2).
// The "Discovery objectives" tab keeps the earlier objectives form that Discovery's personalised ranking reads.
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { OBJECTIVES, useProfile } from "../lib/profile";
import type { ObjectiveCode, PortfolioCreated, PortfolioListItem, Profile, ProfileStatus } from "../lib/types";
import {
  EMPTY_ANSWERS,
  fallLabel,
  recoveryText,
  stressBasis,
  rupeesTimesFraction,
  setupClearList,
  yearsToMonths,
  type SetupAnswers,
  type SetupAnswersIn,
  type SetupGoalIn,
  type SetupState,
  type StressHistory,
} from "../lib/types-goals";
import { useApi, useMutation } from "../lib/useApi";
import { compareDecimals, dateLabel, fractionToPercent as fractionToPct, inr, percentToFraction as pctToFraction } from "../lib/format";
import { ErrorState, Loading } from "../components/States";

// Lazily loaded (a dynamic import is allowed across pages: pageImports.test.ts), so the CAS parser UI is fetched only here.
const CasImport = lazy(() => import("./CasImport").then((m) => ({ default: m.CasImport })));

const EMPTY: Profile = {
  amount: null,
  withdrawal_date: null,
  objective: null,
  loss_acceptable: null,
  max_loss_fraction: null,
  early_need: null,
  max_days_to_cash: null,
  credit_floor: null,
  excluded_kinds: [],
  tax_regime: null,
  slab_rate: null,
  return_aspiration: null,
};

const STEPS = ["Amount", "Withdrawal date", "Objective", "Loss & early need", "Liquidity & extras", "Review"] as const;
const DECIMAL = /^\d+(\.\d+)?$/;
const PCT_HELP = "enter a number only, for example 10 or 12.5 (no % sign, no comma).";

interface FieldError {
  /** id of the input; its visible message has the id `${field}-error`. */
  field: string;
  step: number;
  message: string;
}

/** FastAPI 422 → the server's own reasons, in its words (e.g. "growth objectives require accepting some loss …"). */
function serverReasons(e: ApiError): string {
  const detail = (e.detail as { detail?: unknown } | undefined)?.detail;
  const msgs = Array.isArray(detail)
    ? detail.map((d) => String((d as { msg?: unknown }).msg ?? "").replace(/^Value error, /, "")).filter(Boolean)
    : [];
  return msgs.length ? `${msgs.join("; ")}.` : "some values are not acceptable.";
}

function ObjectivesWizard() {
  const { status, reload } = useProfile();
  const navigate = useNavigate();
  const [p, setP] = useState<Profile>(EMPTY);
  const [step, setStep] = useState(0);
  const [lossPct, setLossPct] = useState("");
  const [slabPct, setSlabPct] = useState("");
  const [result, setResult] = useState<ProfileStatus | null>(null);
  const [summaryKey, setSummaryKey] = useState(0);
  const [focusField, setFocusField] = useState<string | null>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const save = useMutation<Profile, ProfileStatus>("PUT", "/api/profile");

  useEffect(() => {
    if (status) {
      setP(status.profile);
      setLossPct(fractionToPct(status.profile.max_loss_fraction));
      setSlabPct(fractionToPct(status.profile.slab_rate));
    }
  }, [status]);

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setP((x) => ({ ...x, [k]: v }));
  const amountValid = p.amount === null || DECIMAL.test(p.amount);
  const lossFr = pctToFraction(lossPct);
  const slabFr = pctToFraction(slabPct);
  // Save stays enabled; problems are listed on submit (WCAG 3.3.1/3.3.3). The loss limit only counts while its input is
  // shown ("Yes, up to a limit"): a leftover invalid value behind "No" used to block Save with nothing visible.
  const growth = p.objective === "D_growth" || p.objective === "E_aggressive_growth";
  const over = (fr: string | null | "invalid", max: number) => fr !== null && fr !== "invalid" && Number(fr) > max;
  const errors: FieldError[] = [
    ...(!amountValid ? [{ field: "amount", step: 0, message: "Investable amount: digits only, for example 500000." }] : []),
    // Growth objectives (D, E) need an explicit loss budget — the server refuses them otherwise (profile._consistency).
    ...(growth && p.loss_acceptable !== true
      ? [{ field: "loss-yes", step: 3, message: "You chose a growth objective (D or E), which needs a loss limit: choose “Yes, up to a limit” and enter it, or go back and pick objective A, B or C." }]
      : []),
    ...(p.loss_acceptable === true && lossFr === "invalid"
      ? [{ field: "loss", step: 3, message: `Largest loss you would accept: ${PCT_HELP}` }]
      : []),
    ...(growth && p.loss_acceptable === true && lossFr === null
      ? [{ field: "loss", step: 3, message: "Largest loss you would accept: required for growth objectives, for example 10." }]
      : []),
    ...(p.loss_acceptable === true && over(lossFr, 1)
      ? [{ field: "loss", step: 3, message: "Largest loss you would accept: at most 100 %." }]
      : []),
    ...(slabFr === "invalid" ? [{ field: "slab", step: 4, message: `Income-tax slab: ${PCT_HELP}` }] : []),
    // The engine models the new regime only; a slab without it was silently replaced by the illustrative 30 % slab.
    ...(slabFr !== null && slabFr !== "invalid" && p.tax_regime !== "new"
      ? [{ field: "regime", step: 4, message: "Your slab is used only under the new tax regime (the old regime is not modelled): tick “I file under the new tax regime”, or leave the slab empty." }]
      : []),
    ...(over(slabFr, 0.5) ? [{ field: "slab", step: 4, message: "Income-tax slab: at most 50 %." }] : []),
  ];
  const errorFor = (field: string) => errors.find((x) => x.field === field);
  // Not shown before the question is answered: only after "No", or once a save was attempted.
  const showLossYes = Boolean(errorFor("loss-yes")) && (p.loss_acceptable === false || summaryKey > 0);
  const showSummary = summaryKey > 0 && errors.length > 0;

  useEffect(() => {
    if (summaryKey > 0) summaryRef.current?.focus();
  }, [summaryKey]);
  useEffect(() => {
    if (focusField === null) return;
    document.getElementById(focusField)?.focus();
    setFocusField(null);
  }, [focusField, step]);

  const describedBy = (field: string, hint: string) => (errorFor(field) ? `${hint} ${field}-error` : hint);
  const fieldError = (field: string) => {
    const err = errorFor(field);
    return err ? (
      <div id={`${field}-error`} className="hint field-error">
        {err.message}
      </div>
    ) : null;
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (errors.length) {
      setSummaryKey((k) => k + 1); // re-focus (and re-announce) the summary on every failed attempt
      return;
    }
    setSummaryKey(0);
    const loss = lossFr === "invalid" ? null : lossFr;
    const body: Profile = {
      ...p,
      max_loss_fraction: p.loss_acceptable === false ? null : loss,
      slab_rate: slabFr === "invalid" ? null : slabFr,
      // return_aspiration is kept as stored (spread above): the aim is no longer asked here (C02, PLAN §2.2).
    };
    const out = await save.run(body);
    if (out) {
      setResult(out);
      reload();
    }
  }


  return (
    <>
      <p className="muted">
        Five details are needed before anything is ordered <em>for you</em>. You can skip any of them; the app then stays in
        exploration mode and shows illustrative examples only.
      </p>
      <ol className="steps" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined}>
            <button type="button" className="btn btn--ghost" onClick={() => setStep(i)}>
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>
      <form onSubmit={submit} className="card" noValidate>
        {showSummary ? (
          <div
            key={summaryKey}
            className="callout callout--stale"
            role="alert"
            tabIndex={-1}
            ref={summaryRef}
            aria-labelledby="onb-errors-title"
          >
            <p id="onb-errors-title">
              <strong>Not saved yet. Please correct {errors.length === 1 ? "this value" : "these values"}:</strong>
            </p>
            <ul>
              {errors.map((x) => (
                <li key={x.field}>
                  <a
                    href={`#${x.field}`}
                    onClick={(ev) => {
                      ev.preventDefault();
                      setStep(x.step);
                      setFocusField(x.field);
                    }}
                  >
                    {x.message} (step {x.step + 1}, {STEPS[x.step]})
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {step === 0 && (
          <div className="field">
            <label htmlFor="amount">Investable amount (₹)</label>
            <span className="money">
            <input id="amount"
              inputMode="decimal"
              value={p.amount ?? ""}
              onChange={(e) => set("amount", e.target.value.replace(/[,\s₹]/g, "") || null)}
              aria-invalid={!amountValid}
              aria-describedby={describedBy("amount", "amount-hint")}
            />
            </span>
            <div id="amount-hint" className="hint">
              {p.amount && amountValid ? inr(p.amount) : "Digits only, e.g. 500000"}
            </div>
            {fieldError("amount")}
          </div>
        )}
        {step === 1 && (
          <div className="field">
            <label htmlFor="wd">When must the money be available?</label>
            <input id="wd" type="date" value={p.withdrawal_date ?? ""} onChange={(e) => set("withdrawal_date", e.target.value || null)} />
            <div className="hint">Horizons of 1, 3, 6 and 12 months are first-class; longer ones are for comparison.</div>
          </div>
        )}
        {step === 2 && (
          <fieldset className="field">
            <legend>What matters most for this money?</legend>
            {(Object.keys(OBJECTIVES) as ObjectiveCode[]).map((k) => (
              <label key={k} className="choice">
                <input type="radio" name="objective" checked={p.objective === k} onChange={() => set("objective", k)} />
                <strong>
                  {OBJECTIVES[k]?.code} · {OBJECTIVES[k]?.title}
                </strong>
                <span className="small muted"> — {OBJECTIVES[k]?.blurb}</span>
              </label>
            ))}
            {growth ? (
              <p className="hint">Growth objectives need a loss limit: the next step asks how much loss you would accept.</p>
            ) : null}
          </fieldset>
        )}
        {step === 3 && (
          <>
            <fieldset className="field">
              <legend>Is any loss of the amount you invest acceptable?</legend>
              <label className="choice">
                <input type="radio" name="loss" checked={p.loss_acceptable === false} onChange={() => set("loss_acceptable", false)} /> No
              </label>
              <label className="choice">
                <input type="radio" name="loss" id="loss-yes" checked={p.loss_acceptable === true} onChange={() => set("loss_acceptable", true)}
                  aria-invalid={showLossYes} aria-describedby={showLossYes ? "loss-yes-error" : undefined} /> Yes, up
                to a limit
              </label>
              {showLossYes ? fieldError("loss-yes") : null}
            </fieldset>
            {p.loss_acceptable ? (
              <div className="field">
                <label htmlFor="loss">Largest loss you would accept (% of the amount)</label>
                <span className="pct">
                <input
                  id="loss"
                  inputMode="decimal"
                  value={lossPct}
                  onChange={(e) => setLossPct(e.target.value)}
                  aria-invalid={Boolean(errorFor("loss"))}
                  aria-describedby={describedBy("loss", "loss-hint")}
                />
                </span>
                <div id="loss-hint" className="hint">
                  {growth ? "Required for growth objectives." : "Used as your loss budget."} A number only, for example 10.
                </div>
                {fieldError("loss")}
              </div>
            ) : null}
            <fieldset className="field">
              <legend>Might you need the money before that date?</legend>
              {(["unlikely", "possible", "likely"] as const).map((v) => (
                <label key={v} className="choice">
                  <input type="radio" name="early" checked={p.early_need === v} onChange={() => set("early_need", v)} /> {v}
                </label>
              ))}
            </fieldset>
          </>
        )}
        {step === 4 && (
          <>
            <div className="field">
              <label htmlFor="dtc">If needed early, within how many days must it be in your account?</label>
              <input
                id="dtc"
                type="number"
                min={0}
                value={p.max_days_to_cash ?? ""}
                onChange={(e) => set("max_days_to_cash", e.target.value === "" ? null : Number.parseInt(e.target.value, 10))}
              />
            </div>
            <div className="field">
              <label htmlFor="credit">Lowest credit rating you accept (bonds)</label>
              <select id="credit" value={p.credit_floor ?? ""} onChange={(e) => set("credit_floor", e.target.value || null)}>
                <option value="">No floor</option>
                {["SOVEREIGN", "AAA", "AA+", "AA", "AA-", "A+", "A"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="choice">
                <input
                  type="checkbox"
                  id="regime"
                  checked={p.tax_regime === "new"}
                  onChange={(e) => set("tax_regime", e.target.checked ? "new" : null)}
                  aria-invalid={Boolean(errorFor("regime"))}
                  aria-describedby={errorFor("regime") ? "regime-error" : undefined}
                />{" "}
                I file under the new tax regime
              </label>
              {fieldError("regime")}
            </div>
            <div className="field">
              <label htmlFor="slab">Your marginal income-tax slab (%, new regime) — optional</label>
              <span className="pct">
              <input
                id="slab"
                inputMode="decimal"
                value={slabPct}
                onChange={(e) => setSlabPct(e.target.value)}
                aria-invalid={Boolean(errorFor("slab"))}
                aria-describedby={describedBy("slab", "slab-hint")}
              />
              </span>
              <div id="slab-hint" className="hint">
                Used only with the new regime ticked above. If empty, after-tax figures use a labelled illustrative 30 % slab, not yours.
              </div>
              {fieldError("slab")}
            </div>
            <div className="field">
              <label htmlFor="surcharge">Surcharge band (only if your total income exceeds ₹50 lakh) — optional</label>
              <select id="surcharge" value={p.surcharge_rate ?? ""} onChange={(e) => set("surcharge_rate", e.target.value || null)}>
                <option value="">Not given (after-tax figures note that tax may be understated above ₹50 lakh)</option>
                <option value="0">None (total income up to ₹50 lakh)</option>
                <option value="0.10">10 % (₹50 lakh – ₹1 crore)</option>
                <option value="0.15">15 % (₹1 – 2 crore)</option>
                <option value="0.25">25 % (above ₹2 crore)</option>
              </select>
            </div>
          </>
        )}
        {step === 5 && (
          <div>
            <h2>Review</h2>
            <dl className="kv">
              <dt>Amount</dt>
              <dd>{p.amount && amountValid ? inr(p.amount) : "not given"}</dd>
              <dt>Withdrawal date</dt>
              <dd>{p.withdrawal_date ?? "not given"}</dd>
              <dt>Objective</dt>
              <dd>{p.objective ? OBJECTIVES[p.objective]?.title : "not given"}</dd>
              <dt>Loss acceptable</dt>
              <dd>{p.loss_acceptable === null ? "not given" : p.loss_acceptable ? `yes, up to ${lossPct || "?"} %` : "no"}</dd>
              <dt>Early need</dt>
              <dd>{p.early_need ?? "not given"}</dd>
              <dt>Income-tax slab</dt>
              <dd>{slabPct ? `${slabPct} %${p.tax_regime === "new" ? " (new regime)" : " — not used until the new regime is ticked"}` : "not given"}</dd>
            </dl>
          </div>
        )}
        {save.error ? (
          <p className="callout callout--stale" role="alert">
            Not saved:{" "}
            {save.error instanceof ApiError && save.error.status === 422 ? serverReasons(save.error) : "the request failed."}
          </p>
        ) : null}
        {result ? (
          <div className="callout" role="status">
            <p>
              Saved. Mode: <strong>{result.mode}</strong>.{" "}
              {result.missing.length ? `Still missing: ${result.missing.join("; ")}.` : "All five details are present."}
            </p>
            {result.conflicts.map((c) => (
              <p key={c} className="callout callout--warn">
                {c}
              </p>
            ))}
            <button type="button" className="btn btn--primary" onClick={() => navigate("/discover")}>
              Go to Discovery
            </button>
          </div>
        ) : null}
        <div className="row">
          <button type="button" className="btn" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            Back
          </button>
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn" onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          ) : null}
          <button type="submit" className="btn btn--primary" disabled={save.pending}>
            {save.pending ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </>
  );
}


// ================================================================== wave-2 setup

const SETUP_STEPS = ["Upload CAS", "Tax", "Emergency fund", "Goals", "Loss limit", "Recovery time", "Optional extras", "Review"] as const;
const PRESETS = ["Emergency", "Medium-term", "Long-term growth"] as const; // names only: nothing is pre-filled with numbers
const INT = /^\d+$/;

/** Strip the separators people type in ₹ amounts ("4,00,000", "₹ 5000"); keep anything else so it can be flagged. */
const money = (text: string) => text.replace(/[,\s₹]/g, "");

interface GoalForm {
  key: number;
  goal_id: string | null;
  name: string;
  amount: string;
  date: string;
  loss: string;
  recovery: string;
}

interface Form {
  taxChoice: "new" | "old" | "conservative" | null;
  slab: string;
  expenses: string;
  monthsChoice: "3" | "6" | "other" | null;
  monthsOther: string;
  goals: GoalForm[];
  ltcg: string;
  savings: string;
  sweep: string;
}

function toForm(a: SetupAnswers): Form {
  const months = a.emergency.months;
  return {
    taxChoice: a.tax.use_conservative ? "conservative" : a.tax.regime,
    slab: fractionToPct(a.tax.slab_rate),
    expenses: a.emergency.essential_monthly_expenses ?? "",
    monthsChoice: months === null ? null : months === 3 ? "3" : months === 6 ? "6" : "other",
    monthsOther: months === null || months === 3 || months === 6 ? "" : String(months),
    goals: [...a.goals]
      .sort((x, y) => x.priority - y.priority)
      .map((g, i) => ({
        key: i,
        goal_id: g.goal_id,
        name: g.name,
        amount: g.target_amount ?? "",
        date: g.target_date ?? "",
        loss: g.loss_budget_inr ?? "",
        recovery: g.recovery_months === null ? "" : String(g.recovery_months),
      })),
    ltcg: a.extras.ltcg_used_inr ?? "",
    savings: a.extras.savings_balance ?? "",
    sweep: a.extras.sweep_fd_balance ?? "",
  };
}

const optMoney = (t: string) => (t.trim() === "" ? null : money(t));
const optInt = (t: string) => (t.trim() === "" ? null : Number.parseInt(t, 10));

/** The PUT body. Goals merge on the server (GOAL-1): only the fields setup edits are sent, so a saved goal's objective
 * and safe-horizon years are kept. A profile answer sent as null KEEPS its stored value (GOAL-2), so each stored answer
 * the user emptied is named in `clear` instead; `stored` is the server's last answers. */
function toAnswers(f: Form, stored: SetupAnswers): SetupAnswersIn {
  const conservative = f.taxChoice === "conservative";
  const slab = conservative ? null : pctToFraction(f.slab);
  const emergency = {
    essential_monthly_expenses: optMoney(f.expenses),
    months: f.monthsChoice === null ? null : f.monthsChoice === "other" ? optInt(f.monthsOther) : Number(f.monthsChoice),
  };
  const extras = { ltcg_used_inr: optMoney(f.ltcg), savings_balance: optMoney(f.savings), sweep_fd_balance: optMoney(f.sweep) };
  return {
    tax: {
      use_conservative: conservative,
      regime: f.taxChoice === "new" || f.taxChoice === "old" ? f.taxChoice : null,
      slab_rate: slab === "invalid" ? null : slab,
    },
    emergency,
    goals: f.goals.map<SetupGoalIn>((g, i) => ({
      goal_id: g.goal_id,
      name: g.name.trim(),
      priority: i + 1,
      target_amount: optMoney(g.amount),
      target_date: g.date || null,
      loss_budget_inr: optMoney(g.loss),
      recovery_months: optInt(g.recovery),
    })),
    extras,
    clear: setupClearList(stored, { emergency, extras }),
  };
}

/** Answers the user emptied (sent as null) that the server still holds after the save: the tax answers and the LTCG
 * figure have no `clear` entry, so a null keeps them; a clearable answer would show here only if the server kept it
 * anyway. Named after the save instead of being reported as saved. */
function notCleared(sent: SetupAnswersIn, got: SetupAnswers): string[] {
  const pairs: [string, unknown, unknown][] = [
    ["Income-tax regime", sent.tax.regime, got.tax.regime],
    ["Marginal income-tax slab", sent.tax.slab_rate, got.tax.slab_rate],
    ["Essential monthly expenses", sent.emergency.essential_monthly_expenses, got.emergency.essential_monthly_expenses],
    ["Emergency fund months", sent.emergency.months, got.emergency.months],
    ["Equity long-term gains already realised elsewhere", sent.extras.ltcg_used_inr, got.extras.ltcg_used_inr],
    ["Savings account balance", sent.extras.savings_balance, got.extras.savings_balance],
    ["Sweep / auto FD balance", sent.extras.sweep_fd_balance, got.extras.sweep_fd_balance],
  ];
  return pairs.filter(([, a, b]) => a === null && b !== null && b !== undefined).map(([label]) => label);
}

function validate(f: Form): FieldError[] {
  const out: FieldError[] = [];
  const badMoney = (t: string) => t.trim() !== "" && !DECIMAL.test(money(t));
  const slab = pctToFraction(f.slab);
  if (f.taxChoice !== "conservative") {
    if (slab === "invalid") out.push({ field: "su-slab", step: 1, message: `Income-tax slab: ${PCT_HELP}` });
    else if (slab !== null && compareDecimals(slab, "0.5") > 0) out.push({ field: "su-slab", step: 1, message: "Income-tax slab: at most 50 %." });
  }
  if (badMoney(f.expenses)) out.push({ field: "su-expenses", step: 2, message: "Essential monthly expenses: digits only, for example 40000." });
  if (f.monthsChoice === "other" && f.monthsOther.trim() !== "" && (!INT.test(f.monthsOther.trim()) || Number(f.monthsOther) < 1 || Number(f.monthsOther) > 60))
    out.push({ field: "su-months-other", step: 2, message: "Emergency months: a whole number from 1 to 60." });
  f.goals.forEach((g) => {
    const label = g.name.trim() || "unnamed goal";
    if (!g.name.trim() || g.name.trim().length > 120)
      out.push({ field: `su-g${g.key}-name`, step: 3, message: "Goal name: 1 to 120 characters." });
    if (badMoney(g.amount)) out.push({ field: `su-g${g.key}-amount`, step: 3, message: `Goal amount for “${label}”: digits only.` });
    if (badMoney(g.loss)) out.push({ field: `su-g${g.key}-loss`, step: 4, message: `Loss limit for “${label}”: digits only.` });
    else if (g.loss.trim() && g.amount.trim() && DECIMAL.test(money(g.amount)) && compareDecimals(money(g.loss), money(g.amount)) > 0)
      out.push({ field: `su-g${g.key}-loss`, step: 4, message: `Loss limit for “${label}” cannot be more than the goal amount.` });
    if (g.recovery.trim() && !INT.test(g.recovery.trim()))
      out.push({ field: `su-g${g.key}-recovery`, step: 5, message: `Recovery time for “${label}”: whole months, for example 36.` });
  });
  if (badMoney(f.ltcg)) out.push({ field: "su-ltcg", step: 6, message: "Gains already realised elsewhere: digits only." });
  if (badMoney(f.savings)) out.push({ field: "su-savings", step: 6, message: "Savings balance: digits only." });
  if (badMoney(f.sweep)) out.push({ field: "su-sweep", step: 6, message: "Sweep / auto FD balance: digits only." });
  return out;
}


/** The worst-observed-fall table. History, not a forecast; every value comes from the API (U-08: local config and the
 * AMFI recompute), with its basis, recovery and status. Shown before any loss-limit input. */
function CrashHistory({ history, id }: { history: StressHistory; id: string }) {
  return (
    <section aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Worst falls in the available history</h2>
      <div className="table-wrap">
        <table className="table table--compact" aria-labelledby={`${id}-title`}>
          <thead>
            <tr>
              <th scope="col">Kind of holding</th>
              <th scope="col" className="num">Worst fall</th>
              <th scope="col">Episode</th>
              <th scope="col">Time to recover</th>
              <th scope="col">Basis</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {history.rows.map((r) => (
              <tr key={r.risk_class}>
                <th scope="row">{r.label}</th>
                <td className="num">{r.outcome === "PASS" && r.stress ? fallLabel(r.stress) : "—"}</td>
                <td>{r.episode ?? "—"}{r.back_calculated ? " (back-calculated index history)" : ""}</td>
                <td>{recoveryText(r)}</td>
                <td className="small">{stressBasis(r)}</td>
                <td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">{history.caveat}</p>
    </section>
  );
}

function CasStep({ imported, onApplied }: { imported: boolean; onApplied: () => void }) {
  const list = useApi<{ items: PortfolioListItem[] }>("/api/portfolios");
  const [created, setCreated] = useState<PortfolioCreated | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const actual = created ?? list.data?.items.find((p) => p.nature === "actual") ?? null;

  async function create() {
    setPending(true);
    setErr(null);
    try {
      setCreated(await api<PortfolioCreated>("/api/portfolios", { method: "POST", body: { name: "My holdings", nature: "actual" } }));
    } catch (e) {
      setErr(`Not created (${e instanceof ApiError ? e.code : "REQUEST_FAILED"}).`);
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <p>
        Upload your consolidated account statement (CAS) once: holdings, purchase lots, folios, Regular/Direct plans and any
        exit loads charged are read from it. {imported ? <strong>A CAS has already been imported; a newer one updates it.</strong> : null}
      </p>
      <p className="hint">You can skip this step: nothing personal is computed until a CAS is imported, and Today then shows one “import CAS” item.</p>
      {list.loading ? (
        <Loading label="Loading your portfolios" />
      ) : list.error ? (
        <ErrorState error={list.error} retry={list.reload} />
      ) : actual ? (
        <Suspense fallback={<Loading label="Loading the CAS import" />}>
          <CasImport portfolioId={actual.portfolio_id} natureTag={<span className="badge">ACTUAL · {actual.name}</span>} onApplied={onApplied} />
        </Suspense>
      ) : (
        <div>
          <p>A CAS is imported into an actual portfolio (your real holdings). There is none yet.</p>
          <button type="button" className="btn" onClick={create} disabled={pending}>
            Create an actual portfolio named “My holdings”
          </button>
          {err ? <p role="alert">{err}</p> : null}
        </div>
      )}
    </div>
  );
}

function inrOrNotGiven(v: string) {
  return v.trim() && DECIMAL.test(money(v)) ? inr(money(v), { paise: false }) : "not given";
}

function Setup() {
  const state = useApi<SetupState>("/api/goals/setup");
  const [f, setF] = useState<Form>(() => toForm(EMPTY_ANSWERS));
  // The server's last answers (on load, then after each save): the baseline for the `clear` list.
  const [stored, setStored] = useState<SetupAnswers>(EMPTY_ANSWERS);
  const [loaded, setLoaded] = useState(false);
  const [step, setStep] = useState(0);
  const [casDone, setCasDone] = useState(false);
  const [summaryKey, setSummaryKey] = useState(0);
  const [focusField, setFocusField] = useState<string | null>(null);
  const [result, setResult] = useState<SetupState | null>(null);
  const [kept, setKept] = useState<string[]>([]);
  const nextKey = useRef(1000);
  const summaryRef = useRef<HTMLDivElement>(null);
  const stepTitle = useRef<HTMLHeadingElement>(null);
  const shownStep = useRef(step);
  const save = useMutation<SetupAnswersIn, SetupState>("PUT", "/api/goals/setup");

  useEffect(() => {
    if (state.data && !loaded) {
      setF(toForm(state.data.answers));
      setStored(state.data.answers);
      setLoaded(true);
    }
  }, [state.data, loaded]);
  useEffect(() => {
    if (summaryKey > 0) summaryRef.current?.focus();
  }, [summaryKey]);
  useEffect(() => {
    if (focusField === null) return;
    document.getElementById(focusField)?.focus();
    setFocusField(null);
  }, [focusField, step]);
  // On every step change, focus the new step's heading: it announces the step and keeps focus on the page when the
  // control that was pressed disappears or is disabled (Next on the last answer step, Back onto step 1; WCAG 2.4.3).
  // An error-summary link that also names a field wins (the effect above runs first).
  useEffect(() => {
    if (shownStep.current === step) return;
    shownStep.current = step;
    if (focusField === null) stepTitle.current?.focus();
  }, [step, focusField]);

  if (state.loading) return <Loading label="Loading your setup" />;
  if (state.error || !state.data) return <ErrorState error={state.error} retry={state.reload} />;
  const history = state.data.stress_history;

  const errors = validate(f);
  const errorFor = (field: string) => errors.find((x) => x.field === field);
  const showSummary = summaryKey > 0 && errors.length > 0;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const setGoal = (key: number, patch: Partial<GoalForm>) =>
    setF((x) => ({ ...x, goals: x.goals.map((g) => (g.key === key ? { ...g, ...patch } : g)) }));
  const addGoal = (name: string) => {
    nextKey.current += 1;
    const key = nextKey.current;
    setF((x) => ({ ...x, goals: [...x.goals, { key, goal_id: null, name, amount: "", date: "", loss: "", recovery: "" }] }));
  };
  const removeGoal = (key: number) => {
    // The Remove button goes with its goal: focus the next goal (else the previous one, else "Add another goal").
    const i = f.goals.findIndex((g) => g.key === key);
    const neighbour = f.goals[i + 1] ?? f.goals[i - 1];
    setF((x) => ({ ...x, goals: x.goals.filter((g) => g.key !== key) }));
    setFocusField(neighbour ? `su-g${neighbour.key}-name` : "su-add-goal");
  };
  const goalLabel = (g: GoalForm) => g.name.trim() || "unnamed goal";

  const err = (field: string) => {
    const e = errorFor(field);
    return e ? (
      <div id={`${field}-error`} className="hint field-error">
        {e.message}
      </div>
    ) : null;
  };
  const a11y = (field: string, hint?: string) => ({
    id: field,
    "aria-invalid": Boolean(errorFor(field)),
    "aria-describedby": [hint, errorFor(field) ? `${field}-error` : null].filter(Boolean).join(" ") || undefined,
  });
  const moneyField = (field: string, label: ReactNode, value: string, onChange: (v: string) => void, hint?: string) => (
    <div className="field" key={field}>
      <label htmlFor={field}>{label}</label>
      <span className="money">
        <input inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} {...a11y(field, hint ? `${field}-hint` : undefined)} />
      </span>
      {hint ? (
        <div id={`${field}-hint`} className="hint">
          {hint}
        </div>
      ) : null}
      {err(field)}
    </div>
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (errors.length) {
      setSummaryKey((k) => k + 1);
      return;
    }
    setSummaryKey(0);
    const sent = toAnswers(f, stored);
    const out = await save.run(sent);
    if (out) {
      setResult(out);
      setKept(notCleared(sent, out.answers));
      // Rebuild the form from what the server stored: new goals now carry their server-assigned goal_id, so a second
      // Save updates them instead of creating them again, and a kept answer shows its stored value.
      setF(toForm(out.answers));
      setStored(out.answers);
    }
  }

  const noGoals = (
    <p>
      Add a goal first (<button type="button" className="btn btn--ghost" onClick={() => setStep(3)}>step 4, Goals</button>).
    </p>
  );

  return (
    <>
      <p className="muted">
        One upload and about six answers. Every answer is optional: what is missing is named, and the parts that need it
        abstain instead of guessing.
      </p>
      <ol className="steps" aria-label="Setup progress">
        {SETUP_STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined}>
            <button type="button" className="btn btn--ghost" onClick={() => setStep(i)}>
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>
      <div className="card">
        {showSummary ? (
          <div key={summaryKey} className="callout callout--stale" role="alert" tabIndex={-1} ref={summaryRef} aria-labelledby="su-errors-title">
            <p id="su-errors-title">
              <strong>Not saved yet. Please correct {errors.length === 1 ? "this value" : "these values"}:</strong>
            </p>
            <ul>
              {errors.map((x) => (
                <li key={x.field}>
                  <a
                    href={`#${x.field}`}
                    onClick={(ev) => {
                      ev.preventDefault();
                      setStep(x.step);
                      setFocusField(x.field);
                    }}
                  >
                    {x.message} (step {x.step + 1}, {SETUP_STEPS[x.step]})
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <h2 id="su-step-title" ref={stepTitle} tabIndex={-1}>
          Step {step + 1} of {SETUP_STEPS.length}: {SETUP_STEPS[step]}
        </h2>

        {/* Outside the setup <form>: the CAS import has its own form, and a nested form would also submit setup. */}
        {step === 0 && <CasStep imported={state.data.cas_imported || casDone} onApplied={() => setCasDone(true)} />}

        <form id="su-form" onSubmit={submit} noValidate>
        {step === 1 && (
          <fieldset className="field">
            <legend>Your income-tax regime and slab</legend>
            <label className="choice">
              <input type="radio" name="su-tax" checked={f.taxChoice === "new"} onChange={() => set("taxChoice", "new")} /> New regime
            </label>
            <label className="choice">
              <input type="radio" name="su-tax" checked={f.taxChoice === "old"} onChange={() => set("taxChoice", "old")} /> Old regime
            </label>
            <label className="choice">
              <input type="radio" name="su-tax" checked={f.taxChoice === "conservative"} onChange={() => set("taxChoice", "conservative")} /> Use
              the conservative assumption (highest slab, this year&apos;s LTCG exemption already used)
            </label>
            {f.taxChoice === "conservative" ? (
              <p className="hint">Every tax figure is then labelled as using this assumption, and may understate what a tax action is worth to you.</p>
            ) : (
              <div className="field">
                <label htmlFor="su-slab">Marginal income-tax slab (%)</label>
                <span className="pct">
                  <input inputMode="decimal" value={f.slab} onChange={(e) => set("slab", e.target.value)} {...a11y("su-slab", "su-slab-hint")} />
                </span>
                <div id="su-slab-hint" className="hint">A number only, for example 20. Leave empty if you are not sure.</div>
                {err("su-slab")}
              </div>
            )}
          </fieldset>
        )}

        {step === 2 && (
          <>
            {moneyField("su-expenses", "Essential monthly expenses (₹)", f.expenses, (v) => set("expenses", v), "Rent, food, EMIs, insurance: what you must pay each month.")}
            <fieldset className="field">
              <legend>How many months of essential expenses to keep as an emergency fund?</legend>
              {(["3", "6"] as const).map((m) => (
                <label key={m} className="choice">
                  <input type="radio" name="su-months" checked={f.monthsChoice === m} onChange={() => set("monthsChoice", m)} /> {m} months
                </label>
              ))}
              <label className="choice">
                <input type="radio" name="su-months" checked={f.monthsChoice === "other"} onChange={() => set("monthsChoice", "other")} /> Another number
              </label>
              {f.monthsChoice === "other" ? (
                <div className="field">
                  <label htmlFor="su-months-other">Months (1–60)</label>
                  <input inputMode="numeric" value={f.monthsOther} onChange={(e) => set("monthsOther", e.target.value)} {...a11y("su-months-other")} />
                  {err("su-months-other")}
                </div>
              ) : null}
              <p className="hint">
                3–6 months is US-regulator (Investor.gov) guidance; a SEBI attribution is NOT VERIFIED. More months if your income varies.
              </p>
            </fieldset>
          </>
        )}

        {step === 3 && (
          <div>
            <p>Name each goal, its amount and its date. Nothing is filled in for you.</p>
            {f.goals.map((g) => (
              <fieldset key={g.key} className="field">
                <legend>{goalLabel(g)}</legend>
                <div className="field">
                  <label htmlFor={`su-g${g.key}-name`}>Goal name</label>
                  <input maxLength={120} value={g.name} onChange={(e) => setGoal(g.key, { name: e.target.value })} {...a11y(`su-g${g.key}-name`)} />
                  {err(`su-g${g.key}-name`)}
                </div>
                {moneyField(`su-g${g.key}-amount`, `Goal amount (₹) — ${goalLabel(g)}`, g.amount, (v) => setGoal(g.key, { amount: v }))}
                <div className="field">
                  <label htmlFor={`su-g${g.key}-date`}>Goal date — {goalLabel(g)}</label>
                  <input id={`su-g${g.key}-date`} type="date" value={g.date} onChange={(e) => setGoal(g.key, { date: e.target.value })} />
                </div>
                {g.goal_id === null ? (
                  <button type="button" className="btn btn--ghost" onClick={() => removeGoal(g.key)}>
                    Remove “{goalLabel(g)}”
                  </button>
                ) : (
                  // Saving setup only creates or updates goals, so removing a saved goal here would do nothing. Deleting
                  // is done, with its confirmation, on the Goals page.
                  <p className="hint">
                    “{goalLabel(g)}” is saved. <Link to="/goals">Delete it on the Goals page</Link> (its holdings then become
                    Unassigned).
                  </p>
                )}
              </fieldset>
            ))}
            <div className="row">
              {PRESETS.map((name) => (
                <button key={name} type="button" className="btn" onClick={() => addGoal(name)}>
                  Add “{name}”
                </button>
              ))}
              <button id="su-add-goal" type="button" className="btn" onClick={() => addGoal("")}>
                Add another goal
              </button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div role="group" aria-label="Loss limit">
            <CrashHistory history={history} id="su-history" />
            <h2>Your loss limit per goal</h2>
            <p>
              Look at the falls above first. Then, for each goal, enter the largest fall in rupees you would sit through
              without selling. This one number sets how much of the goal may be in equity; without it that goal gets no
              equity suggestion.
            </p>
            {f.goals.length === 0
              ? noGoals
              : f.goals.map((g) => {
                  const amt = money(g.amount);
                  const hasAmt = g.amount.trim() !== "" && DECIMAL.test(amt);
                  const shown = history.rows.filter((r) => r.outcome === "PASS" && r.stress);
                  return (
                    <fieldset key={g.key} className="field">
                      <legend>{goalLabel(g)}</legend>
                      {hasAmt && shown.length ? (
                        <ul className="small" aria-label={`Worst falls applied to ${goalLabel(g)}`}>
                          {shown.map((r) => (
                            <li key={r.risk_class}>
                              On {inr(amt, { paise: false })} entirely in {r.label}, its worst fall in the available history ({fallLabel(r.stress!)}) would
                              have been about {inr(rupeesTimesFraction(amt, r.stress!), { paise: false })} (goal amount × worst fall).
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {moneyField(
                        `su-g${g.key}-loss`,
                        `Largest fall in ₹ you would sit through without selling — ${goalLabel(g)}`,
                        g.loss,
                        (v) => setGoal(g.key, { loss: v }),
                      )}
                    </fieldset>
                  );
                })}
          </div>
        )}

        {step === 5 && (
          <div>
            <p>How long could you wait for a fall to recover before you would need the money or give up?</p>
            {f.goals.length === 0
              ? noGoals
              : f.goals.map((g) => {
                  const months = INT.test(g.recovery.trim()) ? Number(g.recovery) : null;
                  const longer =
                    months === null
                      ? []
                      : history.rows.filter((r) => {
                          const m = yearsToMonths(r.recovery_years);
                          return r.outcome === "PASS" && m !== null && m > months;
                        });
                  return (
                    <div key={g.key} className="field">
                      <label htmlFor={`su-g${g.key}-recovery`}>Longest you would wait for a recovery (months) — {goalLabel(g)}</label>
                      <input inputMode="numeric" value={g.recovery} onChange={(e) => setGoal(g.key, { recovery: e.target.value })} {...a11y(`su-g${g.key}-recovery`)} />
                      {err(`su-g${g.key}-recovery`)}
                      {longer.map((r) => (
                        <p key={r.risk_class} className="callout callout--warn">
                          In the worst episode of {r.label}, recovery took {r.recovery_years} years ({yearsToMonths(r.recovery_years)} months); your limit is {months} months.
                          This is history, not a prediction.
                        </p>
                      ))}
                    </div>
                  );
                })}
          </div>
        )}

        {step === 6 && (
          <>
            <p>Optional. Each one sharpens a specific figure; leaving it empty keeps a labelled, conservative assumption.</p>
            {moneyField("su-ltcg", "Equity long-term gains already realised elsewhere this financial year (₹)", f.ltcg, (v) => set("ltcg", v), "Empty = the exemption is assumed already used.")}
            {moneyField("su-savings", "Savings account balance (₹)", f.savings, (v) => set("savings", v), "Counts towards the emergency fund.")}
            {moneyField("su-sweep", "Sweep / auto FD balance (₹)", f.sweep, (v) => set("sweep", v), "Counts towards the emergency fund.")}
          </>
        )}

        {step === 7 && (
          <div>
            <dl className="kv">
              <dt>CAS</dt>
              <dd>{state.data.cas_imported || casDone ? "imported" : "not imported yet"}</dd>
              <dt>Tax</dt>
              <dd>
                {f.taxChoice === "conservative"
                  ? "conservative assumption"
                  : f.taxChoice
                    ? `${f.taxChoice} regime${f.slab.trim() ? `, slab ${f.slab} %` : ", slab not given"}`
                    : "not given"}
              </dd>
              <dt>Emergency fund</dt>
              <dd>
                {inrOrNotGiven(f.expenses)} a month ×{" "}
                {f.monthsChoice === null ? "months not given" : `${f.monthsChoice === "other" ? f.monthsOther || "?" : f.monthsChoice} months`}
              </dd>
              {f.goals.map((g) => (
                <div className="kv__row" key={g.key}>
                  <dt>{goalLabel(g)}</dt>
                  <dd>
                    {inrOrNotGiven(g.amount)} by {g.date ? dateLabel(g.date) : "date not given"}; loss limit {inrOrNotGiven(g.loss)}; recovery{" "}
                    {g.recovery.trim() ? `${g.recovery} months` : "not given"}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        </form>

        {save.error ? (
          <p className="callout callout--stale" role="alert">
            Not saved: {save.error instanceof ApiError && save.error.status === 422 ? serverReasons(save.error) : "the request failed."}
          </p>
        ) : null}
        {result ? (
          <div className="callout" role="status">
            <p>
              Setup saved. {result.missing.length ? `Still missing: ${result.missing.join("; ")}.` : "Nothing is missing."}
            </p>
            {kept.length ? (
              <p>
                Not cleared: {kept.join("; ")}. These saved answers cannot be cleared here, so each keeps its stored
                value (shown again in its step).
              </p>
            ) : null}
            <p>
              <Link to="/goals">Open your goals</Link>
            </p>
          </div>
        ) : null}
        <div className="row">
          <button type="button" className="btn" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            Back
          </button>
          {step < SETUP_STEPS.length - 1 ? (
            <button type="button" className="btn" onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          ) : null}
          <button type="submit" form="su-form" className="btn btn--primary" disabled={save.pending}>
            {save.pending ? "Saving…" : "Save setup"}
          </button>
        </div>
      </div>
    </>
  );
}

export default function Onboarding() {
  const [params] = useSearchParams();
  const tab = params.get("tab") === "objectives" ? "objectives" : "setup";
  useEffect(() => {
    // Outside the Shell, so it sets its own title (WCAG 2.4.2).
    document.title = `${tab === "setup" ? "Setup" : "Your objectives"} · Investment Intelligence Pro`;
  }, [tab]);
  return (
    <main className="onboarding">
      <header className="row">
        <h1>{tab === "setup" ? "Setup" : "Your objectives"}</h1>
        <span className="topbar__spacer" />
        <Link to="/">Back to the app</Link>
      </header>
      <nav aria-label="Setup sections" className="row">
        <Link to="/onboarding" aria-current={tab === "setup" ? "page" : undefined}>
          Setup: CAS and answers
        </Link>
        <Link to="/onboarding?tab=objectives" aria-current={tab === "objectives" ? "page" : undefined}>
          Discovery objectives
        </Link>
      </nav>
      {tab === "setup" ? <Setup /> : <ObjectivesWizard />}
    </main>
  );
}
