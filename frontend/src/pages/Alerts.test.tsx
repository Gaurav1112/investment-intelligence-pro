import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { AlertEvaluation, AlertRow, AlertRules } from "../lib/types";
import Alerts from "./Alerts";

// Messages are the exact templates of backend/src/iip/services/alerts.py (`Your rule “…” triggered: …`).
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

const BANNED = ["best", "guaranteed", "risk-free", "you should", "recommend", "buy now", "sell now"];

const STALE_ALERT: AlertRow = {
  alert_id: "al_0123456789abcdef0123", kind: "stale_data", severity: "warning", subject_id: "mf:990003",
  message: "Your rule “stale data for held or watched instruments” triggered: the latest NAV for TEST Debt Fund C (held) is dated 2026-09-01 and is STALE; values depending on it are excluded until fresh data is stored.",
  source_id: "fixture.nav", observation_ref: "7", created_at: "2026-10-15T06:00:00+00:00", dedupe_key: "stale:mf:990003:2026-09-01", acknowledged_at: null,
};
const TAX_ALERT: AlertRow = {
  alert_id: "al_aaaaaaaaaaaaaaaaaaaa", kind: "tax_rules", severity: "critical", subject_id: null,
  message: "Your rule “tax rule set coverage ending within 90 days” triggered: the loaded tax rule set covers transfers up to 2026-03-31 and has ended; analyses for later dates abstain until the rules are updated.",
  source_id: "rules.tax", observation_ref: "2026-03-31", created_at: "2026-10-14T06:00:00+00:00", dedupe_key: "tax-coverage:2026-03-31:90", acknowledged_at: "2026-10-14T07:00:00+00:00",
};
const MATURITY_ALERT: AlertRow = {
  alert_id: "al_bbbbbbbbbbbbbbbbbbbb", kind: "maturity", severity: "info", subject_id: "fd:test-bank:180d",
  message: "Your rule “maturity within 30 days” triggered: TEST Bank FD — 180 days in portfolio “Core” matures in 22 days (2026-11-06, as of 2026-10-15).",
  source_id: "deposit_terms tenure + your purchase date", observation_ref: "2026-11-06", created_at: "2026-10-15T06:00:00+00:00", dedupe_key: "maturity:pf:fd:2026-11-06", acknowledged_at: null,
};
const RULES: AlertRules = {
  stale_data: true, maturity_within_days: 30, concentration_hhi_above: "0.25", decline_since_added_beyond: "0.10",
  tax_coverage_within_days: 90, ingestion_failed_lookback_days: 14,
};
const EVAL: AlertEvaluation = {
  evaluated_at: "2026-10-15T06:00:00+00:00", rules: RULES, triggered: 3, created: [STALE_ALERT], already_present: 2, skipped_portfolios: [], delivery: "local only",
};

function realistic(url: string, method: string, body: unknown): Response {
  if (url.startsWith("/api/alerts?")) return json({ items: [STALE_ALERT, MATURITY_ALERT, TAX_ALERT] });
  if (url === "/api/alerts/rules" && method === "GET") return json(RULES);
  if (url === "/api/alerts/rules" && method === "PUT") return json(body);
  if (url === "/api/alerts/evaluate") return json(EVAL);
  if (url.endsWith("/ack")) return json({ ...STALE_ALERT, acknowledged_at: "2026-10-15T06:05:00+00:00" });
  return json({ code: "NOT_FOUND", message: "not found" }, 404);
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <Alerts />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Alerts", () => {
  it("lists alerts with severity word + glyph, source, UTC timestamp and evidence link", async () => {
    stubFetch(realistic);
    renderPage();
    expect(await screen.findByText(/the latest NAV for TEST Debt Fund C/)).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Info")).toBeInTheDocument();
    expect(screen.getByText("⚠")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Source: fixture.nav")).toBeInTheDocument();
    expect(screen.getAllByText("raised 15-Oct-2026 06:00 UTC").length).toBe(2);
    expect(screen.getByRole("link", { name: "Evidence #7" })).toHaveAttribute("href", "/evidence/7");
    expect(screen.getByText("Reference: 2026-11-06")).toBeInTheDocument();
    expect(screen.getByText("Acknowledged 14-Oct-2026 07:00 UTC")).toBeInTheDocument();
  });

  it("uses rule-triggered wording and no banned phrase anywhere on the page", async () => {
    stubFetch(realistic);
    renderPage();
    await screen.findByText(/the latest NAV for TEST Debt Fund C/);
    await screen.findByRole("button", { name: "Save rules" });
    for (const m of [STALE_ALERT, MATURITY_ALERT, TAX_ALERT]) expect(m.message.startsWith("Your rule “")).toBe(true);
    const text = document.body.textContent!.toLowerCase();
    for (const b of BANNED) expect(text).not.toContain(b);
  });

  it("evaluates rules now and announces the outcome", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByText(/the latest NAV for TEST Debt Fund C/);
    await userEvent.click(screen.getByRole("button", { name: "Evaluate rules now" }));
    const st = await screen.findByText(/Rules evaluated at 15-Oct-2026 06:00 UTC: 3 condition\(s\) met, 1 new alert\(s\), 2 already listed. Delivery: local only./);
    expect(st).toHaveAttribute("role", "status");
    expect(calls.find((c) => c.url === "/api/alerts/evaluate")!.method).toBe("POST");
  });

  it("acknowledges an alert", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByText(/the latest NAV for TEST Debt Fund C/);
    await userEvent.click(screen.getAllByRole("button", { name: "Acknowledge" })[0]!);
    await waitFor(() => expect(calls.some((c) => c.url === `/api/alerts/${STALE_ALERT.alert_id}/ack`)).toBe(true));
    expect(await screen.findByText("Alert acknowledged.")).toBeInTheDocument();
  });

  it("shows empty and error states", async () => {
    stubFetch((url, method, body) => (url.startsWith("/api/alerts?") ? json({ items: [] }) : realistic(url, method, body)));
    const { unmount } = renderPage();
    expect(await screen.findByText("No alerts yet")).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();
    stubFetch((url, method, body) => (url.startsWith("/api/alerts?") ? json({ code: "INTERNAL_ERROR" }, 500) : realistic(url, method, body)));
    renderPage();
    expect(await screen.findByText(/Alerts could not be loaded/)).toBeInTheDocument();
  });

  it("saves rules with thresholds as decimal strings and null for disabled rules", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByRole("button", { name: "Save rules" });
    expect(screen.getByLabelText(/Decline since added beyond — threshold/)).toHaveValue("10");
    fireEvent.change(screen.getByLabelText(/Concentration \(HHI\) above — threshold/), { target: { value: "0.3" } });
    fireEvent.change(screen.getByLabelText(/Decline since added beyond — threshold/), { target: { value: "12.5" } });
    await userEvent.click(screen.getByRole("checkbox", { name: "Failed data ingestion in the last" }));
    await userEvent.click(screen.getByRole("button", { name: "Save rules" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
      stale_data: true, maturity_within_days: 30, concentration_hhi_above: "0.3", decline_since_added_beyond: "0.125",
      tax_coverage_within_days: 90, ingestion_failed_lookback_days: null,
    });
    expect(await screen.findByText(/Rules saved/)).toBeInTheDocument();
  });

  it("refuses an out-of-range HHI locally", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByRole("button", { name: "Save rules" });
    fireEvent.change(screen.getByLabelText(/Concentration \(HHI\) above — threshold/), { target: { value: "1.5" } });
    await userEvent.click(screen.getByRole("button", { name: "Save rules" }));
    expect(screen.getByText(/Enter a decimal between 0 and 1/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});
