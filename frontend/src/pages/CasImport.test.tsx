import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CasPreview } from "../lib/types-cas";
import { CAS_PRIVACY_TEXT, CasImport } from "./CasImport";

// Shapes follow backend/src/iip/services/cas.py and the SYNTHETIC statement in backend/tests/services/cas_synthetic.py
// (fictional ISINs with the non-existent issuer prefix INFZZ; TEST instruments).

type Call = { url: string; method: string; body: unknown; headers: Record<string, string> };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

function stubFetch(handler: (url: string, method: string) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const raw = init?.body;
      calls.push({ url, method, body: typeof raw === "string" ? JSON.parse(raw) : raw, headers: (init?.headers ?? {}) as Record<string, string> });
      return handler(url, method);
    }),
  );
  return calls;
}

const SHA = "a".repeat(64);
const SECRET = "ABCDE1234F01011990";

function preview(over: Partial<CasPreview> = {}): CasPreview {
  return {
    batch_id: "imp_cas1", status: "previewed", applied: false, kind: "cas_pdf", label: "CAS statement (PDF)", file_sha256: SHA,
    issuer: "CAMS", statement_period: { from: "01-Jan-2024", to: "31-Mar-2025" },
    schemes: [
      { scheme: 1, isin: "INFZZ0001A01", isin_problem: null, rta: "CAMS", instrument_id: "mf:990001", instrument_name: "TEST Liquid Fund A",
        match: "EXACT_ISIN", segregated_portfolio: false, transactions_in_statement: 3 },
      { scheme: 2, isin: "INFZZ0003C04", isin_problem: null, rta: "CAMS", instrument_id: null, instrument_name: null,
        match: "UNKNOWN_ISIN", segregated_portfolio: false, transactions_in_statement: 1 },
    ],
    will_store: [
      { row: 1, scheme: 1, cas_type: "PURCHASE_SIP", txn_date: "2024-01-10", instrument_id: "mf:990001", instrument_name: "TEST Liquid Fund A",
        isin: "INFZZ0001A01", txn_type: "buy", units: "100.000", amount: "1000.00", nav: "10.0000", flags: [] },
      { row: 3, scheme: 1, cas_type: "DIVIDEND_PAYOUT", txn_date: "2024-06-28", instrument_id: "mf:990001", instrument_name: "TEST Liquid Fund A",
        isin: "INFZZ0001A01", txn_type: "dividend", units: null, amount: "25.00", nav: null, flags: [] },
    ],
    rejected: [{ row: 4, scheme: 2, cas_type: "PURCHASE", txn_date: "2024-01-05", reason: "UNKNOWN_ISIN" }],
    ignored: [{ row: 2, scheme: 1, cas_type: "STAMP_DUTY_TAX", txn_date: "2024-01-10", reason: "STAMP_DUTY_NOT_MODELLED" }],
    reconciliation: [
      { scheme: 1, isin: "INFZZ0001A01", instrument_id: "mf:990001", cas_opening_units: "0", cas_closing_units: "100", imported_net_units: "100.000",
        difference: "0.000", status: "OK", causes: [] },
      { scheme: 2, isin: "INFZZ0003C04", instrument_id: null, cas_opening_units: "0", cas_closing_units: "50", imported_net_units: "0",
        difference: "50", status: "UNMATCHED", causes: ["SCHEME_UNMATCHED"] },
    ],
    reconciliation_ok: false,
    blocking: [],
    warnings: ["Stamp duty, STT and TDS rows are not stored."],
    already_applied: false,
    confirm_with: { sha256: SHA, accept_reconciliation_mismatches: true },
    privacy: "The PDF and its password were used in memory for this preview only and were not stored.",
    note: "Nothing has been stored yet. Confirm with the file's SHA-256 to apply exactly the rows listed.",
    engine_version: "cas_import@1.0.0",
    ...over,
  };
}

const APPLIED = {
  batch_id: "imp_cas1", status: "applied", applied: true, portfolio_id: "pf_a1", transactions_created: 2, rows_rejected: 1, rows_ignored: 1,
  reconciliation_mismatches_accepted: 1, applied_at: "2026-10-15T06:00:00+00:00",
};

function renderIt(onApplied = vi.fn()) {
  render(<CasImport portfolioId="pf_a1" natureTag={<span>ACTUAL</span>} onApplied={onApplied} />);
  return onApplied;
}

