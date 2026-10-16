import type { DataHealthResponse, SourceHealth } from "../lib/types";
import { STATUS_LABELS, type DataRightsRow, type LicenceClass, type SourceStatusLabel, type Unblock } from "../lib/types-settings";
import { useApi } from "../lib/useApi";

// C04: every data source, its licence, its status label and the decision that unblocks it.
//
// Two inputs, merged:
//  1. The live source registry from GET /api/data-health (backend/src/iip/data/registry.py). A status the server reports
//     wins. Until that route exposes `status`, the cited registry status below is used (a test keeps it equal to
//     registry.py); a source neither reports nor cites is labelled NOT VERIFIED — never VERIFIED by default.
//  2. Sources that are deliberately NOT in the registry (blocked or user-owned routes) from
//     docs/research/wave1/design-risk-first.md §2.1, with the user's decisions of 2026-10-16 (PLAN.md §8).
// Decision ids are PLAN.md §3 / docs/product/decisions-register.md.

type RegistryEntry = { name: string; licence: LicenceClass; status: SourceStatusLabel; status_ref: string; unblock: Unblock };

const AMFI_UNBLOCK: Unblock = {
  decisions: ["U-01"],
  text:
    "Usable now. Decided 2026-10-16 (U-01): the full core universe is tracked on your computer only; the hosted app keeps rows " +
    "for held and watched schemes only.",
};
const MANUAL: Unblock = { decisions: [], text: "Nothing to decide: you enter the values with a citation when you need them." };
const NO_DECISION_BLOCKED = (why: string): Unblock => ({ decisions: [], text: `No setting can unblock this: ${why}` });

