import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { ApiError, login, readLoginFragment, restoreSession, UNAUTHORIZED_EVENT } from "./lib/api";
import { dateLabel, inr } from "./lib/format";
import { OBJECTIVES, ProfileProvider, useProfile } from "./lib/profile";
import { REQUIRED } from "./components/Disclosures";
import { Loading } from "./components/States";

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
  if (!status) return <div className="contextbar">Loading your objectives…</div>;
  const p = status.profile;
  const exploring = status.mode === "EXPLORATION";
  const obj = p.objective ? OBJECTIVES[p.objective] : null;
  return (
    <div className={`contextbar${exploring ? " contextbar--exploration" : ""}`} role="region" aria-label="Current objectives">
      <strong>{exploring ? "EXPLORATION" : "PERSONALISED"}</strong>
      {exploring ? (
        <span>Illustrative ₹1,00,000 · 182 days · not ranked for you — {status.missing.length} detail(s) missing</span>
      ) : (
        <>
          <span>{p.amount ? inr(p.amount, { paise: false }) : "—"}</span>
          <span>withdraw {p.withdrawal_date ? dateLabel(p.withdrawal_date) : "—"} ({status.horizon_days} days)</span>
          <span>
            Objective {obj?.code} · {obj?.title}
          </span>
          <span>Loss: {p.loss_acceptable ? `up to ${p.max_loss_fraction ?? "?"}` : "not acceptable"}</span>
        </>
      )}
      <Link to="/onboarding" className="btn btn--ghost">
        {exploring ? "Add details" : "Edit"}
      </Link>
    </div>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          IIP <span>Investment Intelligence</span>
        </Link>
        <span className="topbar__spacer" />
        <NavLink to="/settings">Settings</NavLink>
      </header>
      <ContextBar />
      <nav className="nav" aria-label="Main">
        {NAV.map((g) => (
          <div key={g.group}>
            <h4>{g.group}</h4>
            {g.items.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}>
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <main id="main">
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
