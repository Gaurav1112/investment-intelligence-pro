import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { INSTRUMENTS, SIMULATE, SIMULATE_MISMATCH } from "../test/analysisFixtures";
import Simulator, { checkWeights } from "./Simulator";

type Call = { url: string; method: string; body: unknown };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

function stubFetch(handler: (url: string, method: string, body: unknown) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body });
      return handler(url, method, body);
    }),
  );
  return calls;
}

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/simulate" element={<Simulator />} />
      </Routes>
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

const w = (...pcts: string[]) => pcts.map((weightPct) => ({ weightPct }));

describe("checkWeights (exact decimal strings, no float sum)", () => {
  it("accepts 33.33 + 33.33 + 33.34 = 100 and converts each to an exact fraction string", () => {
    const c = checkWeights(w("33.33", "33.33", "33.34"));
    expect(c.ok).toBe(true);
    expect(c.totalPct).toBe("100");
    expect(c.fractions).toEqual(["0.3333", "0.3333", "0.3334"]);
  });
  it("rejects 33.33 × 3 = 99.99", () => {
    const c = checkWeights(w("33.33", "33.33", "33.33"));
    expect(c.ok).toBe(false);
    expect(c.totalPct).toBe("99.99");
  });
  it("is exact where a float sum is not", () => {
    expect(0.1 + 0.2).not.toBe(0.3); // the float trap a Number sum would fall into
    expect(checkWeights(w("0.1", "0.2", "99.7")).ok).toBe(true);
    expect(checkWeights(w("100.0")).ok).toBe(true);
    expect(checkWeights(w("100.0000001")).ok).toBe(false);
  });
  it("rejects invalid, zero, empty and over-100 weights", () => {
    expect(checkWeights(w("50", "abc")).ok).toBe(false);
    expect(checkWeights(w("100", "0")).ok).toBe(false);
    expect(checkWeights(w("100", "")).ok).toBe(false);
    expect(checkWeights(w("150", "-50")).ok).toBe(false);
    expect(checkWeights([]).ok).toBe(false);
  });
});

async function addInstrument(name: string) {
  await userEvent.clear(screen.getByLabelText("Add an instrument"));
  await userEvent.type(screen.getByLabelText("Add an instrument"), "FIXTURE");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
  await userEvent.click(await screen.findByRole("button", { name: `Select ${name}` }));
}

