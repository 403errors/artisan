import { describe, expect, it } from "vitest";

import { currentGate, lastDecision } from "@/lib/tickets";
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

  it("mentions the PR url when pr_open", () => {
    expect(lastDecision(ticket({ status: "pr_open", prUrl: "https://x/pull/5" }))).toContain(
      "https://x/pull/5",
    );
  });
});
