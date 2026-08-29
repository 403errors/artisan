import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TicketStatusBadge } from "@/components/ticket-status-badge";
import type { TicketStatus } from "@/types/ticket";

const CASES: Array<[TicketStatus, string]> = [
  ["intake", "Triaging"],
  ["in_progress", "Being Handled by Artisan"],
  ["pr_open", "PR Open — Awaiting Review"],
  ["escalated", "Needs Manual Review"],
  ["manual_pickup", "Needs Manual Review"],
  ["done", "Done"],
];

describe("TicketStatusBadge", () => {
  it.each(CASES)("renders the correct label for status %s", (status, label) => {
    render(<TicketStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