describe("Simulator page", () => {
  it("blocks submit until the weights sum to exactly 100 %, then sends fraction strings with the exact field names", async () => {
    const calls = stubFetch((url) => (url.startsWith("/api/instruments") ? json(INSTRUMENTS) : json(SIMULATE)));
    renderAt("/simulate?id=mf:900001");
    const submit = screen.getByRole("button", { name: "Simulate" });
    expect(screen.getByTestId("weight-total")).toHaveTextContent("100 %");
    expect(submit).toBeEnabled();
    await addInstrument("FIXTURE 182-day T-bill");
    await addInstrument("FIXTURE Bank FD — 180 days");
    const [w0, w1, w2] = [0, 1, 2].map((i) => screen.getByLabelText(new RegExp(`^Weight for .*`, "i"), { selector: `#w-${i}` }));
    for (const input of [w0!, w1!, w2!]) {
      await userEvent.clear(input);
      await userEvent.type(input, "33.33");
    }
    expect(screen.getByTestId("weight-total")).toHaveTextContent("99.99 %");
    expect(screen.getByText("must be exactly 100 % to run")).toBeInTheDocument();
    expect(submit).toBeDisabled();
    await userEvent.click(submit);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await userEvent.clear(w2!);
    await userEvent.type(w2!, "33.34");
    expect(screen.getByTestId("weight-total")).toHaveTextContent("100 %");
    expect(submit).toBeEnabled();
    await userEvent.type(screen.getByLabelText("Amount in ₹ (optional)"), "600000.01");
    await userEvent.type(screen.getByLabelText("Withdrawal date (optional)"), "2027-04-15");
    await userEvent.click(submit);
    await screen.findByText("Portfolio band");
    const post = calls.filter((c) => c.method === "POST");
    expect(post).toHaveLength(1);
    expect(post[0]?.url).toBe("/api/simulate");
    expect(post[0]?.body).toEqual({
      allocations: [
        { instrument_id: "mf:900001", weight: "0.3333" },
        { instrument_id: "tbill:182d:2027-04-13", weight: "0.3333" },
        { instrument_id: "fd:fixture-bank:180d", weight: "0.3334" },
      ],
      amount: "600000.01",
      withdrawal_date: "2027-04-15",
    });
  });

  it("renders allocations, bands, the conservative portfolio sum, concentration, ladder, maturity and DICGC from the API", async () => {
    stubFetch((url) => (url.startsWith("/api/instruments") ? json(INSTRUMENTS) : json(SIMULATE)));
    renderAt("/simulate?id=mf:900001");
    await userEvent.click(screen.getByRole("button", { name: "Simulate" }));
    await screen.findByText("Portfolio band");
    expect(screen.getAllByRole("button", { name: /Allocated amount: ₹1,99,980\.00/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /Allocated amount: ₹2,00,040\.01/ })).toBeInTheDocument();
    expect(screen.getAllByText("33.33 %")).toHaveLength(2);
    expect(screen.getByText("Conservative sum, ignores diversification (q05)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Conservative sum, ignores diversification: ₹6,13,592\.53/ })).toBeInTheDocument();
    expect(screen.getByText(/Allocations sum to ₹6,00,000\.01 of ₹6,00,000\.01 — reconciles exactly\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Concentration \(HHI\): 0\.3333/ })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "cash within 1 day(s)" })).toBeInTheDocument();
    expect(screen.getAllByText(/Cash idle 2 days before withdrawal/)).toHaveLength(2);
    const dicgc = screen.getByRole("rowheader", { name: "FIXTURE Bank (bank)" }).closest("tr")!;
    expect(within(dicgc).getByRole("button", { name: /Insured at FIXTURE Bank: ₹2,06,945\.50/ })).toBeInTheDocument();
    expect(within(dicgc).getByRole("button", { name: /Uninsured at FIXTURE Bank: ₹0\.00/ })).toBeInTheDocument();
    expect(screen.getByText(/FIXTURE — not market data\./)).toBeInTheDocument();
  });

  it("highlights a maturity mismatch in words and shows the refused portfolio band as a refusal", async () => {
    stubFetch(() => json(SIMULATE_MISMATCH));
    renderAt("/simulate?id=mf:900001");
    await userEvent.click(screen.getByRole("button", { name: "Simulate" }));
    expect(await screen.findByText(/⚠ MATURITY MISMATCH — matures 90 days after your withdrawal date\./)).toBeInTheDocument();
    expect(screen.getByText(/Not shown: Not every holding could be evaluated: fd:fixture-bank:180d/)).toBeInTheDocument();
    expect(screen.queryByText("Conservative sum, ignores diversification (q05)")).not.toBeInTheDocument();
  });

  it("shows an error message rather than a result when the API refuses", async () => {
    stubFetch(() => json({ detail: { code: "ABSTAIN", message: "No tax rule set covers the analysis date; after-tax outcomes refused." } }, 409));
    renderAt("/simulate?id=mf:900001");
    await userEvent.click(screen.getByRole("button", { name: "Simulate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No tax rule set covers the analysis date; after-tax outcomes refused. (ABSTAIN)");
    expect(screen.queryByText("Portfolio band")).not.toBeInTheDocument();
  });

  it("starts empty with submit blocked when no instrument is chosen", () => {
    stubFetch(() => json({}));
    renderAt("/simulate");
    expect(screen.getByText("No holdings yet. Add instruments below.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Simulate" })).toBeDisabled();
  });
});
