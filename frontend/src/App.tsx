import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ApiError, login, readLoginFragment, restoreSession, UNAUTHORIZED_EVENT } from "./lib/api";
import { dateLabel, inr, utcStamp } from "./lib/format";
import { OBJECTIVES, ProfileProvider, useProfile } from "./lib/profile";
import { REQUIRED } from "./components/Disclosures";
import { Loading } from "./components/States";
import type { DataHealthResponse } from "./lib/types";
import { useApi } from "./lib/useApi";

const Onboarding = lazy(() => import("./pages/Onboarding"));
const Discovery = lazy(() => import("./pages/Discovery"));
const Overview = lazy(() => import("./pages/Overview"));
const MfExplorer = lazy(() => import("./pages/MfExplorer"));
const FixedIncome = lazy(() => import("./pages/FixedIncome"));
const InstrumentDetail = lazy(() => import("./pages/InstrumentDetail"));
const Compare = lazy(() => import("./pages/Compare"));
const Scenarios = lazy(() => import("./pages/Scenarios"));
const Simulator = lazy(() => import("./pages/Simulator"));
const Risk = lazy(() => import("./pages/Risk"));
const Watchlist = lazy(() => import("./pages/Watchlist"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Evidence = lazy(() => import("./pages/Evidence"));
const Methodology = lazy(() => import("./pages/Methodology"));
const Settings = lazy(() => import("./pages/Settings"));
const DataHealth = lazy(() => import("./pages/DataHealth"));

type AuthState = "checking" | "ok" | "locked";

function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>("checking");
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    const token = readLoginFragment();
    const go = token ? login(token).then(() => true) : restoreSession();
    go.then((ok) => setState(ok ? "ok" : "locked")).catch((e: unknown) => {
      setError(e instanceof ApiError ? e.code : "LOGIN_FAILED");
      setState("locked");
    });
  }, [epoch]);
  useEffect(() => {
    // A login link opened in a tab already showing the app is a same-document hash change, not a page load.
    const onHash = () => {
      if (window.location.hash.includes("login=")) {
        setState("checking");
        setEpoch((n) => n + 1);
      }
    };
    const onUnauthorized = () => setState("locked");
    window.addEventListener("hashchange", onHash);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);
  if (state === "checking") return <Loading label="Checking your local session" />;
  if (state === "locked")
    return (
      <main className="locked">
        <h1>Investment Intelligence Pro</h1>
        <p>This is a private, local app. Open it with the one-time link printed by <code>make open</code>.</p>
        {error ? <p className="small subtle">Sign-in was refused ({error}).</p> : null}
      </main>
    );
  // Remount the app after every (re)login so no data from a previous session survives.
  return <div key={epoch}>{children}</div>;
}

const NAV: { group: string; items: [string, string][] }[] = [
  {
    group: "Decide",
    items: [
      ["/", "Overview"],
      ["/discover", "Discovery"],
      ["/compare", "Compare"],
      ["/scenarios", "Scenarios"],
      ["/simulate", "Simulator"],
      ["/risk", "Risk"],
    ],
  },
  {
    group: "Research",
    items: [
      ["/mf", "Mutual funds"],
      ["/fi", "Fixed income"],
      ["/watchlist", "Watchlist"],
      ["/alerts", "Alerts"],
    ],
  },
  {
    group: "Trust",
    items: [
      ["/evidence", "Evidence"],
      ["/methodology", "Methodology"],
      ["/data-health", "Data health"],
    ],
  },
];

