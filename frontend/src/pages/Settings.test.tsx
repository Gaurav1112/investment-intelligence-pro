import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { PrivacyInventory } from "../lib/types";
import Settings, { ERASE_PHRASE } from "./Settings";

// Shapes follow backend/src/iip/services/portfolio.py inventory(), make_backup() and erase().
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

const INV: PrivacyInventory = {
  user_data: {
    tables: { transactions: 1234, portfolios: 2, watchlist: 1, alerts: 3, runs: 0, audit_events: 9, settings: 2, profiles: 1 },
    pending_import_previews: 1,
  },
  public_market_data_kept_on_erase: {
    tables: { sources: 6, ingestion_runs: 4, issuers: 0, instruments: 10, mf_schemes: 8, bond_terms: 1, deposit_terms: 1, observations: 120000 },
  },
  backups: { count: 2, note: "backups may contain user data" },
  note: "Counts only; no amounts or names.",
};

function realistic(url: string, method: string): Response {
  if (url === "/api/privacy/inventory") return json(INV);
  if (url === "/api/backup")
    return json({ path: "/home/u/.iip/backups/iip-20261015T060000Z-v3.sqlite3", integrity: "ok", bytes: 1048576, sha256: "d".repeat(64), schema_version: 3 });
  if (url === "/api/privacy/erase" && method === "POST")
    return json({
      status: "erased",
      deleted_rows: INV.user_data.tables,
      backups_deleted: 0,
      backups_remaining: 2,
      kept: "public market data (instruments, observations, sources, ingestion runs) and the schema",
    });
  return json({ code: "NOT_FOUND" }, 404);
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <Settings />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Settings & privacy", () => {
  it("shows the inventory as counts only, export links, profile link and the LLM note", async () => {
    stubFetch(realistic);
    renderPage();
    expect(await screen.findByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("1,20,000")).toBeInTheDocument();
    expect(screen.getByText(/Backups on disk: 2/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit objectives" })).toHaveAttribute("href", "/onboarding");
    expect(screen.getByRole("link", { name: "Export everything (JSON)" })).toHaveAttribute("href", "/api/privacy/export");
    expect(screen.getByRole("link", { name: "Export transactions (CSV)" })).toHaveAttribute("href", "/api/privacy/export.csv");
    // The optional AI wording section replaces the old "not part of version 1" note; with no status endpoint it degrades.
    expect(await screen.findByText(/AI wording settings are unavailable/)).toBeInTheDocument();
  });

  it("includes the optional AI wording section, off by default", async () => {
    stubFetch((url, method) =>
      url === "/api/llm/status"
        ? json({ mode: "off", base_url: "", model: "", api_key_env: "", config_source: "env", api_key_present: false, provider: null,
            privacy_note: "", config_error: null, last_error: null, rejected_count: 0, calls: 0, cache_hits: 0,
            default_local_url: "http://127.0.0.1:11434/v1", providers: [], probe: null })
        : realistic(url, method),
    );
    renderPage();
    expect(await screen.findByRole("heading", { name: "Optional AI wording" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Off — deterministic wording only/ })).toBeChecked();
  });

  it("shows an error state for the inventory", async () => {
    stubFetch(() => json({ code: "INTERNAL_ERROR" }, 500));
    renderPage();
    expect(await screen.findByText(/The inventory could not be loaded/)).toBeInTheDocument();
  });

  it("backs up and shows the path and integrity", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByText("1,234");
    await userEvent.click(screen.getByRole("button", { name: "Back up now" }));
    expect(await screen.findByText("Backup written. Integrity check: ok.")).toBeInTheDocument();
    expect(screen.getByText("/home/u/.iip/backups/iip-20261015T060000Z-v3.sqlite3")).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/api/backup")!.method).toBe("POST");
  });

  it("requires the exact phrase before erasing, and keeps backups unless opted in", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByText("1,234");
    const btn = screen.getByRole("button", { name: "Erase all my data" });
    const input = screen.getByLabelText(/to confirm/);
    expect(btn).toBeDisabled();
    for (const wrong of ["erase all my data", "ERASE ALL MY DATA ", "ERASE  ALL MY DATA", "ERASE ALL"]) {
      fireEvent.change(input, { target: { value: wrong } });
      expect(btn).toBeDisabled();
    }
    fireEvent.submit(btn.closest("form")!);
    expect(calls.some((c) => c.url === "/api/privacy/erase")).toBe(false);
    expect(screen.getByText(/Backups are not erased/)).toBeInTheDocument();

    fireEvent.change(input, { target: { value: ERASE_PHRASE } });
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/privacy/erase")).toBe(true));
    expect(calls.find((c) => c.url === "/api/privacy/erase")!.body).toEqual({ confirm: "ERASE ALL MY DATA", delete_backups: false });
    expect(await screen.findByText(/Erased 1,252 row\(s\) of your data/)).toBeInTheDocument();
    expect(screen.getByText(/backups remaining: 2 \(these still contain your data\)/)).toBeInTheDocument();
  });

  it("sends delete_backups only when ticked", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByText("1,234");
    await userEvent.click(screen.getByRole("checkbox", { name: "Also delete every backup file" }));
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: ERASE_PHRASE } });
    await userEvent.click(screen.getByRole("button", { name: "Erase all my data" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/privacy/erase")).toBe(true));
    expect(calls.find((c) => c.url === "/api/privacy/erase")!.body).toEqual({ confirm: ERASE_PHRASE, delete_backups: true });
  });
});
