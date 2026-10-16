import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { DataHealthResponse } from "../lib/types";
import DataHealth from "./DataHealth";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const stub = (body: unknown, status = 200) => vi.stubGlobal("fetch", vi.fn(async () => json(body, status)));
afterEach(() => vi.unstubAllGlobals());

const AMFI_NOTE = "AMFI ToU: personal, non-commercial use only; do not store a significant portion; no redistribution.";
const HEALTH: DataHealthResponse = {
  sources: [
    {
      source_id: "amfi.navall", name: "AMFI NAVAll.txt (latest NAV, all schemes)", owner: "AMFI", official: true, mode: "live",
      licence: "PERSONAL_USE_ONLY", licence_note: AMFI_NOTE, terms_url: "https://www.amfiindia.com/terms-of-use",
      freshness: "NAV for T by 23:00 IST on T; stale 2-3 business days", requires_configuration: true,
      last_run: { status: "partial", finished_at: "2026-10-15T05:34:19+00:00", rows_ok: 1530, rows_rejected: 4, error: null },
    },
    {
      source_id: "mfapi.in", name: "mfapi.in (UNOFFICIAL mirror of AMFI)", owner: "Independent operator", official: false, mode: "disabled",
      licence: "UNKNOWN", licence_note: "No terms page found.", terms_url: null, freshness: "NAV SLO", requires_configuration: false, last_run: null,
    },
    {
      source_id: "amfi.ter", name: "AMFI TER of MF schemes", owner: "AMFI", official: true, mode: "manual", licence: "PERSONAL_USE_ONLY",
      licence_note: AMFI_NOTE, terms_url: "https://www.amfiindia.com/terms-of-use", freshness: "Current or previous month fresh",
      requires_configuration: false, last_run: null,
    },
  ],
  runs: [
    { run_id: "run_2", source_id: "amfi.navall", started_at: "2026-10-15T05:33:00+00:00", finished_at: "2026-10-15T05:34:19+00:00", status: "partial", rows_ok: 1530, rows_rejected: 4, raw_sha256: "a".repeat(64), error: null },
    { run_id: "run_1", source_id: "amfi.navhistory", started_at: "2026-10-14T05:33:00+00:00", finished_at: "2026-10-14T05:33:30+00:00", status: "failed", rows_ok: 0, rows_rejected: 0, raw_sha256: null, error: "FetchRefused: timeout" },
  ],
  observation_counts: { ok: 25000, fixture: 7300, manual: 2 },
  tax_rules_loaded: true,
  tax_rules_coverage_to: "2027-03-31",
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <DataHealth />
    </MemoryRouter>,
  );

describe("DataHealth", () => {
  it("renders per-source mode, licence, freshness and last run", async () => {
    stub(HEALTH);
    renderPage();
    const row = (await screen.findByText("AMFI NAVAll.txt (latest NAV, all schemes)")).closest("tr")!;
    expect(within(row).getByText("FETCHED")).toBeInTheDocument();
    expect(within(row).getByText("Personal, non-commercial use only")).toBeInTheDocument();
    expect(within(row).getByText(AMFI_NOTE)).toBeInTheDocument();
    expect(within(row).getByText(/stale 2-3 business days/)).toBeInTheDocument();
    expect(within(row).getByText(/PARTIAL/)).toBeInTheDocument();
    expect(within(row).getByText("finished 15-Oct-2026 05:34 UTC")).toBeInTheDocument();
    expect(within(row).getByText(/rows ok 1530 · rejected 4/)).toBeInTheDocument();

    const disabled = screen.getByText("mfapi.in (UNOFFICIAL mirror of AMFI)").closest("tr")!;
    expect(within(disabled).getByText("DISABLED")).toBeInTheDocument();
    expect(within(disabled).getByText(/Never fetched and never used/)).toBeInTheDocument();
    expect(within(disabled).getByText(/UNOFFICIAL — cross-check only/)).toBeInTheDocument();
    expect(within(disabled).getByText("never run")).toBeInTheDocument();

    const manual = screen.getByText("AMFI TER of MF schemes").closest("tr")!;
    expect(within(manual).getByText("MANUAL ONLY")).toBeInTheDocument();
    expect(within(manual).getByText(/Values exist only if you enter them/)).toBeInTheDocument();
  });

  it("renders runs, observation counts (fixture labelled) and tax coverage", async () => {
    stub(HEALTH);
    renderPage();
    const runs = await screen.findByRole("table", { name: /Recent ingestion runs/ });
    expect(within(runs).getByText("FetchRefused: timeout")).toBeInTheDocument();
    expect(within(runs).getByText(/FAILED/)).toBeInTheDocument();
    expect(screen.getByText("7300")).toBeInTheDocument();
    expect(screen.getByText(/FIXTURE — synthetic, not market data/)).toBeInTheDocument();
    expect(screen.getByText("31-Mar-2027")).toBeInTheDocument();
  });

  it("shows empty states when nothing has run or been stored, and flags missing tax rules", async () => {
    stub({ ...HEALTH, runs: [], observation_counts: {}, tax_rules_loaded: false, tax_rules_coverage_to: null });
    renderPage();
    expect(await screen.findByText("No ingestion has run yet")).toBeInTheDocument();
    expect(screen.getByText("No observations are stored yet")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("tax rule file failed to load");
  });

  it("lists hosted scheduled-job failures and daily-check findings (silent-failure-hunter-02 d)", async () => {
    const jobs = {
      lookback_days: 14,
      problems: [
        { job: "snapshot", run_key: "attempt:2026-10-15", state: "failed", attempts: 2, started_at: "2026-10-15T05:10:00+00:00", finished_at: "2026-10-15T05:10:02+00:00", detail_code: "SNAPSHOT_FAILED" },
        { job: "watchdog", run_key: "2026-10-14", state: "done", attempts: 1, started_at: "2026-10-14T16:00:00+00:00", finished_at: "2026-10-14T16:00:01+00:00", detail_code: "ATTENTION;SNAPSHOT_MISSING;NAV_STALE" },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => json(String(url).includes("/api/data-health/jobs") ? jobs : HEALTH)));
    renderPage();
    const table = await screen.findByRole("table", { name: /Scheduled-job problems/ });
    const snap = within(table).getByText("J4 · today's cards").closest("tr")!;
    expect(within(snap).getByText("failed: SNAPSHOT_FAILED")).toBeInTheDocument();
    expect(within(snap).getByText("2")).toBeInTheDocument();
    const dog = within(table).getByText("J5 · daily check").closest("tr")!;
    expect(within(dog).getByText("found SNAPSHOT_MISSING, NAV_STALE")).toBeInTheDocument();
  });

  it("says plainly when there are no scheduled-job problems, and when their status cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      json(String(url).includes("/api/data-health/jobs") ? { lookback_days: 14, problems: [] } : HEALTH)));
    renderPage();
    expect(await screen.findByText(/No scheduled-job failures or daily-check findings in the last 14 days/)).toBeInTheDocument();
  });

  it("does not hide scheduled-job status behind a silent blank when its endpoint fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      String(url).includes("/api/data-health/jobs") ? json({ code: "INTERNAL_ERROR" }, 500) : json(HEALTH)));
    renderPage();
    expect(await screen.findByText(/Scheduled-job status could not be read/)).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    stub({ code: "INTERNAL_ERROR" }, 500);
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("INTERNAL_ERROR");
  });
});