/** Cited copy of registry.py statuses (status_ref quoted from the registry entry). A test checks it against registry.py. */
export const REGISTRY_OVERLAY: Record<string, RegistryEntry> = {
  "amfi.navall": {
    name: "AMFI NAVAll.txt (latest NAV, all schemes)", licence: "PERSONAL_USE_ONLY", status: "VERIFIED",
    status_ref: "probe 2026-10-15, docs/data/probes/README.md", unblock: AMFI_UNBLOCK,
  },
  "amfi.navhistory": {
    name: "AMFI NAV history report", licence: "PERSONAL_USE_ONLY", status: "VERIFIED",
    status_ref: "probe 2026-10-15, docs/data/probes/README.md", unblock: AMFI_UNBLOCK,
  },
  "amfi.schememaster": {
    name: "AMFI scheme master CSV", licence: "PERSONAL_USE_ONLY", status: "VERIFIED",
    status_ref: "probe 2026-10-15, docs/data/probes/README.md", unblock: AMFI_UNBLOCK,
  },
  "mospi.cpi": {
    name: "MoSPI CPI API", licence: "PUBLIC_GOVT", status: "VERIFIED",
    status_ref: "filtered no-login queries probed, docs/research/wave1/audit-automation.md §3.1",
    unblock: { decisions: [], text: "Usable now; no credentials needed." },
  },
  "mfapi.in": {
    name: "mfapi.in (UNOFFICIAL mirror of AMFI)", licence: "UNKNOWN", status: "BLOCKED",
    status_ref: "unofficial mirror; disabled by policy (source-registry.md)",
    unblock: NO_DECISION_BLOCKED("an unofficial mirror is never used as a source; AMFI itself is used instead."),
  },
  "amfi.ter": {
    name: "AMFI TER of MF schemes", licence: "PERSONAL_USE_ONLY", status: "REQUIRES CONFIGURATION",
    status_ref: "manual entry; no download link (audit-automation.md §3.3)",
    unblock: {
      decisions: ["U-14"],
      text: "U-14 (default: off). Upload a factsheet or type the TER when comparing different funds; the TER JSON endpoint stays off.",
    },
  },
  "amfi.riskometer": {
    name: "Riskometer / PRC disclosures", licence: "PERSONAL_USE_ONLY", status: "BLOCKED",
    status_ref: "crawling blocked by AMC terms; user-supplied file only (audit-automation.md #5)",
    unblock: NO_DECISION_BLOCKED("AMC terms forbid crawling. You can still upload the disclosure file yourself."),
  },
  "rbi.home.rates": {
    name: "RBI home page current rates (policy rates)", licence: "PUBLIC_GOVT", status: "BLOCKED",
    status_ref: "RBI disclaimer and WAF; manual entry (audit-automation.md §2.4)",
    unblock: NO_DECISION_BLOCKED("the RBI disclaimer forbids caching and the site blocks scripts. Enter the rate by hand."),
  },
  "rbi.pr.tbill": {
    name: "RBI T-bill auction result press releases (cut-off yields)", licence: "PUBLIC_GOVT", status: "NOT VERIFIED",
    status_ref:
      "release page and formula probed (audit-automation.md §3.2); a cut-off item's feed description carrying the table is NOT VERIFIED",
    unblock: {
      decisions: [],
      text: "No decision needed: verified by the first live run, whose yields must pass the (100 − P)/P × 365/days self-check.",
    },
  },
  "rbi.rss.pressreleases": {
    name: "RBI press releases RSS feed", licence: "PUBLIC_GOVT", status: "VERIFIED",
    status_ref: "feed answered HTTP 200 text/xml to an honest user-agent (audit-automation.md §2.4, §3.2)",
    unblock: { decisions: [], text: "Usable now; citations shown as plain text, never as links." },
  },
  "rbi.dbie": {
    name: "RBI Database on Indian Economy", licence: "PUBLIC_GOVT", status: "NOT VERIFIED",
    status_ref: "no documented API; licence NOT VERIFIED (audit-automation.md §3.2)",
    unblock: { decisions: [], text: "No decision of yours unblocks it: the licence must be read first. Manual downloads only." },
  },
  "rbi.wadtdr": {
    name: "RBI weighted average domestic term deposit rate", licence: "PUBLIC_GOVT", status: "REQUIRES CONFIGURATION",
    status_ref: "manual reference series; RSS parser not built (audit-automation.md §3.2)", unblock: MANUAL,
  },
  "ccil.marketwatch": {
    name: "CCIL NDS-OM Market Watch (manual citation only)", licence: "PERSONAL_USE_ONLY", status: "REQUIRES CONFIGURATION",
    status_ref: "user enters values with citation", unblock: MANUAL,
  },
  "bond.quote": {
    name: "Bond price/yield (user-entered with citation)", licence: "PERSONAL_USE_ONLY", status: "REQUIRES CONFIGURATION",
    status_ref: "user enters quote, page URL and date", unblock: MANUAL,
  },
  "cra.ratings": {
    name: "Credit rating agency rating actions", licence: "UNKNOWN", status: "BLOCKED",
    status_ref: "CRISIL forbids copying; others NOT VERIFIED (audit-automation.md #14)",
    unblock: NO_DECISION_BLOCKED("rating agency terms forbid copying. Enter the rating, agency, date and rationale link by hand."),
  },
  dicgc: {
    name: "DICGC deposit insurance limit", licence: "PUBLIC_GOVT", status: "REQUIRES CONFIGURATION",
    status_ref: "curated constant with citation", unblock: MANUAL,
  },
  "bank.fd": {
    name: "Bank FD terms (user-entered)", licence: "UNKNOWN", status: "REQUIRES CONFIGURATION",
    status_ref: "user enters own FD terms", unblock: MANUAL,
  },
  "amc.factsheet": {
    name: "AMC monthly factsheet (user-entered)", licence: "UNKNOWN", status: "BLOCKED",
    status_ref: "AMC terms forbid crawling; user-supplied PDF only (audit-automation.md #6)",
    unblock: NO_DECISION_BLOCKED("AMC terms forbid crawling. Upload the factsheet you downloaded; it is parsed and discarded."),
  },
  "mof.smallsavings": {
    name: "Small-savings rates (DEA OM / DoP SB Order)", licence: "PUBLIC_GOVT", status: "REQUIRES CONFIGURATION",
    status_ref: "curated table with OM citation", unblock: MANUAL,
  },
  "itd.tax": {
    name: "Income-tax rule sets", licence: "PUBLIC_GOVT", status: "REQUIRES CONFIGURATION",
    status_ref: "curated, versioned rule set",
    unblock: { decisions: ["U-05"], text: "Rules are curated in the app. U-05 (default: conservative assumption): enter your slab and regime." },
  },
  "sebi.regs": {
    name: "SEBI regulations and circulars", licence: "PUBLIC_GOVT", status: "REQUIRES CONFIGURATION",
    status_ref: "citations only", unblock: MANUAL,
  },
  "calendar.trading": {
    name: "Trading and holiday calendars (curated)", licence: "PUBLIC_GOVT", status: "REQUIRES CONFIGURATION",
    status_ref: "curated by hand from official circulars", unblock: MANUAL,
  },
};

