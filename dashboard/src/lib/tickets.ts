import type { Timestamp } from "@google-cloud/firestore";

import { getFirestore } from "@/lib/firestore";
import { TARGET_REPO } from "@/lib/config";
import { currentGate, lastDecision } from "@/lib/ticket-derived";
import type {
  ConflictDetectionResult,
  EscalationEntry,
  ExecutionResult,
  Plan,
  TicketDoc,
  TicketSummary,
  TicketStatus,
} from "@/types/ticket";
import type { TicketEvent } from "@/types/ticket-event";

// Raw wire shape as Firestore actually stores it — Pydantic dumps field names verbatim, no
// alias_generator configured anywhere in firestore_schema.py, so this is genuinely snake_case.
interface RawTicketDoc {
  github_issue_number: number;
  github_repo: string;
  jira_key: string;
  status: TicketStatus;
  current_step: string | null;
  clarification_rounds: number;
  retry_count: number;
  domains: string[];
  plan: RawPlan | null;
  last_execution_result: RawExecutionResult | null;
  pr_url: string | null;
  pr_number: number | null;
  trivial_conflict_attempts: number;
  last_conflict_detection: RawConflictDetectionResult | null;
  last_conflict_resolution: RawExecutionResult | null;
  escalation_history: EscalationEntry[];
  trace_ids: string[];
  created_at: string;
  updated_at: string;
}

interface RawPlan {
  steps: string[];
  touched_files: string[];
  test_cases: string[];
  doc_updates: string[];
}

interface RawExecutionResult {
  branch: string;
  diff_summary: string;
  tests_passed: boolean;
  logs_uri: string;
}

interface RawConflictDetectionResult {
  has_conflict: boolean;
  conflicted_files: string[];
  conflict_markers: string;
  base_branch_history: string;
  diff_summary: string;
  logs_uri: string;
  head_sha: string;
}

function toPlan(raw: RawPlan | null): Plan | null {
  if (!raw) return null;
  return {
    steps: raw.steps,
    touchedFiles: raw.touched_files,
    testCases: raw.test_cases,
    docUpdates: raw.doc_updates,
  };
}

function toExecutionResult(raw: RawExecutionResult | null): ExecutionResult | null {
  if (!raw) return null;
  return {
    branch: raw.branch,
    diffSummary: raw.diff_summary,
    testsPassed: raw.tests_passed,
    logsUri: raw.logs_uri,
  };
}

function toConflictDetectionResult(
  raw: RawConflictDetectionResult | null,
): ConflictDetectionResult | null {
  if (!raw) return null;
  return {
    hasConflict: raw.has_conflict,
    conflictedFiles: raw.conflicted_files,
    conflictMarkers: raw.conflict_markers,
    baseBranchHistory: raw.base_branch_history,
    diffSummary: raw.diff_summary,
    logsUri: raw.logs_uri,
    headSha: raw.head_sha,
  };
}

function toTicketDoc(id: string, raw: RawTicketDoc): TicketDoc {
  return {
    id,
    githubIssueNumber: raw.github_issue_number,
    githubRepo: raw.github_repo,
    jiraKey: raw.jira_key,
    status: raw.status,
    currentStep: raw.current_step ?? null,
    clarificationRounds: raw.clarification_rounds,
    retryCount: raw.retry_count,
    domains: raw.domains ?? [],
    plan: toPlan(raw.plan),
    lastExecutionResult: toExecutionResult(raw.last_execution_result),
    prUrl: raw.pr_url,
    prNumber: raw.pr_number,
    trivialConflictAttempts: raw.trivial_conflict_attempts,
    lastConflictDetection: toConflictDetectionResult(raw.last_conflict_detection),
    lastConflictResolution: toExecutionResult(raw.last_conflict_resolution),
    escalationHistory: raw.escalation_history ?? [],
    traceIds: raw.trace_ids ?? [],
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function toTicketSummary(doc: TicketDoc): TicketSummary {
  return {
    id: doc.id,
    jiraKey: doc.jiraKey,
    githubIssueNumber: doc.githubIssueNumber,
    githubRepo: doc.githubRepo,
    status: doc.status,
    currentGate: currentGate(doc),
    currentStep: doc.currentStep,
    lastDecision: lastDecision(doc),
    prUrl: doc.prUrl,
    updatedAt: doc.updatedAt,
  };
}

export async function listTickets(): Promise<TicketSummary[]> {
  const snapshot = await getFirestore()
    .collection("tickets")
    .where("github_repo", "==", TARGET_REPO)
    .orderBy("updated_at", "desc")
    .get();
  return snapshot.docs.map((d) => toTicketSummary(toTicketDoc(d.id, d.data() as RawTicketDoc)));
}

export async function listEscalatedTickets(): Promise<TicketSummary[]> {
  const snapshot = await getFirestore()
    .collection("tickets")
    .where("github_repo", "==", TARGET_REPO)
    .where("status", "in", ["escalated", "manual_pickup", "needs_human_review"])
    .orderBy("updated_at", "desc")
    .get();
  return snapshot.docs.map((d) => toTicketSummary(toTicketDoc(d.id, d.data() as RawTicketDoc)));
}

export async function getTicket(id: string): Promise<TicketDoc | null> {
  const snapshot = await getFirestore().collection("tickets").doc(id).get();
  if (!snapshot.exists) return null;
  return toTicketDoc(snapshot.id, snapshot.data() as RawTicketDoc);
}

// Raw wire shape of a `tickets/{ticketId}/events/{autoId}` doc — see
// packages/artisan_shared/src/artisan_shared/events.py::TicketEvent for the source of truth.
// `at` is a real Firestore Timestamp (SERVER_TIMESTAMP resolved server-side), not an ISO string
// like every other timestamp field in this file — see event_log.py's EventSink for why (ordering
// across two different processes with unbounded clock skew).
export interface RawTicketEvent {
  seq: number;
  run_id: string;
  at: Timestamp | null;
  gate: "1" | "2" | "3" | null;
  type: string;
  actor: string;
  summary: string;
  detail: string | null;
  tool_name: string | null;
  tool_args: Record<string, string> | null;
  tool_result_summary: string | null;
  truncated: boolean;
}

export function toTicketEvent(id: string, raw: RawTicketEvent): TicketEvent {
  return {
    id,
    // A just-committed event's listener callback can still see `at` as null for an instant
    // (server-timestamp resolution) — fall back to "now" rather than a bogus epoch date.
    at: raw.at ? raw.at.toDate().toISOString() : new Date().toISOString(),
    type: raw.type,
    gate: raw.gate,
    summary: raw.summary,
    detail: raw.detail ?? undefined,
    toolName: raw.tool_name ?? undefined,
    args: raw.tool_args ?? undefined,
    result: raw.tool_result_summary ?? undefined,
    status: raw.type === "error" ? "error" : undefined,
  };
}

export { toTicketDoc, toTicketSummary, currentGate, lastDecision };
export type { RawTicketDoc };
