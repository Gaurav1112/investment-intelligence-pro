import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { DataHealthResponse, SourceHealth } from "../lib/types";
import { STATUS_LABELS } from "../lib/types-settings";
import { DataRightsPanel, OFF_REGISTRY_SOURCES, REGISTRY_OVERLAY, buildRows } from "./DataRightsPanel";

// SYNTHETIC registry rows shaped like GET /api/data-health `sources` (routes_core.py data_health). No market data.
const src = (over: Partial<SourceHealth> & { source_id: string; status?: string; status_ref?: string }): SourceHealth & { status?: string; status_ref?: string } => ({
  name: `Synthetic ${over.source_id}`,
  owner: "Test owner",
  official: true,
  mode: "live",
  licence: "PERSONAL_USE_ONLY",
  licence_note: "Synthetic licence note.",
  terms_url: null,
  freshness: "synthetic",
  requires_configuration: false,
  last_run: null,
  ...over,
});

const HEALTH = (sources: SourceHealth[]): DataHealthResponse => ({
  sources,
  runs: [],
  observation_counts: {},
  tax_rules_loaded: true,
  tax_rules_coverage_to: null,
});

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

function rowFor(name: RegExp | string) {
  const cell = screen.getByRole("rowheader", { name });
  return cell.closest("tr")!;
}

describe("buildRows", () => {
  it("lists every registry source plus every off-registry source, each with one of the four status labels and a decision", () => {
    const rows = buildRows([src({ source_id: "amfi.navall" }), src({ source_id: "synthetic.new" })]);
    const ids = rows.map((r) => r.id);
    expect(ids).toContain("amfi.navall");
    expect(ids).toContain("synthetic.new");
    for (const s of OFF_REGISTRY_SOURCES) expect(ids).toContain(s.id);
    for (const r of rows) {
      expect(STATUS_LABELS).toContain(r.status);
      expect(r.licence).toBeTruthy();
      expect(r.unblock.text.length).toBeGreaterThan(10);
    }
  });

  it("uses the server's status when it reports one, the cited registry status otherwise, and NOT VERIFIED when unknown", () => {
    const rows = buildRows([
      src({ source_id: "amfi.navall", status: "NOT VERIFIED", status_ref: "synthetic server ref" }),
      src({ source_id: "mospi.cpi" }),
      src({ source_id: "synthetic.new" }),
      src({ source_id: "synthetic.bad", status: "GREEN" }),
    ]);
    const by = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(by["amfi.navall"]!.status).toBe("NOT VERIFIED");
    expect(by["amfi.navall"]!.status_ref).toBe("synthetic server ref");
    expect(by["mospi.cpi"]!.status).toBe(REGISTRY_OVERLAY["mospi.cpi"]!.status);
    expect(by["synthetic.new"]!.status).toBe("NOT VERIFIED");
    expect(by["synthetic.new"]!.status_ref).toMatch(/did not report a status/);
    expect(by["synthetic.bad"]!.status).toBe("NOT VERIFIED");
  });

  it("without the live registry still lists the cited registry sources and the off-registry ones", () => {
    const rows = buildRows(null);
    expect(rows.length).toBe(Object.keys(REGISTRY_OVERLAY).length + OFF_REGISTRY_SOURCES.length);
  });

  it("records the user's decisions: stocks abstain (U-10), hosted AMFI beyond held/watched is blocked pending permission (U-01)", () => {
    const rows = buildRows(null);
    const nse = rows.find((r) => r.id === "nse.automated")!;
    expect(nse.status).toBe("BLOCKED");
    expect(nse.unblock.decisions).toContain("U-10");
    const hosted = rows.find((r) => r.id === "amfi.hosted.core")!;
    expect(hosted.status).toBe("BLOCKED");
    expect(hosted.unblock.decisions).toEqual(expect.arrayContaining(["U-01", "U-17"]));
    expect(rows.find((r) => r.id === "kite.connect")!.status).toBe("BLOCKED");
    expect(rows.find((r) => r.id === "user.cas")!.licence).toBe("USER_OWNED");
  });
});