async function previewIt() {
  await userEvent.upload(screen.getByLabelText("CAS statement (.pdf)"), new File(["%PDF-1.4"], "cas.pdf", { type: "application/pdf" }));
  await userEvent.type(screen.getByLabelText("PDF password"), SECRET);
  await userEvent.click(screen.getByRole("button", { name: "Preview CAS import" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("CAS import", () => {
  it("says the password and PDF are not stored, with a non-autocompleting password input", () => {
    renderIt();
    expect(screen.getByText(CAS_PRIVACY_TEXT)).toBeInTheDocument();
    expect(CAS_PRIVACY_TEXT).toMatch(/not stored/);
    const pw = screen.getByLabelText("PDF password");
    expect(pw).toHaveAttribute("type", "password");
    expect(pw).toHaveAttribute("autocomplete", "off");
    expect(screen.getByRole("heading", { name: "Import CAS statement (PDF)" })).toBeInTheDocument();
  });

  it("previews (password sent once, then cleared), shows reconciliation, and applies only after acknowledgement", async () => {
    const calls = stubFetch((url) => {
      if (url === "/api/holdings/import-cas") return json(preview());
      if (url === "/api/holdings/import-cas/imp_cas1/apply") return json(APPLIED);
      return json({ code: "UNEXPECTED" }, 500);
    });
    const onApplied = renderIt();
    await previewIt();

    const up = calls.find((c) => c.url === "/api/holdings/import-cas")!;
    expect(up.method).toBe("POST");
    const form = up.body as FormData;
    expect(form.get("password")).toBe(SECRET);
    expect(form.get("portfolio_id")).toBe("pf_a1");
    expect((form.get("file") as File).name).toBe("cas.pdf");
    expect(Object.keys(up.headers).map((h) => h.toLowerCase())).not.toContain("content-type");
    expect(screen.getByLabelText("PDF password")).toHaveValue(""); // not kept in the form after sending

    expect(await screen.findByText(/Preview of CAMS statement 01-Jan-2024 to 31-Mar-2025 — nothing stored yet/)).toBeInTheDocument();
    const stored = screen.getByRole("table", { name: "CAS rows that will be stored" });
    expect(within(stored).getByText("dividend (IDCW payout)")).toBeInTheDocument();
    expect(within(stored).getByText("₹1,000.00")).toBeInTheDocument();
    const recon = screen.getByRole("table", { name: "Reconciliation per scheme" });
    expect(within(recon).getByText("UNMATCHED")).toBeInTheDocument();
    expect(within(recon).getByText(/ISIN is not in the local store/)).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Rejected CAS rows" })).getByText(/unmatched: no stored instrument has this ISIN/)).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Ignored CAS rows" })).getByText(/stamp duty is not stored/)).toBeInTheDocument();
    expect(screen.getByText(/1 scheme\(s\) do not reconcile/)).toHaveAttribute("role", "alert");

    const confirm = screen.getByRole("button", { name: "Confirm and store 2 row(s)" });
    expect(confirm).toBeDisabled(); // a mismatch must be acknowledged first
    await userEvent.click(screen.getByLabelText(/I have reviewed the 1 reconciliation mismatch/));
    expect(confirm).toBeEnabled();
    expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(false);
    await userEvent.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/apply"))!.body).toEqual({ sha256: SHA, accept_reconciliation_mismatches: true });
    expect(await screen.findByText(/CAS import applied: 2 transaction\(s\) stored/)).toHaveAttribute("role", "status");
    expect(onApplied).toHaveBeenCalledWith(expect.stringMatching(/1 reconciliation mismatch\(es\) were accepted by you/));
    expect(JSON.stringify(calls.filter((c) => c.url.endsWith("/apply")).map((c) => c.body))).not.toContain(SECRET);
  });

  it("blocks apply when the statement would oversell", async () => {
    stubFetch(() =>
      json(preview({ reconciliation_ok: true, reconciliation: [], blocking: [{ code: "OVERSELL", instrument_id: "mf:990001", message: "sell of 80 units exceeds the 50 units held" }] })),
    );
    renderIt();
    await previewIt();
    expect(await screen.findByText(/A sale in this statement exceeds the units held: sell of 80 units/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and store 2 row(s)" })).toBeDisabled();
  });

  it("never claims success unless the API says applied: true", async () => {
    stubFetch((url) =>
      url.endsWith("/apply") ? json({ batch_id: "imp_cas1", status: "previewed", applied: false }) : json(preview({ reconciliation: [], reconciliation_ok: true })),
    );
    renderIt();
    await previewIt();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm and store 2 row(s)" }));
    expect(await screen.findByText(/did not confirm that the import was applied/)).toHaveAttribute("role", "alert");
    expect(screen.queryByText(/CAS import applied/)).toBeNull();
  });

  it("shows a refusal (wrong password) and stores nothing", async () => {
    const calls = stubFetch(() => json({ code: "WRONG_PASSWORD", message: "the password did not open this PDF; nothing was stored" }, 422));
    renderIt();
    await previewIt();
    expect(await screen.findByText(/The statement was refused; nothing was stored. the password did not open this PDF/)).toHaveAttribute("role", "alert");
    expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(false);
    expect(screen.getByLabelText("PDF password")).toHaveValue("");
  });

  it("asks for a file before sending anything", async () => {
    const calls = stubFetch(() => json({}));
    renderIt();
    await userEvent.click(screen.getByRole("button", { name: "Preview CAS import" }));
    expect(await screen.findByText("Choose your CAS PDF first.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });
});
