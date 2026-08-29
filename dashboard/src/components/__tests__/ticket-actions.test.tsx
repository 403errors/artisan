import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TicketActions } from "@/components/ticket-actions";
import { TicketDetailHeader } from "@/components/ticket-detail-header";
import type { TicketDoc } from "@/types/ticket";

function ticket(overrides: Partial<TicketDoc>): TicketDoc {
  return {
    id: "403errors_artisan-demo__4",
    githubIssueNumber: 4,
    githubRepo: "403errors/artisan-demo",
    jiraKey: "ART-10",
    status: "escalated",
    currentStep: null,
    clarificationRounds: 0,
    retryCount: 1,
    domains: [],
    plan: null,
    lastExecutionResult: null,
    prUrl: null,
    prNumber: null,
    trivialConflictAttempts: 0,
    lastConflictDetection: null,
    lastConflictResolution: null,
    escalationHistory: [{ at: new Date().toISOString(), reason: "boom", gate: "2" }],
    traceIds: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TicketActions", () => {
  it("shows retry and mark-resolved for an escalated ticket, no force-escalate", () => {
    render(<TicketActions ticket={ticket({ status: "escalated" })} />);
    expect(screen.getByRole("button", { name: /Retry gate/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mark resolved/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Force escalate/ })).not.toBeInTheDocument();
  });

  it("shows a disabled mark-resolved with no retry for an in_progress ticket", () => {
    render(
      <TicketActions
        ticket={ticket({ status: "in_progress", updatedAt: new Date().toISOString() })}
      />,
    );
    expect(screen.getByRole("button", { name: /Force escalate/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mark resolved/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Retry gate/ })).not.toBeInTheDocument();
  });

  it("shows nothing but a done message for a resolved ticket", () => {
    render(<TicketActions ticket={ticket({ status: "done" })} />);
    expect(screen.getByText("No actions available")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not call the API until the confirmation dialog is accepted", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    render(<TicketActions ticket={ticket({ status: "escalated" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Retry gate/ }));

    expect(await screen.findByText("Retry this gate?")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tickets/403errors_artisan-demo__4/actions/retry",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("disables the confirm button and shows a spinner while the request is pending", async () => {
    let resolveFetch: (v: unknown) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(new Promise((resolve) => (resolveFetch = resolve))),
    );

    render(<TicketActions ticket={ticket({ status: "escalated" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Retry gate/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    // The background is inert while the AlertDialog is open (correct a11y
    // behavior) — assert against the dialog's own confirm/cancel controls.
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    resolveFetch({ ok: true });
    await waitFor(() => expect(screen.queryByText("Retry this gate?")).not.toBeInTheDocument());
  });

  it("does not warn when the PR link is rendered as an anchor", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <TicketDetailHeader
        ticket={ticket({
          status: "pr_open",
          prUrl: "https://github.com/403errors/artisan-demo/pull/42",
        })}
        stalled={false}
      />,
    );

    expect(screen.getByRole("button", { name: /View PR on GitHub/i })).toHaveAttribute(
      "href",
      "https://github.com/403errors/artisan-demo/pull/42",
    );
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