describe("registry drift guard", () => {
  it("every cited registry status matches backend/src/iip/data/registry.py", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const py = readFileSync(join(here, "../../../backend/src/iip/data/registry.py"), "utf8");
    const enumToLabel: Record<string, string> = {
      VERIFIED: "VERIFIED",
      NOT_VERIFIED: "NOT VERIFIED",
      REQUIRES_CONFIGURATION: "REQUIRES CONFIGURATION",
      BLOCKED: "BLOCKED",
    };
    const found: Record<string, string> = {};
    const re = /\bid="([^"]+)",[\s\S]*?status=SourceStatus\.([A-Z_]+)/g;
    for (const m of py.matchAll(re)) found[m[1]!] = enumToLabel[m[2]!]!;
    expect(Object.keys(found).length).toBeGreaterThan(10);
    const cited = Object.fromEntries(Object.entries(REGISTRY_OVERLAY).map(([k, v]) => [k, v.status]));
    expect(cited).toEqual(found);
  });

  it("every cited registry licence class matches registry.py", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const py = readFileSync(join(here, "../../../backend/src/iip/data/registry.py"), "utf8");
    const found: Record<string, string> = {};
    for (const m of py.matchAll(/\bid="([^"]+)",[\s\S]*?licence_class=LicenceClass\.([A-Z_]+)/g)) found[m[1]!] = m[2]!;
    const cited = Object.fromEntries(Object.entries(REGISTRY_OVERLAY).map(([k, v]) => [k, v.licence]));
    expect(cited).toEqual(found);
  });
});

describe("DataRightsPanel", () => {
  it("renders every source with its licence, status label and the decision that unblocks it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(HEALTH([src({ source_id: "amfi.navall", name: "Synthetic AMFI feed", status: "VERIFIED", status_ref: "probe" })])),
      ),
    );
    render(<DataRightsPanel />);
    expect(await screen.findByRole("rowheader", { name: /Synthetic AMFI feed/ })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Every data source/ });
    const body = within(table).getAllByRole("row").slice(1);
    expect(body.length).toBe(buildRows([src({ source_id: "amfi.navall" })]).length);
    for (const tr of body) {
      const cells = within(tr).getAllByRole("cell");
      const text = tr.textContent ?? "";
      expect(STATUS_LABELS.some((l) => text.includes(l))).toBe(true);
      expect(cells.length).toBe(3);
    }
    const amfi = rowFor(/Synthetic AMFI feed/);
    expect(within(amfi).getByText("VERIFIED")).toBeInTheDocument();
    expect(within(amfi).getByText(/Personal use only/)).toBeInTheDocument();
    const nse = rowFor(/NSE website and bhavcopy, automated/);
    expect(within(nse).getByText("BLOCKED")).toBeInTheDocument();
    expect(within(nse).getAllByText(/U-10/).length).toBeGreaterThan(0);
    // A per-status count summary.
    expect(screen.getByText(/BLOCKED: \d+/)).toBeInTheDocument();
  });

  it("never renders an RBI terms page as a link (RBI disclaimer: deep links need permission)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          HEALTH([
            src({ source_id: "rbi.pr.tbill", name: "Synthetic RBI feed", licence: "PUBLIC_GOVT", terms_url: "https://www.rbi.org.in/Scripts/Disclaimer.aspx" }),
            src({ source_id: "amfi.navall", name: "Synthetic AMFI feed", terms_url: "https://www.amfiindia.com/terms-of-use" }),
          ]),
        ),
      ),
    );
    render(<DataRightsPanel />);
    await screen.findByRole("rowheader", { name: /Synthetic RBI feed/ });
    const rbi = rowFor(/Synthetic RBI feed/);
    expect(within(rbi).queryByRole("link")).not.toBeInTheDocument();
    expect(within(rbi).getByText(/rbi\.org\.in/)).toBeInTheDocument();
    const amfi = rowFor(/Synthetic AMFI feed/);
    expect(within(amfi).getByRole("link", { name: /terms/i })).toHaveAttribute("href", "https://www.amfiindia.com/terms-of-use");
  });

  it("still lists the cited sources when the live registry cannot be loaded, and says so", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "INTERNAL_ERROR" }, 500)));
    render(<DataRightsPanel />);
    expect(await screen.findByText(/live source registry could not be loaded/)).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: /NSE website and bhavcopy, automated/ })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: /AMFI NAVAll/ })).toBeInTheDocument();
  });
});
