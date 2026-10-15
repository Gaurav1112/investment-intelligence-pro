import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { BondList, BondListItem } from "../lib/types-bonds";
import FixedIncome, { isinProblem } from "./FixedIncome";

// FIXTURE values only: synthetic ISINs (valid check digits) and https://fixture.invalid citations — not market data.
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

const GSEC: BondListItem = {
  instrument_id: "gsec:INFIXGSEC016",
  kind: "gsec",
  name: "7.1 % Government of India GS 2027-04-15 (INFIXGSEC016)",
  isin: "INFIXGSEC016",
  origin: "manual",
  fixture: false,
  quote: { kind: "clean_price", value: "99.80", convention: "clean price per ₹100, 30E/360", quote_date: "2026-10-14", age_days: 1, freshness: "MANUAL", citation_url: "https://fixture.invalid/gsec", source_id: "bond.quote" },
  quote_problem: null,
  terms: { issuer: "Government of India", coupon_rate: "0.071", frequency: 2, issue_date: "2022-04-15", maturity: "2027-04-15", face_value: "100", listed: true, secured: null, record_date_days: 1, calls: [], transaction_spread: null, day_count: "30E/360" },
  rating: null,
};
const CORP: BondListItem = {
  instrument_id: "corp_bond:INFIXCORP018",
  kind: "corp_bond",
  name: "FIXTURE Finance Ltd 9 % 2029-10-15 (INFIXCORP018)",
  isin: "INFIXCORP018",
  origin: "manual",
  fixture: false,
  quote: { kind: "ytm", value: "0.0812", convention: "ytm; compounding=annual", quote_date: "2026-10-01", age_days: 14, freshness: "STALE", citation_url: "https://fixture.invalid/corp", source_id: "bond.quote" },
  quote_problem: null,
  terms: { issuer: "FIXTURE Finance Ltd", coupon_rate: "0.09", frequency: 1, issue_date: "2024-10-15", maturity: "2029-10-15", face_value: "10000", listed: true, secured: true, record_date_days: 15, calls: [{ call_date: "2027-10-15", call_price: "100" }], transaction_spread: "0.001", day_count: "ACT/ACT-SEBI" },
  rating: { rating: "AA+", agency: "ICRA", rating_date: "2025-09-01", age_days: 409, stale: true, citation_url: "https://fixture.invalid/rating" },
};
const SDL_FIXTURE: BondListItem = { ...GSEC, instrument_id: "sdl:INFIXSDL0013", kind: "sdl", name: "FIXTURE SDL", origin: "fixture", fixture: true };
const LIST: BondList = { as_of: "2026-10-15", quote_stale_after_days: 7, rating_stale_after_days: 365, items: [GSEC, CORP, SDL_FIXTURE] };
const EMPTY: BondList = { ...LIST, items: [] };

function routes(list: BondList, post?: (url: string, body: unknown) => Response) {
  return (url: string, method: string, body: unknown): Response => {
    if (method === "POST" && post) return post(url, body);
    if (method === "POST") return json({ instrument_id: "x" });
    if (method === "DELETE") return json({ status: "deleted" });
    if (url === "/api/bonds") return json(list);
    if (url.startsWith("/api/instruments?kind=")) return json({ items: [], truncated: false });
    return json({ detail: "not found" }, 404);
  };
}

async function openBonds() {
  render(
    <MemoryRouter>
      <FixedIncome />
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("tab", { name: "G-secs & bonds" }));
}

const set = (id: string, value: string) => fireEvent.change(document.getElementById(id)!, { target: { value } });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-15T06:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ISIN check digit", () => {
  it("accepts valid ISINs and explains invalid ones", () => {
    expect(isinProblem("INFIXGSEC016")).toBeNull();
    expect(isinProblem("infixcorp018")).toBeNull(); // normalised to upper case
    expect(isinProblem("INFIXGSEC017")).toMatch(/check digit/);
    expect(isinProblem("IN123")).toMatch(/12-character/);
  });
});