function ContextBar() {
  const { status } = useProfile();
  if (!status)
    return (
      <div className="contextbar" role="status">
        Loading your objectives…
      </div>
    );
  const p = status.profile;
  const exploring = status.mode === "EXPLORATION";
  const obj = p.objective ? OBJECTIVES[p.objective] : null;
  return (
    <div className={`contextbar${exploring ? " contextbar--exploration" : ""}`} role="region" aria-label="Current objectives">
      <strong>{exploring ? "EXPLORATION" : "PERSONALISED"}</strong>
      {exploring ? (
        <span className="contextbar__item">Illustrative ₹1,00,000 · 182 days · not ranked for you — {status.missing.length} detail(s) missing</span>
      ) : (
        <>
          <span className="contextbar__item">
            <b>{p.amount ? inr(p.amount, { paise: false }) : "—"}</b>
          </span>
          <span className="contextbar__item">
            withdraw <b>{p.withdrawal_date ? dateLabel(p.withdrawal_date) : "—"}</b> ({status.horizon_days} days)
          </span>
          <span className="contextbar__item">
            Objective {obj?.code} · {obj?.title}
          </span>
          <span className="contextbar__item">Loss: {p.loss_acceptable ? `up to ${p.max_loss_fraction ?? "?"}` : "not acceptable"}</span>
        </>
      )}
      <Link to="/onboarding" className="btn btn--ghost">
        {exploring ? "Add details" : "Edit"}
      </Link>
    </div>
  );
}

/** Data-as-of line in the top bar: when the official NAV file was last fetched, straight from Data health. */
function DataAsOf() {
  const { data, error } = useApi<DataHealthResponse>("/api/data-health");
  const run = data?.sources.find((s) => s.source_id === "amfi.navall")?.last_run ?? null;
  let text: string;
  if (error) text = "Data status unavailable";
  else if (!data) text = "Checking data…";
  else if (!run?.finished_at) text = "AMFI NAVs not fetched yet";
  else text = `AMFI NAVs fetched ${utcStamp(run.finished_at)}${run.status === "ok" ? "" : ` (${run.status})`}`;
  return (
    <Link to="/data-health" className="topbar__data" title="Open Data health">
      <span className="badge badge--eod">
        <span aria-hidden="true">◑</span> DATA
      </span>
      <span className="topbar__data-text">{text}</span>
    </Link>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setMenuOpen(false), [pathname]); // a chosen page closes the small-screen menu
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <button
          type="button"
          className="btn menu-btn"
          aria-expanded={menuOpen}
          aria-controls="main-nav"
          onClick={() => setMenuOpen((o) => !o)}
        >
          <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span> Menu
        </button>
        <Link to="/" className="brand">
          IIP <span>Investment Intelligence</span>
        </Link>
        <span className="topbar__spacer" />
        <DataAsOf />
        <NavLink to="/settings" className="topbar__link">
          Settings
        </NavLink>
      </header>
      <ContextBar />
      <nav className="nav" id="main-nav" aria-label="Main" data-open={menuOpen ? "true" : "false"}>
        {NAV.map((g) => (
          <div key={g.group} role="group" aria-labelledby={`nav-${g.group}`}>
            <p className="nav__group-title" id={`nav-${g.group}`}>
              {g.group}
            </p>
            {g.items.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}>
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <main id="main" tabIndex={-1}>
        <Suspense fallback={<Loading />}>{children}</Suspense>
      </main>
      <footer className="footer">{REQUIRED.footer}</footer>
    </div>
  );
}

export function App() {
  return (
    <AuthGate>
      <ProfileProvider>
        <Routes>
          <Route
            path="/onboarding"
            element={
              <Suspense fallback={<Loading />}>
                <Onboarding />
              </Suspense>
            }
          />
          <Route
            path="*"
            element={
              <Shell>
                <Routes>
                  <Route path="/" element={<Overview />} />
                  <Route path="/discover" element={<Discovery />} />
                  <Route path="/mf" element={<MfExplorer />} />
                  <Route path="/fi" element={<FixedIncome />} />
                  <Route path="/i/:id" element={<InstrumentDetail />} />
                  <Route path="/compare" element={<Compare />} />
                  <Route path="/scenarios" element={<Scenarios />} />
                  <Route path="/simulate" element={<Simulator />} />
                  <Route path="/risk" element={<Risk />} />
                  <Route path="/watchlist" element={<Watchlist />} />
                  <Route path="/alerts" element={<Alerts />} />
                  <Route path="/evidence" element={<Evidence />} />
                  <Route path="/evidence/:obsId" element={<Evidence />} />
                  <Route path="/methodology" element={<Methodology />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="/data-health" element={<DataHealth />} />
                </Routes>
              </Shell>
            }
          />
        </Routes>
      </ProfileProvider>
    </AuthGate>
  );
}
