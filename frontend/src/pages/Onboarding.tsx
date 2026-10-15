import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../lib/api";
import { OBJECTIVES, useProfile } from "../lib/profile";
import type { ObjectiveCode, Profile, ProfileStatus } from "../lib/types";
import { useMutation } from "../lib/useApi";
import { fractionToPercent as fractionToPct, inr, percentToFraction as pctToFraction } from "../lib/format";

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

export default function Onboarding() {
  const { status, reload } = useProfile();
  const navigate = useNavigate();
  const [p, setP] = useState<Profile>(EMPTY);
  const [step, setStep] = useState(0);
  const [lossPct, setLossPct] = useState("");
  const [slabPct, setSlabPct] = useState("");
  const [aspPct, setAspPct] = useState("");
  const [result, setResult] = useState<ProfileStatus | null>(null);
  const [summaryKey, setSummaryKey] = useState(0);
  const [focusField, setFocusField] = useState<string | null>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const save = useMutation<Profile, ProfileStatus>("PUT", "/api/profile");

  useEffect(() => {
    document.title = "Your objectives · Investment Intelligence Pro"; // outside the Shell, so it sets its own (2.4.2)
  }, []);
  useEffect(() => {
    if (status) {
      setP(status.profile);
      setLossPct(fractionToPct(status.profile.max_loss_fraction));
      setSlabPct(fractionToPct(status.profile.slab_rate));
      setAspPct(fractionToPct(status.profile.return_aspiration));
    }
  }, [status]);

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setP((x) => ({ ...x, [k]: v }));
  const amountValid = p.amount === null || DECIMAL.test(p.amount);
  const lossFr = pctToFraction(lossPct);
  const slabFr = pctToFraction(slabPct);
  const aspFr = pctToFraction(aspPct);
  // Save stays enabled; problems are listed on submit (WCAG 3.3.1/3.3.3). The loss limit only counts while its input is
  // shown ("Yes, up to a limit"): a leftover invalid value behind "No" used to block Save with nothing visible.
  const errors: FieldError[] = [
    ...(!amountValid ? [{ field: "amount", step: 0, message: "Investable amount: digits only, for example 500000." }] : []),
    ...(p.loss_acceptable === true && lossFr === "invalid"
      ? [{ field: "loss", step: 3, message: `Largest loss you would accept: ${PCT_HELP}` }]
      : []),
    ...(slabFr === "invalid" ? [{ field: "slab", step: 4, message: `Income-tax slab: ${PCT_HELP}` }] : []),
    ...(aspFr === "invalid" ? [{ field: "asp", step: 4, message: `Return you are hoping for: ${PCT_HELP}` }] : []),
  ];
  const errorFor = (field: string) => errors.find((x) => x.field === field);
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
      return_aspiration: aspFr === "invalid" ? null : aspFr,
    };
    const out = await save.run(body);
    if (out) {
      setResult(out);
      reload();
    }
  }

  const growth = p.objective === "D_growth" || p.objective === "E_aggressive_growth";

  return (
    <main className="onboarding">
      <header className="row">
        <h1>Your objectives</h1>
        <span className="topbar__spacer" />
        <Link to="/">Back to the app</Link>
      </header>
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
                <input type="radio" name="loss" checked={p.loss_acceptable === true} onChange={() => set("loss_acceptable", true)} /> Yes, up
                to a limit
              </label>
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
              <div id="slab-hint" className="hint">If empty, after-tax figures use a labelled illustrative 30 % slab, not yours.</div>
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
            <label className="choice">
              <input type="checkbox" checked={p.tax_regime === "new"} onChange={(e) => set("tax_regime", e.target.checked ? "new" : null)} /> I
              file under the new tax regime
            </label>
            <div className="field">
              <label htmlFor="asp">Return you are hoping for (% a year) — optional</label>
              <span className="pct">
              <input
                id="asp"
                inputMode="decimal"
                value={aspPct}
                onChange={(e) => setAspPct(e.target.value)}
                aria-invalid={Boolean(errorFor("asp"))}
                aria-describedby={describedBy("asp", "asp-hint")}
              />
              </span>
              <div id="asp-hint" className="hint">
                Recorded as an aspiration only. It is never used to rank options; see Return-target feasibility for how often
                it happened historically.
              </div>
              {fieldError("asp")}
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
              <dd>{slabPct ? `${slabPct} %` : "not given"}</dd>
              <dt>Return you are hoping for</dt>
              <dd>{aspPct ? `${aspPct} % a year` : "not given"}</dd>
            </dl>
          </div>
        )}
        {save.error ? (
          <p className="callout callout--stale" role="alert">
            Not saved:{" "}
            {save.error instanceof ApiError && save.error.status === 422
              ? "some values are not acceptable (check the loss limit and objective combination)."
              : "the request failed."}
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
    </main>
  );
}

