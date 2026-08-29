import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TicketFilterBar } from "@/components/ticket-filter-bar";

const COUNTS = { active: 2, review: 0, urgent: 1, resolved: 3 };

describe("TicketFilterBar", () => {
  it("renders one chip per bucket with its count", () => {
    render(
      <TicketFilterBar
        counts={COUNTS}
        selected={[]}
        onChange={vi.fn()}
        total={6}
        hiddenActiveCount={0}
        onShowActive={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Being handled.*2/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resolved.*3/ })).toBeInTheDocument();
    expect(screen.getByText("Showing all 6")).toBeInTheDocument();
  });

  it("disables a bucket chip with zero tickets", () => {
    render(
      <TicketFilterBar
        counts={COUNTS}
        selected={[]}
        onChange={vi.fn()}
        total={6}
        hiddenActiveCount={0}
        onShowActive={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Needs review/ })).toBeDisabled();
  });

  it("fires onChange with the toggled bucket and shows a Clear button when filtering", () => {
    const onChange = vi.fn();
    render(
      <TicketFilterBar
        counts={COUNTS}
        selected={[]}
        onChange={onChange}
        total={6}
        hiddenActiveCount={0}
        onShowActive={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Resolved/ }));
    expect(onChange).toHaveBeenCalledWith(["resolved"]);
  });

  it("shows a clear button once a filter is selected", () => {
    render(
      <TicketFilterBar
        counts={COUNTS}
        selected={["resolved"]}
        onChange={vi.fn()}
        total={6}
        hiddenActiveCount={0}
        onShowActive={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Clear/ })).toBeInTheDocument();
  });

  it("shows the hidden-active-work escape hatch when the active bucket is filtered out", () => {
    const onShowActive = vi.fn();
    render(
      <TicketFilterBar
        counts={COUNTS}
        selected={["resolved"]}
        onChange={vi.fn()}
        total={6}
        hiddenActiveCount={2}
        onShowActive={onShowActive}
      />,
    );
    const showButton = screen.getByRole("button", { name: "Show" });
    expect(screen.getByText(/2 tickets are being worked right now/)).toBeInTheDocument();
    fireEvent.click(showButton);
    expect(onShowActive).toHaveBeenCalled();
  });
});
