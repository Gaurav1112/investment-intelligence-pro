import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { clearApiCache } from "../lib/api";
import type { RuleDetailResponse } from "../lib/types-signals";
import { DETAIL_ACCEPTED, DETAIL_SE } from "../test/signalsFixtures";
import RuleDetail from "./RuleDetail";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
function stubFetch(body: unknown, status = 200) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return json(body, status);
    }),
  );
  return calls;
}

const renderAt = (path = "/signals/S-E/1") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/signals/:ruleId/:version" element={<RuleDetail />} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => clearApiCache());
afterEach(() => vi.unstubAllGlobals());

const section = (name: RegExp) => within(screen.getByRole("region", { name }));

describe("RuleDetail", () => {
  it("fetches the rule once by id and version", async () => {
    const calls = stubFetch(DETAIL_SE);
    renderAt("/signals/S-E/1");
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(calls).toEqual(["/api/signals/S-E/1"]);
  });

  it("renders ABSTAIN with the failing gate in the header", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const status = section(/^Status$/);
    expect(status.getByText("ABSTAIN")).toBeInTheDocument();
    expect(status.getByText(/G5 Sample size/)).toBeInTheDocument();
    expect(status.getByText(/Pre-registered/)).toBeInTheDocument();
  });

  it("shows MinTRL next to the 80 %-power length, OOS periods and the earliest possible review", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const power = section(/How much evidence is needed/);
    expect(power.getByText("126.4 months")).toBeInTheDocument();
    expect(power.getByText("287.9 months")).toBeInTheDocument();
    expect(power.getByText("0 of 30 needed")).toBeInTheDocument();
    expect(power.getByText("Earliest possible review: 2037-04")).toBeInTheDocument();
    expect(power.getByText(/stats\.mintrl@1/)).toBeInTheDocument();
  });

  it("says 'not computed' rather than inventing power numbers", async () => {
    stubFetch({ ...DETAIL_SE, power: { ...DETAIL_SE.power, min_trl_months: null, power80_months: null, earliest_review: null, n_oos_periods: null } });
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const power = section(/How much evidence is needed/);
    expect(power.getAllByText("not computed")).toHaveLength(3);
    expect(power.getByText("Earliest possible review: not computed (no backtest run yet)")).toBeInTheDocument();
  });

  it("shows the post-publication tag and the trial count", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(screen.getByText("Post-publication out-of-sample")).toBeInTheDocument();
    expect(screen.getByText(/Fixture citation, 2001/)).toBeInTheDocument();
    expect(screen.getByText(/1 trial logged in family trend_timing/)).toBeInTheDocument();
  });

  it("shows expected excess only after the ×0.5 decay haircut", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const ev = section(/Expected excess/);
    expect(ev.getByText(/×0\.5 decay haircut/)).toBeInTheDocument();
    expect(ev.getByText(/^\+1\.00\s%\/yr$/)).toBeInTheDocument(); // after haircut
    expect(ev.getByText(/before the haircut: \+2\.00/)).toBeInTheDocument();
  });

  it("hides the expected excess when the haircut was not applied (fail closed)", async () => {
    stubFetch({ ...DETAIL_SE, expected_excess: { ...DETAIL_SE.expected_excess!, after_haircut: null } });
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const ev = section(/Expected excess/);
    expect(ev.getByText(/Not shown: the ×0\.5 decay haircut was not applied/)).toBeInTheDocument();
    expect(ev.queryByText(/2\.00/)).toBeNull();
  });

  it("shows the shadow record as recorded-only rows, never as an action", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const sh = section(/Shadow record/);
    expect(sh.getByText(/never an action/i)).toBeInTheDocument();
    expect(sh.getByText(/12 daily evaluations/)).toBeInTheDocument();
    expect(sh.getAllByRole("row")).toHaveLength(1 + DETAIL_SE.shadow.length);
    expect(sh.getByText("Entry condition met")).toBeInTheDocument();
    expect(sh.getByText("Unscorable: nav_missing")).toBeInTheDocument();
    expect(sh.getByText(/^Scored: −0\.31\s%$/)).toBeInTheDocument();
    expect(sh.getByText("Not yet due")).toBeInTheDocument();
  });

  it("does not show the latest condition for a rule that has not passed every gate", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    const status = section(/^Status$/);
    expect(status.queryByText(/condition met/i)).toBeNull();
  });

  it("uses neutral wording with no BUY/SELL anywhere by default, even for an accepted rule", async () => {
    stubFetch(DETAIL_ACCEPTED);
    const { container } = renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(section(/^Status$/).getByText("Entry condition met")).toBeInTheDocument();
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\bbuy\b/i);
    expect(text).not.toMatch(/\bsell\b/i);
  });

  it("shows a BUY badge only for an accepted rule after the owner opted in, never in the shadow record", async () => {
    const opted: RuleDetailResponse = { ...DETAIL_ACCEPTED, vocabulary: "buy_sell" };
    stubFetch(opted);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(section(/^Status$/).getByText("BUY")).toBeInTheDocument();
    expect(section(/Shadow record/).queryByText(/\b(BUY|SELL)\b/)).toBeNull();
  });

  it("keeps ABSTAIN for an opted-in rule that has not passed every gate", async () => {
    stubFetch({ ...DETAIL_SE, vocabulary: "buy_sell" });
    const { container } = renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(section(/^Status$/).getByText("ABSTAIN")).toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/\b(BUY|SELL)\b/);
  });

  it("renders the rule formula and its role names (no scheme codes)", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(screen.getByText("S_m = 1 if C_m > mean(C_{m-9..m}) else 0")).toBeInTheDocument();
    expect(screen.getByText("index_fund.broad_large.direct")).toBeInTheDocument();
  });

  it("shows the error state for an unknown rule", async () => {
    stubFetch({ code: "NOT_FOUND", message: "no such rule" }, 404);
    renderAt("/signals/S-Z/9");
    expect(await screen.findByRole("alert")).toHaveTextContent(/NOT_FOUND/);
  });

  it("carries the footer disclosure and a link back to the registry", async () => {
    stubFetch(DETAIL_SE);
    renderAt();
    await screen.findByRole("heading", { level: 1, name: /S-E v1/ });
    expect(screen.getByText(/Not investment advice/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All signals/ })).toHaveAttribute("href", "/signals");
  });
});
