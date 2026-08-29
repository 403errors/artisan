import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { TicketGrid } from "@/components/ticket-grid";
import type { TicketSummary } from "@/types/ticket";

const TICKET: TicketSummary = {
  id: "403errors_artisan-demo__4",
  jiraKey: "ART-10",
  githubIssueNumber: 4,
  githubRepo: "403errors/artisan-demo",
  status: "pr_open",
  currentGate: "2",
  currentStep: null,
  lastDecision: "PR opened: https://github.com/403errors/artisan-demo/pull/5",
  prUrl: "https://github.com/403errors/artisan-demo/pull/5",
  updatedAt: new Date().toISOString(),
};

describe("TicketGrid", () => {
  it("renders one card per ticket", () => {
    render(<TicketGrid tickets={[TICKET]} emptyMessage="empty" />);
    expect(screen.getByText("ART-10")).toBeInTheDocument();
    expect(screen.getByText("#4")).toBeInTheDocument();
    expect(screen.getByText("PR Open — Awaiting Review")).toBeInTheDocument();
  });

  it("renders the empty-state message when there are no tickets", () => {
    render(<TicketGrid tickets={[]} emptyMessage="No tickets yet." />);
    expect(screen.getByText("No tickets yet.")).toBeInTheDocument();
  });
});