describe("G-secs & bonds list", () => {
  it("shows quote date with freshness, rating with its date, and delete only for manual entries", async () => {
    stubFetch(routes(LIST));
    await openBonds();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    const [g, c, s] = rows as [HTMLElement, HTMLElement, HTMLElement];
    expect(within(g).getByText("99.8000 per ₹100")).toBeInTheDocument();
    expect(within(g).getByText(/1 day old/)).toBeInTheDocument();
    expect(within(g).getByText(/Sovereign/)).toBeInTheDocument();
    expect(within(c).getByText("8.12 % YTM")).toBeInTheDocument();
    expect(within(c).getByText(/yield, annual/)).toBeInTheDocument();
    expect(within(c).getByText(/older than 7 days: excluded/)).toBeInTheDocument();
    expect(within(c).getByText("AA+")).toBeInTheDocument();
    expect(within(c).getByText(/older than 365 days: excluded/)).toBeInTheDocument();
    expect(within(c).getByText(/callable \(1\)/)).toBeInTheDocument();
    expect(within(g).getByRole("button", { name: `Delete ${GSEC.name}` })).toBeInTheDocument();
    expect(within(s).queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
    expect(within(s).getByText(/State government/)).toBeInTheDocument();
    expect(screen.getByText(/FIXTURE data present/)).toBeInTheDocument();
  });

  it("deletes a manual bond after confirmation", async () => {
    const calls = stubFetch(routes(LIST));
    await openBonds();
    await userEvent.click(await screen.findByRole("button", { name: `Delete ${GSEC.name}` }));
    await userEvent.click(screen.getByRole("button", { name: `Confirm delete ${GSEC.name}` }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(calls.find((c) => c.method === "DELETE")!.url).toBe(`/api/instruments/${encodeURIComponent(GSEC.instrument_id)}`);
    expect(await screen.findByText(`Deleted ${GSEC.name}.`)).toBeInTheDocument();
  });
});

function fillGsec() {
  set("gs-isin", "INFIXGSEC016");
  set("gs-coupon", "7.10");
  set("gs-issue", "2022-04-15");
  set("gs-maturity", "2027-04-15");
  set("gs-price", "99.80");
  set("gs-qdate", "2026-10-14");
  set("gs-url", "https://fixture.invalid/gsec");
  set("gs-asof", "2026-10-14");
}

describe("G-sec / SDL form", () => {
  it("refuses to submit without the required fields and the citation", async () => {
    const calls = stubFetch(routes(EMPTY));
    await openBonds();
    const form = screen.getByRole("form", { name: "Add a G-sec or SDL" });
    await userEvent.click(within(form).getByRole("button", { name: "Save G-sec / SDL" }));
    expect(within(form).getByText(/12-character ISIN/)).toBeInTheDocument();
    expect(within(form).getByText(/clean price per ₹100 face/)).toBeInTheDocument();
    expect(within(form).getByText(/https:\/\/ address/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("posts exact field names with decimal strings and exactly one quote", async () => {
    const calls = stubFetch(routes(EMPTY, () => json({ instrument_id: "gsec:INFIXGSEC016" })));
    await openBonds();
    fillGsec();
    const form = screen.getByRole("form", { name: "Add a G-sec or SDL" });
    await userEvent.click(within(form).getByRole("button", { name: "Save G-sec / SDL" }));
    expect(await within(form).findByText("Saved as gsec:INFIXGSEC016.")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/instruments/gsec");
    expect(post.body).toEqual({
      kind: "gsec",
      frequency: 2,
      issuer: "Government of India",
      isin: "INFIXGSEC016",
      coupon_rate: "0.071",
      issue_date: "2022-04-15",
      maturity: "2027-04-15",
      face_value: "100",
      clean_price: "99.80",
      ytm: null,
      quote_date: "2026-10-14",
      transaction_spread: null,
      citation: { url: "https://fixture.invalid/gsec", as_of: "2026-10-14" },
    });
  });

  it("sends an SDL yield as a fraction", async () => {
    const calls = stubFetch(routes(EMPTY));
    await openBonds();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "sdl" } });
    set("gs-issuer", "State of Fixtureland");
    fillGsec();
    await userEvent.click(screen.getAllByRole("radio", { name: "Yield to maturity" })[0]!);
    set("gs-ytm", "7.12");
    set("gs-spread", "0.25");
    await userEvent.click(screen.getByRole("button", { name: "Save G-sec / SDL" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const body = calls.find((c) => c.method === "POST")!.body as Record<string, unknown>;
    expect(body["kind"]).toBe("sdl");
    expect(body["ytm"]).toBe("0.0712");
    expect(body["clean_price"]).toBeNull();
    expect(body["transaction_spread"]).toBe("0.0025");
  });

  it("shows server 422 errors inline under the field", async () => {
    const reject = () =>
      json({ detail: [{ loc: ["body", "isin"], msg: "Value error, ISIN_BAD_CHECKSUM: enter the 12-character ISIN", type: "value_error" }] }, 422);
    stubFetch(routes(EMPTY, reject));
    await openBonds();
    fillGsec();
    const form = screen.getByRole("form", { name: "Add a G-sec or SDL" });
    await userEvent.click(within(form).getByRole("button", { name: "Save G-sec / SDL" }));
    expect(await within(form).findByText(/ISIN_BAD_CHECKSUM/)).toBeInTheDocument();
    expect(document.getElementById("gs-isin")).toHaveAttribute("aria-invalid", "true");
    expect(within(form).getByText(/the server rejected 1 field/)).toBeInTheDocument();
  });
});

function fillCorp() {
  set("cb-issuer", "FIXTURE Finance Ltd");
  set("cb-isin", "INFIXCORP018");
  set("cb-coupon", "9");
  set("cb-issue", "2024-10-15");
  set("cb-maturity", "2029-10-15");
  set("cb-face", "10000");
  set("cb-qdate", "2026-10-14");
  set("cb-rating", "AAA");
  set("cb-agency", "CRISIL");
  set("cb-rdate", "2026-06-01");
  set("cb-rating-cite-url", "https://fixture.invalid/rating");
  set("cb-rating-cite-asof", "2026-06-01");
  set("cb-secured", "yes");
  set("cb-record", "15");
  set("cb-url", "https://fixture.invalid/corp");
  set("cb-asof", "2026-10-14");
}

describe("corporate bond form", () => {
  it("requires the rating, its citation and the yield compounding", async () => {
    const calls = stubFetch(routes(EMPTY));
    await openBonds();
    const form = screen.getByRole("form", { name: "Add a corporate bond" });
    await userEvent.click(within(form).getByRole("radio", { name: "Yield to maturity" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save corporate bond" }));
    expect(within(form).getByText(/Choose the rating from/)).toBeInTheDocument();
    expect(within(form).getByText(/Choose the rating agency/)).toBeInTheDocument();
    expect(within(form).getByText(/compounded/)).toBeInTheDocument();
    expect(within(form).getAllByText(/https:\/\/ address/)).toHaveLength(2); // bond page + rating rationale
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("posts the full corporate body with a call schedule", async () => {
    const calls = stubFetch(routes(EMPTY));
    await openBonds();
    fillCorp();
    const form = screen.getByRole("form", { name: "Add a corporate bond" });
    await userEvent.click(within(form).getByRole("radio", { name: "Yield to maturity" }));
    set("cb-ytm", "8.12");
    set("cb-comp", "annual");
    await userEvent.click(within(form).getByRole("button", { name: "Add a call date" }));
    set("cb-call-0-date", "2027-10-15");
    set("cb-call-0-price", "100");
    await userEvent.click(within(form).getByRole("button", { name: "Save corporate bond" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/instruments/corp-bond");
    expect(post.body).toEqual({
      issuer: "FIXTURE Finance Ltd",
      isin: "INFIXCORP018",
      coupon_rate: "0.09",
      issue_date: "2024-10-15",
      maturity: "2029-10-15",
      face_value: "10000",
      clean_price: null,
      ytm: "0.0812",
      quote_date: "2026-10-14",
      transaction_spread: null,
      citation: { url: "https://fixture.invalid/corp", as_of: "2026-10-14" },
      frequency: 1,
      ytm_compounding: "annual",
      rating: "AAA",
      rating_agency: "CRISIL",
      rating_date: "2026-06-01",
      rating_citation: { url: "https://fixture.invalid/rating", as_of: "2026-06-01" },
      listed: true,
      secured: true,
      record_date_days: 15,
      call_schedule: [{ call_date: "2027-10-15", call_price: "100" }],
    });
  });

  it("maps a server error on the rating citation to the rating citation field", async () => {
    const reject = () => json({ detail: [{ loc: ["body", "rating_citation", "url"], msg: "String should match pattern", type: "string_pattern_mismatch" }] }, 422);
    stubFetch(routes(EMPTY, reject));
    await openBonds();
    fillCorp();
    set("cb-price", "102.50");
    const form = screen.getByRole("form", { name: "Add a corporate bond" });
    await userEvent.click(within(form).getByRole("button", { name: "Save corporate bond" }));
    expect(await within(form).findByText("String should match pattern")).toBeInTheDocument();
    expect(document.getElementById("cb-rating-cite-url")).toHaveAttribute("aria-invalid", "true");
  });
});
