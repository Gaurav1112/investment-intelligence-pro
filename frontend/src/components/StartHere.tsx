import { useState } from "react";
import { Link } from "react-router-dom";
import { utcStamp } from "../lib/format";
import { OBJECTIVES, useProfile } from "../lib/profile";
import type { DataHealthResponse, InstrumentList, SourceHealth } from "../lib/types";
import { useApi } from "../lib/useApi";

type StepState = "done" | "todo" | "attention" | "unknown" | "next";

interface Step {
  key: string;
  title: string;
  state: StepState;
  status: string;
  to: string;
  action: string;
}

const STATE_WORD: Record<StepState, string> = {
  done: "Done",
  todo: "To do",
  attention: "Needs attention",
  unknown: "Status unavailable",
  next: "Next",
};
const STATE_GLYPH: Record<StepState, string> = { done: "✓", todo: "", attention: "!", unknown: "?", next: "→" };

function lastRun(dh: DataHealthResponse | null, id: string): SourceHealth["last_run"] {
  return dh?.sources.find((s) => s.source_id === id)?.last_run ?? null;
}

function runStep(
  run: SourceHealth["last_run"],
  loaded: boolean,
  failed: boolean,
  words: { none: string; ok: (when: string, rows: number) => string },
): Pick<Step, "state" | "status"> {
  if (failed) return { state: "unknown", status: "Could not read Data health." };
  if (!loaded) return { state: "unknown", status: "Checking…" };
  if (!run?.finished_at) return { state: "todo", status: words.none };
  const when = utcStamp(run.finished_at);
  if (run.status === "failed") return { state: "attention", status: `Last attempt failed (${when}). See Data health for the error.` };
  const base = words.ok(when, run.rows_ok);
  if (run.status === "partial")
    return { state: "done", status: `${base} Some rows were rejected (${run.rows_rejected.toLocaleString("en-IN")}); details in Data health.` };
  return { state: "done", status: base };
}

/**
 * First-run journey: five steps with live status from existing read-only endpoints. Each step links to where it is done.
 * The checklist only reports state; it never changes anything itself.
 */
export function StartHere({ defaultOpen }: { defaultOpen: boolean }) {
  const [open] = useState(defaultOpen);
  const { status, error: profileError } = useProfile();
  const dh = useApi<DataHealthResponse>("/api/data-health");
  const tb = useApi<InstrumentList>("/api/instruments?kind=tbill");
  const fd = useApi<InstrumentList>("/api/instruments?kind=fd");

  // 1. objectives
  let s1: Pick<Step, "state" | "status">;
  if (profileError) s1 = { state: "unknown", status: "Could not read your profile." };
  else if (!status) s1 = { state: "unknown", status: "Checking…" };
  else if (status.mode === "PERSONALISED") {
    const obj = status.profile.objective ? OBJECTIVES[status.profile.objective] : null;
    const conflicts = status.conflicts.length;
    s1 = conflicts
      ? {
          state: "attention",
          status: `Set (objective ${obj?.code ?? "?"} · ${obj?.title ?? ""}), but ${conflicts} setting conflict${conflicts === 1 ? "" : "s"} to review.`,
        }
      : { state: "done", status: `Set: objective ${obj?.code ?? "?"} · ${obj?.title ?? ""}.` };
  } else s1 = { state: "todo", status: `Exploration mode: ${status.missing.length} detail(s) missing.` };

  // 2. latest NAVs, 3. history
  const dhLoaded = dh.data !== null;
  const dhFailed = Boolean(dh.error);
  const s2 = runStep(lastRun(dh.data, "amfi.navall"), dhLoaded, dhFailed, {
    none: "The official AMFI NAV file has not been fetched yet.",
    ok: (when) => `Last fetched ${when}.`,
  });
  const s3 = runStep(lastRun(dh.data, "amfi.navhistory"), dhLoaded, dhFailed, {
    none: "No NAV history backfilled yet. Discovery skips funds without history.",
    ok: (when, rows) => `Last backfill ${when} (${rows.toLocaleString("en-IN")} rows).`,
  });

  // 4. T-bills / FDs
  let s4: Pick<Step, "state" | "status">;
  if (tb.error || fd.error) s4 = { state: "unknown", status: "Could not read stored instruments." };
  else if (!tb.data || !fd.data) s4 = { state: "unknown", status: "Checking…" };
  else {
    const all = [...tb.data.items, ...fd.data.items];
    const real = all.filter((i) => !i.fixture);
    const fixtures = all.length - real.length;
    const tbills = tb.data.items.filter((i) => !i.fixture).length;
    const fds = fd.data.items.filter((i) => !i.fixture).length;
    const fixtureNote = fixtures ? ` ${fixtures} FIXTURE item(s) are not counted.` : "";
    s4 =
      real.length > 0
        ? { state: "done", status: `${tbills} T-bill(s) and ${fds} FD(s) entered.${fixtureNote}` }
        : { state: "todo", status: `None entered from official pages yet.${fixtureNote}` };
  }

  // 5. discovery — runs when the page opens; ready once objectives and NAVs are in place
  const ready = s1.state !== "todo" && s1.state !== "unknown" && s2.state === "done";
  const s5: Pick<Step, "state" | "status"> = ready
    ? { state: "next", status: "Ready. Discovery evaluates everything stored under your constraints when you open it." }
    : { state: "todo", status: "Works best after steps 1 and 2." };

  const steps: Step[] = [
    { key: "objectives", title: "Set your objectives", ...s1, to: "/onboarding", action: s1.state === "todo" ? "Set objectives" : "Review" },
    { key: "nav", title: "Fetch the latest AMFI NAVs", ...s2, to: "/mf", action: "Mutual funds" },
    { key: "history", title: "Backfill history for the funds you want evaluated", ...s3, to: "/mf", action: "Mutual funds" },
    { key: "fixed", title: "Add T-bills or FDs", ...s4, to: "/fi", action: "Fixed income" },
    { key: "discover", title: "Run Discovery", ...s5, to: "/discover", action: "Open Discovery" },
  ];
  const done = steps.slice(0, 4).filter((s) => s.state === "done").length;

  return (
    <details className="card start-here" open={open} aria-labelledby="start-title">
      <summary>
        <span className="progress-line">
          <strong id="start-title">Start here</strong>
          <span className="small muted">
            {done} of 4 setup steps done
          </span>
          <span className="progress-line__bar" aria-hidden="true">
            <span className={`w-${done}`} />
          </span>
        </span>
      </summary>
      <p className="small muted">Four setup steps, then Discovery shows results for your own money. Each step links to where it is done.</p>
      <ol className="checklist" aria-label="Setup steps">
        {steps.map((s, i) => (
          <li key={s.key} data-testid={`step-${s.key}`} data-state={s.state}>
            <span
              className={`checklist__mark${s.state === "done" ? " checklist__mark--done" : s.state === "attention" ? " checklist__mark--attention" : ""}`}
              aria-hidden="true"
            >
              {STATE_GLYPH[s.state] || i + 1}
            </span>
            <div>
              <div className="checklist__title">
                {i + 1}. {s.title}
              </div>
              <div className="checklist__status">
                <span className="chip">{STATE_WORD[s.state]}</span> {s.status}
              </div>
            </div>
            <Link className="btn checklist__go" to={s.to}>
              {s.action}
            </Link>
          </li>
        ))}
      </ol>
    </details>
  );
}
