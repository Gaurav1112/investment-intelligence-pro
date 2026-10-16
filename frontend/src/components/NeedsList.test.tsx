import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { lossLimitNeed, num, taxSlabNeed } from "../test/todayFixtures";
import { NeedsList } from "./NeedsList";

describe("NeedsList", () => {
  it("keeps the server's rank order (largest single ₹ bound first, unbounded last)", () => {
    render(<NeedsList needs={[lossLimitNeed, taxSlabNeed]} onExplain={() => {}} />);
    const items = Array.from(screen.getByRole("list", { name: "Needs from you" }).children);
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Loss limit");
    expect(items[1]).toHaveTextContent("Tax slab");
  });

  it("shows the largest bound as an explainable number with its basis", async () => {
    const onExplain = vi.fn();
    render(<NeedsList needs={[lossLimitNeed]} onExplain={onExplain} />);
    expect(screen.getByText(/amount at risk/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /₹33,333/ }));
    expect(onExplain).toHaveBeenCalledWith(expect.objectContaining({ formula_id: "actions.needs@1" }));
  });

  it("never adds bounds: with several it shows the largest and says they are not added", () => {
    const two = {
      ...lossLimitNeed,
      unlocks: [
        lossLimitNeed.unlocks[0]!,
        { card_id: "x".repeat(64), basis: "TAX_DEFERRED" as const, number: num("unlock", "₹1,000", "actions.needs@1") },
      ],
    };
    render(<NeedsList needs={[two]} onExplain={() => {}} />);
    expect(screen.getByText(/largest of 2 bounds; bounds are never added/)).toBeInTheDocument();
    expect(screen.queryByText(/₹34,333/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /₹1,000/ })).not.toBeInTheDocument();
  });

  it("an unbounded need says so instead of inventing a number", () => {
    render(<NeedsList needs={[taxSlabNeed]} onExplain={() => {}} />);
    expect(screen.getByText(/The engine cannot bound the ₹ this unlocks/)).toBeInTheDocument();
    expect(screen.getByText(/Choose your tax slab/)).toBeInTheDocument();
  });

  it("an empty list is an explicit state", () => {
    render(<NeedsList needs={[]} onExplain={() => {}} />);
    expect(screen.getByText("Nothing is needed from you today.")).toBeInTheDocument();
  });
});