type OffRegistry = Omit<DataRightsRow, "from_registry" | "feeds"> & { feeds: string };

/** Sources kept out of the registry on purpose (design-risk-first.md §2.1), with the decision that would unblock each. */
export const OFF_REGISTRY_SOURCES: readonly OffRegistry[] = [
  {
    id: "amfi.hosted.core", name: "AMFI data stored in the hosted app beyond held and watched schemes",
    feeds: "Core-universe tracking on the phone view", licence: "PERSONAL_USE_ONLY",
    licence_note: "AMFI terms: “personal and non-commercial use only”; “You shall not store electronically any significant portion”.",
    terms_url: "https://www.amfiindia.com/terms-of-use", status: "BLOCKED",
    status_ref: "registry flags hosted use as REQUIRES LICENCE / WRITTEN PERMISSION (design-risk-first.md §2.1; ADR-0017)",
    unblock: {
      decisions: ["U-01", "U-17"],
      text:
        "Written permission from AMFI. The letter is drafted at docs/operations/amfi-permission-letter-draft.md for you to " +
        "send (U-01, decided 2026-10-16; U-17). Until then the core universe is tracked on your computer only.",
    },
  },
  {
    id: "user.cas", name: "Your CAS statement (CAMS / KFin PDF you download)", feeds: "Holdings, lots, Regular/Direct, exit loads charged",
    licence: "USER_OWNED", licence_note: "Your own data; encrypted at rest.", terms_url: null, status: "VERIFIED",
    status_ref: "existing CAS import (routes_cas.py)", unblock: { decisions: [], text: "Usable now: upload your CAS." },
  },
  {
    id: "user.documents", name: "Documents you upload (factsheet, monthly portfolio, SID load structure)",
    feeds: "Duration, YTM, credit mix, exit loads", licence: "USER_OWNED",
    licence_note: "Uploaded by you and parsed deterministically; no crawling (AMC and bank terms forbid it).", terms_url: null,
    status: "REQUIRES CONFIGURATION", status_ref: "design-risk-first.md §2.1",
    unblock: { decisions: [], text: "No decision needed: upload the document when a card asks for it." },
  },
  {
    id: "nse.automated", name: "NSE website and bhavcopy, automated", feeds: "Stock and ETF prices", licence: "PERSONAL_USE_ONLY",
    licence_note: "NSE terms: “User is prohibited to conduct any systematic or automated data collection activities”.",
    terms_url: "https://www.nseindia.com/static/nse-terms-of-use", status: "BLOCKED", status_ref: "research-equity-data-nse.md",
    unblock: {
      decisions: ["U-10", "U-17"],
      text: "Decided 2026-10-16 (U-10): no stock data; stocks ABSTAIN. Only written permission from NSE (U-17) could change this.",
    },
  },
  {
    id: "nse.manual", name: "NSE bhavcopy, downloaded by hand and parsed locally", feeds: "Stock prices, local mode only",
    licence: "PERSONAL_USE_ONLY", licence_note: "NSE terms on aggregation and electronic retrieval are ambiguous (verify NSE-6).",
    terms_url: "https://www.nseindia.com/static/nse-terms-of-use", status: "NOT VERIFIED",
    status_ref: "design-risk-first.md §2.1 (ambiguous clause)",
    unblock: { decisions: ["U-10"], text: "U-10 option (d), email NSE first. Decided 2026-10-16: (a) none, so this stays off." },
  },
  {
    id: "niftyindices.tri", name: "NSE Indices TRI CSVs (niftyindices.com)", feeds: "Long index history for stress tables",
    licence: "PERSONAL_USE_ONLY",
    licence_note: "“No material from the Site may be copied … uploaded … without prior written permission” (verify MOM-8).",
    terms_url: null, status: "BLOCKED",
    status_ref: "BLOCKED for hosted upload; NOT VERIFIED for local manual import (design-risk-first.md §2.1)",
    unblock: {
      decisions: ["U-08", "U-17"],
      text: "U-08 (default: stress constants live in local config). Written permission from NSE Indices (U-17) would unblock storage.",
    },
  },
  {
    id: "broker.api", name: "Upstox / Angel One SmartAPI on your own account", feeds: "Daily stock and ETF candles, local only",
    licence: "UNKNOWN", licence_note: "Developer terms on storage and backtesting are unread; candles adjust splits and bonuses only.",
    terms_url: null, status: "NOT VERIFIED", status_ref: "REQUIRES CONFIGURATION + NOT VERIFIED (design-risk-first.md §2.1; X-01)",
    unblock: {
      decisions: ["U-10"],
      text: "U-10 options (b)/(c), after the developer terms are read (X-01). Decided 2026-10-16: (a) none, so this stays off.",
    },
  },
  {
    id: "kite.connect", name: "Zerodha Kite Connect", feeds: "Stock candles", licence: "LICENSED",
    licence_note: "Paid (₹500/month); terms forbid “build databases, or otherwise create permanent copies”.",
    terms_url: "https://kite.trade/terms/", status: "BLOCKED", status_ref: "design-risk-first.md §2.1",
    unblock: NO_DECISION_BLOCKED("it needs a paid key (the app uses none) and its database clause conflicts with a backtest store."),
  },
  {
    id: "scrapers", name: "yfinance, jugaad-data, nsepython, nsetools", feeds: "—", licence: "UNKNOWN",
    licence_note: "Yahoo bans automated collection; the NSE libraries scrape NSE.", terms_url: null, status: "BLOCKED",
    status_ref: "design-risk-first.md §2.1", unblock: NO_DECISION_BLOCKED("these tools break the sites' terms."),
  },
  {
    id: "iima.factors", name: "IIMA factor library", feeds: "Optional factor-evidence panel", licence: "UNKNOWN",
    licence_note: "Citation requested; no licence stated.", terms_url: null, status: "REQUIRES CONFIGURATION",
    status_ref: "research-evidence-value-quality.md",
    unblock: { decisions: ["U-17"], text: "Manual import for personal use, pinned by hash; optionally ask the authors (U-17)." },
  },
];

