import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TicketFacts } from "@/components/ticket-facts";
import type { TicketDoc } from "@/types/ticket";

const TICKET: TicketDoc = {
  id: "403errors_artisan-demo__4",
  githubIssueNumber: 4,
  githubRepo: "403errors/artisan-demo",
  jiraKey: "ART-10",
  status: "pr_open",
  currentStep: null,
  clarificationRounds: 1,
  duplicateFollowups: 0,
  duplicateCandidates: [],
  retryCount: 2,
  domains: ["frontend"],
  plan: null,
  lastExecutionResult: {
    branch: "artisan/ART-10-attempt-2",
    diffSummary: "Added static landing page markup.",
    testsPassed: true,
    logsUri: "gs://artisan-logs/attempt-2",
  },
  prUrl: "https://github.com/403errors/artisan-demo/pull/5",
  prNumber: 5,
  trivialConflictAttempts: 0,
  lastConflictDetection: null,
  lastConflictResolution: null,
  escalationHistory: [],
  traceIds: [],
  createdAt: new Date("2026-01-01T00:00:00Z").toISOString(),
  updatedAt: new Date("2026-01-02T00:00:00Z").toISOString(),
};

describe("TicketFacts", () => {
  it("pulls scalars out of the narrative into a clean fact list", () => {
    render(<TicketFacts ticket={TICKET} />);
    expect(screen.getByText("Retries")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Clarification rounds")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Pull request")).toBeInTheDocument();
    expect(screen.getByText("#5")).toBeInTheDocument();
    expect(screen.getByText("artisan/ART-10-attempt-2")).toBeInTheDocument();
  });

  it("omits facts with no value instead of rendering an empty row", () => {
    render(<TicketFacts ticket={{ ...TICKET, prNumber: null, lastExecutionResult: null }} />);
    expect(screen.queryByText("Pull request")).not.toBeInTheDocument();
    expect(screen.queryByText("Branch")).not.toBeInTheDocument();
  });
});
