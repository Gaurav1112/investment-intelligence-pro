import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { EvidenceResponse } from "../lib/types";
import Evidence from "./Evidence";

// Shape follows backend/src/iip/services/portfolio.py evidence().
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const stub = (fn: (url: string) => Response) => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      return fn(url);
    }),
  );
  return urls;
};

const SHA = "3b".repeat(32);
const EV: EvidenceResponse = {
  observation: {
    obs_id: 42, series_id: "nav:119551", kind: "nav", value: "1234.5678", unit: "INR/unit", currency: "INR", source_id: "amfi.nav",
    url: "https://www.amfiindia.com/spages/NAVAll.txt", retrieved_at: "2026-10-14T18:05:00+00:00", observation_date: "2026-10-14",
    publication_time: null, sha256: SHA, quality: "ok", convention: "NAV per unit, declared", ingestion_run_id: "run_1", superseded_by: null,
  },
  is_current: true,
  fixture: false,
  superseded_chain: {
    newer: [],
    older: [{ obs_id: 40, value: "1234.5600", observation_date: "2026-10-14", retrieved_at: "2026-10-14T16:00:00+00:00", quality_status: "ok", sha256: "c".repeat(64), superseded_by: 42 }],
  },
  source: { source_id: "amfi.nav", owner: "AMFI", official: 1, url: "https://www.amfiindia.com", terms_url: null, licence_note: "Public data", mode: "live", freshness_slo_days: 1 },
  ingestion_run: { run_id: "run_1", source_id: "amfi.nav", started_at: "2026-10-14T18:00:00+00:00", finished_at: "2026-10-14T18:06:00+00:00", status: "ok" },
};

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/evidence" element={<Evidence />} />
        <Route path="/evidence/:obsId" element={<Evidence />} />
      </Routes>
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Evidence", () => {
  it("shows full provenance and the superseded chain", async () => {
    const urls = stub(() => json(EV));
    renderAt("/evidence/42");
    expect(await screen.findByText("amfi.nav")).toBeInTheDocument();
    expect(urls).toEqual(["/api/evidence/42"]);
    expect(screen.getByText("https://www.amfiindia.com/spages/NAVAll.txt")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source page" })).toHaveAttribute("href", EV.observation.url);
    expect(screen.getByText("14-Oct-2026 18:05 UTC")).toBeInTheDocument();
    expect(screen.getByText("14-Oct-2026 (India calendar date)")).toBeInTheDocument();
    expect(screen.getAllByText(SHA).length).toBeGreaterThan(0);
    expect(screen.getByText("NAV per unit, declared")).toBeInTheDocument();
    expect(screen.getByText(/official source/)).toBeInTheDocument();
    expect(screen.getByText("This is the current stored value for its series.")).toBeInTheDocument();
    expect(screen.getByText("None — nothing has replaced this value.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#40" })).toHaveAttribute("href", "/evidence/40");
  });

  it("marks a superseded fixture observation and links forward", async () => {
    stub(() =>
      json({
        ...EV,
        is_current: false,
        fixture: true,
        observation: { ...EV.observation, quality: "fixture", superseded_by: 43 },
        superseded_chain: { newer: [{ ...EV.superseded_chain.older[0]!, obs_id: 43, superseded_by: null }], older: [] },
      }),
    );
    renderAt("/evidence/42");
    expect(await screen.findByText(/FIXTURE — not market data/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "observation #43" })).toHaveAttribute("href", "/evidence/43");
    expect(screen.getByText("None — this value replaced nothing.")).toBeInTheDocument();
  });

  it("says plainly when an observation does not exist", async () => {
    stub(() => json({ code: "NOT_FOUND", message: "observation not found" }, 404));
    renderAt("/evidence/999999");
    expect(await screen.findByText("No observation #999999 is stored.")).toBeInTheDocument();
  });

  it("rejects a non-numeric id without calling the API", () => {
    const urls = stub(() => json(EV));
    renderAt("/evidence/abc");
    expect(screen.getByRole("alert")).toHaveTextContent("is not an observation id");
    expect(urls).toEqual([]);
  });

  it("explains evidence and looks up an id", async () => {
    const urls = stub(() => json(EV));
    renderAt("/evidence");
    expect(screen.getByRole("heading", { name: "Evidence", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Data health" })).toHaveAttribute("href", "/data-health");
    fireEvent.change(screen.getByLabelText("Observation id"), { target: { value: "x1" } });
    await userEvent.click(screen.getByRole("button", { name: "Show evidence" }));
    expect(screen.getByText(/Enter an observation id/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Observation id"), { target: { value: "42" } });
    await userEvent.click(screen.getByRole("button", { name: "Show evidence" }));
    expect(await screen.findByText("NAV per unit, declared")).toBeInTheDocument();
    expect(urls).toEqual(["/api/evidence/42"]);
  });
});
