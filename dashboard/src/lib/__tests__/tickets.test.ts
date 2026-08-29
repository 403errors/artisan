import { describe, expect, it } from "vitest";

import { currentGate, lastDecision, toTicketEvent, type RawTicketEvent } from "@/lib/tickets";
import type { TicketDoc } from "@/types/ticket";

function ticket(overrides: Partial<TicketDoc>): TicketDoc {
  return {
    id: "403errors_artisan-demo__1",
    githubIssueNumber: 1,
    githubRepo: "403errors/artisan-demo",
    jiraKey: "ART-1",
    status: "intake",
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
    ...overrides,
  };
}

describe("currentGate", () => {
  it("returns gate 1 for a fresh intake ticket", () => {
    expect(currentGate(ticket({ status: "intake" }))).toBe("1");
  });

  it("returns gate 2 for a live current_step in gate 2's step set", () => {
    expect(currentGate(ticket({ status: "in_progress", currentStep: "planning (attempt 2)" }))).toBe(
      "2",
    );
  });

  it("returns gate 3 for a live current_step in gate 3's step set", () => {
    expect(
      currentGate(ticket({ status: "in_progress", currentStep: "classifying_conflict" })),
    ).toBe("3");
  });

  it("falls back to the last escalation's gate for a terminal ticket with no live step", () => {
    expect(
      currentGate(
        ticket({
          status: "escalated",
          currentStep: null,
          escalationHistory: [{ at: new Date().toISOString(), reason: "x", gate: "3" }],
        }),
      ),
    ).toBe("3");
  });

  it("falls back to gate 2 for a pr_open ticket with no escalation history", () => {
    expect(currentGate(ticket({ status: "pr_open", prUrl: "https://x" }))).toBe("2");
  });

  it("returns gate 1 while awaiting duplicate confirmation", () => {
    expect(currentGate(ticket({ status: "duplicate_review" }))).toBe("1");
  });
});

describe("lastDecision", () => {
  it("surfaces the last escalation reason when escalated", () => {
    expect(
      lastDecision(
        ticket({
          status: "escalated",
          escalationHistory: [{ at: new Date().toISOString(), reason: "verification failed 3x", gate: "2" }],
        }),
      ),
    ).toBe("verification failed 3x");
  });

  it("reports awaiting duplicate confirmation while in duplicate_review", () => {
    expect(lastDecision(ticket({ status: "duplicate_review" }))).toBe(
      "awaiting duplicate confirmation",
    );
  });

  it("mentions the PR url when pr_open", () => {
    expect(lastDecision(ticket({ status: "pr_open", prUrl: "https://x/pull/5" }))).toContain(
      "https://x/pull/5",
    );
  });
});

function rawEvent(overrides: Partial<RawTicketEvent>): RawTicketEvent {
  return {
    seq: 0,
    run_id: "run-1",
    at: { toDate: () => new Date("2026-01-01T00:00:00Z") } as RawTicketEvent["at"],
    gate: "2",
    type: "tool_call",
    actor: "coding_agent",
    summary: "read_file(path=a.txt)",
    detail: null,
    tool_name: "read_file",
    tool_args: { path: "a.txt" },
    tool_result_summary: null,
    truncated: false,
    ...overrides,
  };
}

describe("toTicketEvent", () => {
  it("converts the Firestore Timestamp to an ISO string and maps snake_case to camelCase", () => {
    const event = toTicketEvent("doc-1", rawEvent({}));
    expect(event).toMatchObject({
      id: "doc-1",
      at: "2026-01-01T00:00:00.000Z",
      type: "tool_call",
      gate: "2",
      toolName: "read_file",
      args: { path: "a.txt" },
    });
  });

  it("falls back to now when at is still null (server timestamp not yet resolved)", () => {
    const event = toTicketEvent("doc-1", rawEvent({ at: null }));
    expect(new Date(event.at).getTime()).toBeGreaterThan(0);
  });

  it("marks error-type events with status error", () => {
    const event = toTicketEvent("doc-1", rawEvent({ type: "error", summary: "boom" }));
    expect(event.status).toBe("error");
  });

  it("omits detail/toolName/args/result when the underlying fields are null", () => {
    const event = toTicketEvent(
      "doc-1",
      rawEvent({ detail: null, tool_name: null, tool_args: null, tool_result_summary: null }),
    );
    expect(event.detail).toBeUndefined();
    expect(event.toolName).toBeUndefined();
    expect(event.args).toBeUndefined();
    expect(event.result).toBeUndefined();
  });
});
