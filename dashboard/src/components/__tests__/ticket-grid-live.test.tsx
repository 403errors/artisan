import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { TicketGridLive } from "@/components/ticket-grid-live";
import type { TicketSummary } from "@/types/ticket";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {}

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

function ticket(overrides: Partial<TicketSummary>): TicketSummary {
  return {
    id: "1",
    jiraKey: "ART-1",
    githubIssueNumber: 1,
    githubRepo: "403errors/artisan-demo",
    status: "in_progress",
    currentGate: "2",
    currentStep: null,
    lastDecision: "",
    prUrl: null,
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("TicketGridLive", () => {
  it("sorts the initial list by updatedAt descending", () => {
    const older = ticket({ id: "old", jiraKey: "ART-OLD", updatedAt: "2020-01-01T00:00:00Z" });
    const newer = ticket({ id: "new", jiraKey: "ART-NEW", updatedAt: "2024-01-01T00:00:00Z" });
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketGridLive initial={[older, newer]} emptyMessage="empty" />);
    const cards = screen.getAllByText(/^ART-/);
    expect(cards[0]).toHaveTextContent("ART-NEW");
    expect(cards[1]).toHaveTextContent("ART-OLD");
  });

  it("re-sorts every SSE frame instead of trusting server order", async () => {
    const older = ticket({ id: "old", jiraKey: "ART-OLD", updatedAt: "2020-01-01T00:00:00Z" });
    const newer = ticket({ id: "new", jiraKey: "ART-NEW", updatedAt: "2024-01-01T00:00:00Z" });
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketGridLive initial={[]} emptyMessage="empty" />);

    // Firestore's stream has no server-side orderBy, so a frame can arrive in
    // doc order rather than updatedAt order — the client must re-sort it.
    FakeEventSource.instances[0].emit([older, newer]);

    const cards = await screen.findAllByText(/^ART-/);
    expect(cards[0]).toHaveTextContent("ART-NEW");
    expect(cards[1]).toHaveTextContent("ART-OLD");
  });

  it("filters the grid when a status bucket chip is toggled", () => {
    const resolved = ticket({ id: "1", jiraKey: "ART-DONE", status: "done" });
    const active = ticket({ id: "2", jiraKey: "ART-WORKING", status: "in_progress" });
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketGridLive initial={[resolved, active]} emptyMessage="empty" />);

    expect(screen.getByText("ART-DONE")).toBeInTheDocument();
    expect(screen.getByText("ART-WORKING")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Resolved/ }));

    expect(screen.getByText("ART-DONE")).toBeInTheDocument();
    expect(screen.queryByText("ART-WORKING")).not.toBeInTheDocument();
  });
});
