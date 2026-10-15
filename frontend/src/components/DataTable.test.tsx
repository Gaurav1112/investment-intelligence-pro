import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { compareDecimal, DataTable } from "./DataTable";

describe("compareDecimal (exact, no floats)", () => {
  it.each([
    ["0.1", "0.2", -1],
    ["10.00", "9.99", 1],
    ["-1.5", "-1.25", -1],
    ["100534.00", "100534", 0],
    ["0.30000000000000004", "0.3", 1],
    ["99999999999999999.01", "99999999999999999.02", -1],
  ])("%s vs %s", (a, b, sign) => expect(Math.sign(compareDecimal(a, b))).toBe(sign));
});

type Row = { id: string; name: string; v: string | null };
const rows: Row[] = [
  { id: "b", name: "Beta", v: "10.5" },
  { id: "a", name: "Alpha", v: "9.75" },
  { id: "c", name: "Gamma", v: null },
];

describe("DataTable", () => {
  it("sorts decimal strings exactly, keeps missing values last, and exposes aria-sort", async () => {
    render(
      <DataTable
        rows={rows}
        caption="test"
        rowKey={(r) => r.id}
        columns={[
          { key: "name", header: "Name", render: (r) => r.name, sortValue: (r) => r.name },
          { key: "v", header: "Value", numeric: true, render: (r) => r.v ?? "—", sortValue: (r) => r.v },
        ]}
      />,
    );
    const btn = screen.getByRole("button", { name: /Value/ });
    await userEvent.click(btn);
    const names = () => within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => (r as HTMLTableRowElement).cells[0]?.textContent);
    expect(names()).toEqual(["Alpha", "Beta", "Gamma"]);
    expect(btn.closest("th")).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(btn);
    expect(names()).toEqual(["Beta", "Alpha", "Gamma"]);
  });
});
