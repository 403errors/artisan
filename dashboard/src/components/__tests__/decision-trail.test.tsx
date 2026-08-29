import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionTrail } from "@/components/decision-trail";
import type { TicketDoc } from "@/types/ticket";

const TICKET: TicketDoc = {
  id: "403errors_artisan-demo__4",
  githubIssueNumber: 4,
  githubRepo: "403errors/artisan-demo",
  jiraKey: "ART-10",
  status: "pr_open",
  currentStep: null,
  clarificationRounds: 0,
  duplicateFollowups: 0,
  duplicateCandidates: [],
  retryCount: 2,
  domains: ["frontend"],
  plan: {
    steps: ["Add landing page"],
    touchedFiles: ["index.html"],
    testCases: ["renders hero section"],
    docUpdates: ["README.md"],
  },
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
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
};

describe("DecisionTrail", () => {
  it("renders every Gate 2 field from the ticket doc exactly", () => {
    render(<DecisionTrail ticket={TICKET} />);
    expect(screen.getByText("frontend")).toBeInTheDocument();
    expect(screen.getByText("Add landing page")).toBeInTheDocument();
    expect(screen.getByText("Touched files")).toBeInTheDocument();
    expect(screen.getByText("index.html")).toBeInTheDocument();
    expect(screen.getByText("Test cases")).toBeInTheDocument();
    expect(screen.getByText("renders hero section")).toBeInTheDocument();
    expect(screen.getByText("Doc updates")).toBeInTheDocument();
    expect(screen.getByText("README.md")).toBeInTheDocument();
    expect(screen.getByText("Added static landing page markup.")).toBeInTheDocument();
    expect(screen.getByText("Tests passed")).toBeInTheDocument();
  });

  it("does not render a Gate 3 section when no conflict data exists", () => {
    render(<DecisionTrail ticket={TICKET} />);
    expect(screen.queryByText(/Gate 3/)).not.toBeInTheDocument();
  });

  it("renders the Gate 3 section when conflict detection data exists", () => {
    const withConflict: TicketDoc = {
      ...TICKET,
      lastConflictDetection: {
        hasConflict: true,
        conflictedFiles: ["shared.py"],
        conflictMarkers: "<<<<<<<",
        baseBranchHistory: "base history",
        diffSummary: "conflicting edits to shared.py",
        logsUri: "gs://artisan-logs/detect-1",
        headSha: "deadbeef",
      },
    };
    render(<DecisionTrail ticket={withConflict} />);
    expect(screen.getByText(/Gate 3/)).toBeInTheDocument();
    expect(screen.getByText("conflicting edits to shared.py")).toBeInTheDocument();
    expect(screen.getByText("shared.py")).toBeInTheDocument();
  });
});
