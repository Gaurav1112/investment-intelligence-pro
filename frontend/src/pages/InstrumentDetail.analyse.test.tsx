import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { InstrumentDetailResponse } from "../lib/types";
import InstrumentDetail from "./InstrumentDetail";

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });

const DETAIL: InstrumentDetailResponse = {
  instrument: {
    instrument_id: "mf:900003",
    kind: "mf_scheme",
    name: "FIXTURE Large Cap Fund C — Direct · Growth",
    issuer_id: null,
    isin: null,
    amfi_code: "900003",
    currency: "INR",
    origin: "fixture",
    created_at: "2026-10-15T06:00:00+00:00",
  },
  series: { series_id: "nav:900003", points: [] },
  freshness: { badge: "FIXTURE", observed: null },
};

afterEach(() => vi.unstubAllGlobals());

it("instrument detail links to risk, return-target feasibility and compare for this instrument", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(DETAIL)));
  render(
    <MemoryRouter initialEntries={["/i/mf%3A900003"]}>
      <Routes>
        <Route path="/i/:id" element={<InstrumentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
  const nav = await screen.findByRole("navigation", { name: "Analyse this instrument" });
  expect(within(nav).getByRole("link", { name: "Risk" })).toHaveAttribute("href", "/risk?id=mf%3A900003");
  expect(within(nav).getByRole("link", { name: "Return-target feasibility" })).toHaveAttribute("href", "/scenarios?tab=feasibility&id=mf%3A900003");
  expect(within(nav).getByRole("link", { name: "Compare" })).toHaveAttribute("href", "/compare?ids=mf%3A900003");
});