const LICENCE_TEXT: Record<LicenceClass, string> = {
  PERSONAL_USE_ONLY: "Personal use only",
  PUBLIC_GOVT: "Public government data",
  LICENSED: "Licensed (paid)",
  USER_OWNED: "Your own data",
  UNKNOWN: "Licence unknown",
};

/** Hosts whose pages may not be deep-linked (RBI disclaimer; registry.py NO_DEEP_LINK_HOSTS). */
const NO_LINK_HOSTS = ["rbi.org.in"];

function isLabel(s: unknown): s is SourceStatusLabel {
  return typeof s === "string" && (STATUS_LABELS as readonly string[]).includes(s);
}

type LiveSource = SourceHealth & { status?: string; status_ref?: string };

/** Merge the live registry (or null when it could not be loaded) with the cited and off-registry sources. */
export function buildRows(live: LiveSource[] | null): DataRightsRow[] {
  const rows: DataRightsRow[] = [];
  const seen = new Set<string>();
  for (const s of live ?? []) {
    const cited = REGISTRY_OVERLAY[s.source_id];
    const reported = isLabel(s.status) ? s.status : null;
    const status: SourceStatusLabel = reported ?? cited?.status ?? "NOT VERIFIED";
    const status_ref = reported
      ? (s.status_ref ?? "reported by the server")
      : (cited?.status_ref ?? "the server did not report a status for this source, so it is not treated as verified");
    rows.push({
      id: s.source_id, name: s.name, feeds: s.freshness, licence: s.licence, licence_note: s.licence_note,
      terms_url: s.terms_url, status, status_ref, from_registry: true,
      unblock: cited?.unblock ?? {
        decisions: [],
        text: status === "BLOCKED" ? "No setting can unblock this source." : "No decision recorded for this source yet.",
      },
    });
    seen.add(s.source_id);
  }
  for (const [id, c] of Object.entries(REGISTRY_OVERLAY)) {
    if (seen.has(id)) continue;
    rows.push({ id, name: c.name, feeds: "", licence: c.licence, licence_note: "", terms_url: null, status: c.status,
      status_ref: c.status_ref, unblock: c.unblock, from_registry: true });
  }
  for (const o of OFF_REGISTRY_SOURCES) rows.push({ ...o, from_registry: false });
  return rows;
}

