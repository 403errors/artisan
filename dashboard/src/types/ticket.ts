// Mirrors packages/artisan_shared/src/artisan_shared/firestore_schema.py + models.py exactly.
// SYSTEM_DESIGN.md §6.4 is stale (missing lastExecutionResult/processedDeliveryIds) — this file
// is derived from the real Pydantic models, not that doc.

export type TicketStatus =
  | "intake"
  | "in_progress"
  | "pr_open"
  | "escalated"
  | "manual_pickup"
  | "needs_human_review"
  | "done";

export interface Plan {
  steps: string[];
  touchedFiles: string[];
  testCases: string[];
  docUpdates: string[];
}

export interface ExecutionResult {
  branch: string;
  diffSummary: string;
  testsPassed: boolean;
  logsUri: string;
}

export interface ConflictDetectionResult {
  hasConflict: boolean;
  conflictedFiles: string[];
  conflictMarkers: string;
  baseBranchHistory: string;
  diffSummary: string;
  logsUri: string;
  headSha: string;
}

export interface EscalationEntry {
  at: string; // ISO datetime
  reason: string;
  gate: "1" | "2" | "3";
}

// One Cloud Trace span per gate decision (not one per gate) — `label` names which decision this
// is, e.g. "Gate 2: verification passed", since a bare trace id alone doesn't say what it's for.
export interface TraceEntry {
  traceId: string;
  label: string;
}

export interface TicketDoc {
  id: string; // Firestore doc id (ticket_doc_id)
  githubIssueNumber: number;
  githubRepo: string;
  jiraKey: string;
  jiraSummary: string | null;
  status: TicketStatus;
  currentStep: string | null;
  clarificationRounds: number;
  retryCount: number;
  domains: string[];
  plan: Plan | null;
  lastExecutionResult: ExecutionResult | null;
  prUrl: string | null;
  prNumber: number | null;
  trivialConflictAttempts: number;
  lastConflictDetection: ConflictDetectionResult | null;
  lastConflictResolution: ExecutionResult | null;
  escalationHistory: EscalationEntry[];
  traceIds: TraceEntry[];
  createdAt: string;
  updatedAt: string;
}

// Slim shape for the list/card view (SYSTEM_DESIGN.md §6.3).
export interface TicketSummary {
  id: string;
  jiraKey: string;
  jiraSummary: string | null;
  githubIssueNumber: number;
  githubRepo: string;
  status: TicketStatus;
  currentGate: "1" | "2" | "3";
  currentStep: string | null;
  lastDecision: string;
  prUrl: string | null;
  updatedAt: string;
}
