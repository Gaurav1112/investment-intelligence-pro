import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { pageTitle, ROUTES, Shell } from "./App";
import { ProfileProvider } from "./lib/profile";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

function renderShell() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/data-health")
        return json({
          sources: [{ source_id: "amfi.navall", last_run: { status: "ok", finished_at: "2026-10-15T06:45:41+00:00", rows_ok: 1, rows_rejected: 0, error: null } }],
          runs: [], observation_counts: {}, tax_rules_loaded: true, tax_rules_coverage_to: null,
        });
      return json({ code: "NOT_FOUND" }, 404);
    }),
  );
  return render(
    <MemoryRouter>
      <ProfileProvider>
        <Shell>
          <p>page</p>
        </Shell>
      </ProfileProvider>
    </MemoryRouter>,
  );
}

describe("page titles and route focus (A11Y-3)", () => {
  it("pageTitle names every nav page and the link-only pages", () => {
    expect(pageTitle("/")).toBe("Today");
    expect(pageTitle("/overview")).toBe("Overview");
    expect(pageTitle("/discover")).toBe("Discovery");
    expect(pageTitle("/data-health")).toBe("Data health");
    expect(pageTitle("/settings")).toBe("Settings");
    expect(pageTitle("/i/mf:900001")).toBe("Instrument detail");
    expect(pageTitle("/evidence/42")).toBe("Evidence");
  });

  it("sets document.title per route and moves focus to the main landmark on navigation (not on first load)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ code: "NOT_FOUND" }, 404)),
    );
    render(
      <MemoryRouter initialEntries={["/discover"]}>
        <ProfileProvider>
          <Shell>
            <p>page</p>
          </Shell>
        </ProfileProvider>
      </MemoryRouter>,
    );
    expect(document.title).toBe("Discovery · Investment Intelligence Pro");
    expect(screen.getByRole("main")).not.toHaveFocus();
    await userEvent.click(screen.getByRole("link", { name: "Risk" }));
    expect(document.title).toBe("Risk · Investment Intelligence Pro");
    expect(screen.getByRole("main")).toHaveFocus();
  });
});

describe("App shell", () => {
  it("'/' is Today: the first nav link, and the brand links to it (C01)", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const first = nav.querySelector("a");
    expect(first).toHaveTextContent("Today");
    expect(first).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/overview");
  });

  it("routes '/' to the Today page and '/overview' to Overview", () => {
    expect(ROUTES.find((r) => r.path === "/")?.name).toBe("Today");
    expect(ROUTES.find((r) => r.path === "/overview")?.name).toBe("Overview");
  });

  it("has a skip link to the main landmark and labelled landmarks", () => {
    renderShell();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Not investment advice");
  });

  it("menu button toggles the navigation for small screens", async () => {
    renderShell();
    const btn = screen.getByRole("button", { name: /Menu/ });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(nav).toHaveAttribute("data-open", "false");
    await userEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(nav).toHaveAttribute("data-open", "true");
  });

  it("shows when the official NAV file was last fetched, linking to Data health", async () => {
    renderShell();
    const link = await screen.findByRole("link", { name: /AMFI NAVs fetched 15-Oct-2026 06:45 UTC/ });
    expect(link).toHaveAttribute("href", "/data-health");
  });
});