function Terms({ url }: { url: string | null }) {
  if (!url) return null;
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    return null;
  }
  if (NO_LINK_HOSTS.some((h) => host === h || host.endsWith(`.${h}`)))
    return <span className="small subtle"> Terms: {url} (shown as text; deep links need RBI's permission).</span>;
  return (
    <>
      {" "}
      <a className="small" href={url} rel="noopener noreferrer" target="_blank">
        Read the terms
      </a>
    </>
  );
}

export function DataRightsPanel() {
  const health = useApi<DataHealthResponse>("/api/data-health");
  const live = health.data ? (health.data.sources as LiveSource[]) : null;
  const rows = buildRows(live);
  const counts = STATUS_LABELS.map((l) => [l, rows.filter((r) => r.status === l).length] as const);
  return (
    <div className="card" aria-labelledby="data-rights-title">
      <h2 id="data-rights-title">Data sources and rights</h2>
      <p className="small">
        Every source the app uses or has refused, with its licence, its status and the decision that would unblock it. A fact from
        a BLOCKED source or with an unknown licence never reaches the engine.
      </p>
      {health.loading ? <p className="small subtle">Loading the live source registry…</p> : null}
      {!health.loading && !health.data ? (
        <p className="callout callout--warn small" role="status">
          The live source registry could not be loaded, so the list below uses the statuses cited from the code registry.
        </p>
      ) : null}
      <p className="small">
        {counts.map(([l, n], i) => (
          <span key={l}>
            {i ? " · " : ""}
            {l}: {n}
          </span>
        ))}
      </p>
      <div className="table-wrap">
        <table className="table table--compact">
          <caption>Every data source, its licence, status and what unblocks it</caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Licence</th>
              <th scope="col">Status</th>
              <th scope="col">Unblocked by</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <th scope="row">
                  {r.name}
                  {r.feeds ? <div className="small subtle">{r.feeds}</div> : null}
                </th>
                <td>
                  {LICENCE_TEXT[r.licence] ?? r.licence}
                  {r.licence_note ? <div className="small subtle">{r.licence_note}</div> : null}
                  <Terms url={r.terms_url} />
                </td>
                <td>
                  <span className="chip">{r.status}</span>
                  <div className="small subtle">{r.status_ref}</div>
                </td>
                <td className="small">
                  {r.unblock.decisions.length ? <strong>{r.unblock.decisions.join(", ")}: </strong> : null}
                  {r.unblock.text}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
