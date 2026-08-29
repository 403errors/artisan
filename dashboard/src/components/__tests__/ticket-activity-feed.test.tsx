import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TicketActivityFeed } from "@/components/ticket-activity-feed";
import type { TicketDoc } from "@/types/ticket";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeEventSource.instances.push(this);
  }

  close() {}

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  fail() {
    this.onerror?.();
  }
}

const TICKET: TicketDoc = {
  id: "403errors_artisan-demo__4",
  githubIssueNumber: 4,
  githubRepo: "403errors/artisan-demo",
  jiraKey: "ART-10",
  status: "done",
  currentStep: null,
  clarificationRounds: 0,
  duplicateFollowups: 0,
  duplicateCandidates: [],
  retryCount: 0,
  domains: [],
  plan: null,
  lastExecutionResult: null,
  prUrl: null,
  prNumber: null,
  trivialConflictAttempts: 0,
  lastConflictDetection: null,
  lastConflictResolution: null,
  escalationHistory: [],
  traceIds: [],
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
};

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("TicketActivityFeed", () => {
  it("renders events grouped by gate once the SSE stream delivers a frame", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketActivityFeed ticket={TICKET} />);

    FakeEventSource.instances[0].emit([
      { id: "1", at: "2026-01-01T00:00:00Z", type: "gate_started", gate: "2", summary: "Gate 2 started" },
      { id: "2", at: "2026-01-01T00:01:00Z", type: "pr_opened", gate: "2", summary: "PR opened" },
    ]);

    expect(await screen.findByText("Gate 2 started")).toBeInTheDocument();
    expect(screen.getByText("PR opened")).toBeInTheDocument();
    expect(screen.getByText("2 events")).toBeInTheDocument();
  });

  it("renders an unknown event type without crashing", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketActivityFeed ticket={TICKET} />);

    FakeEventSource.instances[0].emit([
      { id: "1", at: "2026-01-01T00:00:00Z", type: "some_future_event_type", gate: null },
    ]);

    expect(await screen.findByText("Some Future Event Type")).toBeInTheDocument();
  });

  it("falls back to a fetch and then an unavailable message when the SSE route doesn't exist", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    render(<TicketActivityFeed ticket={TICKET} />);
    FakeEventSource.instances[0].fail();

    expect(await screen.findByText("Activity capture isn't available for this ticket yet.")).toBeInTheDocument();
  });

  it("shows a plain empty state when the feed loads with zero events", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketActivityFeed ticket={TICKET} />);
    expect(screen.getByText("No recorded activity yet.")).toBeInTheDocument();
  });

  it("groups consecutive same-run tool calls under one 'Show tool calls' toggle", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    render(<TicketActivityFeed ticket={TICKET} />);

    FakeEventSource.instances[0].emit([
      { id: "1", at: "2026-01-01T00:00:00Z", type: "gate_started", gate: "2", summary: "Gate 2 started" },
      {
        id: "2",
        at: "2026-01-01T00:00:01Z",
        type: "tool_call",
        gate: "2",
        summary: "read_file(a.py)",
        run_id: "run-1",
      },
      {
        id: "3",
        at: "2026-01-01T00:00:02Z",
        type: "tool_call",
        gate: "2",
        summary: "write_file(a.py)",
        run_id: "run-1",
      },
    ]);

    expect(await screen.findByText("Gate 2 started")).toBeInTheDocument();
    expect(screen.getByText("Show tool calls (2)")).toBeInTheDocument();
    expect(screen.queryByText("read_file(a.py)")).not.toBeInTheDocument();
  });
});
