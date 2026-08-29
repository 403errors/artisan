import {
  BotIcon,
  CircleIcon,
  GitPullRequestArrowIcon,
  GitPullRequestClosedIcon,
  MessageCircleIcon,
  MessageCircleQuestionIcon,
  PlayIcon,
  RotateCcwIcon,
  ShieldAlertIcon,
  SquareKanbanIcon,
  Trash2Icon,
  TriangleAlertIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import { stepLabel } from "@/lib/format";
import type { TicketEvent } from "@/types/ticket-event";

export type EventTone = "default" | "active" | "ok" | "warn" | "error";

interface EventPresentation {
  icon: LucideIcon;
  tone: EventTone;
  label?: string;
}

export const EVENT_PRESENTATION: Record<string, EventPresentation> = {
  gate_started: { icon: PlayIcon, tone: "active", label: "Gate started" },
  gate_decision: { icon: CircleIcon, tone: "default", label: "Gate decision" },
  step_changed: { icon: CircleIcon, tone: "default", label: "Step changed" },
  agent_invoked: { icon: BotIcon, tone: "active", label: "Agent invoked" },
  agent_completed: { icon: BotIcon, tone: "ok", label: "Agent completed" },
  tool_call: { icon: WrenchIcon, tone: "default", label: "Tool call" },
  retry: { icon: RotateCcwIcon, tone: "active", label: "Retry" },
  clarification_asked: { icon: MessageCircleQuestionIcon, tone: "warn", label: "Clarification asked" },
  clarification_answered: { icon: MessageCircleIcon, tone: "ok", label: "Clarification answered" },
  pr_opened: { icon: GitPullRequestArrowIcon, tone: "ok", label: "PR opened" },
  pr_closed: { icon: GitPullRequestClosedIcon, tone: "default", label: "PR closed" },
  issue_deleted: { icon: Trash2Icon, tone: "warn", label: "Issue deleted" },
  jira_synced: { icon: SquareKanbanIcon, tone: "default", label: "Jira synced" },
  escalation: { icon: ShieldAlertIcon, tone: "error", label: "Escalated" },
  escalated: { icon: ShieldAlertIcon, tone: "error", label: "Escalated" },
  error: { icon: TriangleAlertIcon, tone: "error", label: "Error" },
  manual_action: { icon: BotIcon, tone: "active", label: "Manual action" },
};

const DEFAULT_PRESENTATION: EventPresentation = { icon: CircleIcon, tone: "default" };

export function humanizeEventType(type: string): string {
  return EVENT_PRESENTATION[type]?.label ?? stepLabel(type);
}

export function presentationFor(type: string): EventPresentation {
  return EVENT_PRESENTATION[type] ?? DEFAULT_PRESENTATION;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function asGate(value: unknown): "1" | "2" | "3" | null {
  return value === "1" || value === "2" || value === "3" ? value : null;
}

function pick(obj: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (obj[key] !== undefined) return obj[key];
  }
  return undefined;
}

// Accepts snake_case or camelCase, tolerates missing/unexpected fields, and
// never throws — the backend event-log shape may not exist yet (fallback
// state) or may still be evolving once it does.
export function normalizeEvent(raw: unknown, index: number): TicketEvent {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};

  const type = asString(obj.type) ?? "unknown";
  const at = asString(pick(obj, "at", "timestamp", "created_at", "createdAt")) ?? new Date(0).toISOString();
  const id = asString(obj.id) ?? `${at}-${type}-${index}`;
  const summary = asString(obj.summary) ?? humanizeEventType(type);
  const toolName = asString(pick(obj, "tool_name", "toolName"));
  const runId = asString(pick(obj, "run_id", "runId"));
  const detail = asString(obj.detail);
  const status = obj.status === "ok" || obj.status === "error" || obj.status === "pending" ? obj.status : undefined;

  const knownKeys = new Set([
    "id",
    "at",
    "timestamp",
    "created_at",
    "createdAt",
    "type",
    "gate",
    "summary",
    "detail",
    "tool_name",
    "toolName",
    "args",
    "tool_args",
    "toolArgs",
    "result",
    "tool_result",
    "toolResult",
    "tool_result_summary",
    "toolResultSummary",
    "status",
    "run_id",
    "runId",
  ]);
  const extraEntries = Object.entries(obj).filter(([key]) => !knownKeys.has(key));
  const extra = extraEntries.length > 0 ? Object.fromEntries(extraEntries) : undefined;

  return {
    id,
    at,
    type,
    gate: asGate(obj.gate),
    summary,
    detail,
    toolName,
    args: pick(obj, "args", "tool_args", "toolArgs"),
    result: pick(obj, "result", "tool_result", "toolResult", "tool_result_summary", "toolResultSummary"),
    status,
    extra,
    runId,
  };
}

export interface GateGroup {
  gate: "1" | "2" | "3" | null;
  startedAt: string;
  endedAt: string;
  events: TicketEvent[];
}

// Groups consecutive events sharing the same gate (events are assumed sorted
// ascending by `at`), so the feed can show one section header per gate run
// rather than repeating the gate on every row.
export function groupByGate(events: TicketEvent[]): GateGroup[] {
  const groups: GateGroup[] = [];
  for (const event of events) {
    const last = groups.at(-1);
    if (last && last.gate === event.gate) {
      last.events.push(event);
      last.endedAt = event.at;
    } else {
      groups.push({ gate: event.gate, startedAt: event.at, endedAt: event.at, events: [event] });
    }
  }
  return groups;
}

export interface ToolCallGroup {
  kind: "tool_call_group";
  runId: string | undefined;
  events: TicketEvent[];
}

export type FeedItem = TicketEvent | ToolCallGroup;

export function isToolCallGroup(item: FeedItem): item is ToolCallGroup {
  return (item as ToolCallGroup).kind === "tool_call_group";
}

// Collapses consecutive `tool_call` events sharing the same `runId` into one group, so a long
// execution run's tool calls render as one expandable section instead of flooding the feed with
// one row per call. Everything else passes through untouched, in order.
export function groupToolCalls(events: TicketEvent[]): FeedItem[] {
  const items: FeedItem[] = [];
  for (const event of events) {
    const last = items.at(-1);
    if (
      event.type === "tool_call" &&
      last &&
      isToolCallGroup(last) &&
      last.runId === event.runId
    ) {
      last.events.push(event);
    } else if (event.type === "tool_call") {
      items.push({ kind: "tool_call_group", runId: event.runId, events: [event] });
    } else {
      items.push(event);
    }
  }
  return items;
}
