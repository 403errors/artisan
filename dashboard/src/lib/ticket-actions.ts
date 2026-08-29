import { RotateCcwIcon, ShieldAlertIcon, CircleCheckBigIcon, type LucideIcon } from "lucide-react";

import { isActivelyWorking, isLive, isStalled } from "@/lib/ticket-status";
import type { TicketStatus } from "@/types/ticket";

export type TicketActionKind = "retry" | "escalate" | "mark-done";

interface ActionMeta {
  label: string;
  icon: LucideIcon;
  variant: "default" | "outline" | "secondary" | "destructive";
  path: string;
  confirm: { title: string; body: string; confirmLabel: string; destructive: boolean };
  needsReason?: boolean;
}

export const ACTION_META: Record<TicketActionKind, ActionMeta> = {
  retry: {
    label: "Retry gate",
    icon: RotateCcwIcon,
    variant: "outline",
    path: "retry",
    confirm: {
      title: "Retry this gate?",
      body: "Artisan will re-run this gate with fresh retry budget. This costs agent time and may take a few minutes.",
      confirmLabel: "Retry",
      destructive: false,
    },
  },
  escalate: {
    label: "Force escalate",
    icon: ShieldAlertIcon,
    variant: "outline",
    path: "escalate",
    confirm: {
      title: "Force escalate this ticket?",
      body: "This immediately marks the ticket as needing manual review and notifies via GitHub and Jira.",
      confirmLabel: "Escalate",
      destructive: true,
    },
    needsReason: true,
  },
  "mark-done": {
    label: "Mark resolved",
    icon: CircleCheckBigIcon,
    variant: "secondary",
    path: "mark-done",
    confirm: {
      title: "Mark this ticket resolved?",
      body: "This closes the ticket in Artisan's own record. The GitHub issue and PR are not modified.",
      confirmLabel: "Mark resolved",
      destructive: true,
    },
  },
};

export interface ActionAvailability {
  kind: TicketActionKind;
  enabled: boolean;
  disabledReason?: string;
  /** Overrides `ACTION_META[kind]`'s label/confirm copy for a specific ticket status, when the
   * generic wording would be misleading in that context (e.g. "Force escalate" once a PR is
   * already open and just stalled, rather than genuinely broken). */
  label?: string;
  confirm?: ActionMeta["confirm"];
}

interface TicketForActions {
  status: TicketStatus;
  updatedAt: string;
}

export function availableActions(ticket: TicketForActions, now: number | null): ActionAvailability[] {
  if (ticket.status === "done") return [];

  const actions: ActionAvailability[] = [];
  const live = isLive(ticket.status);
  const stalled = isStalled(ticket, now);
  const actively = isActivelyWorking(ticket, now);

  if (
    ticket.status === "escalated" ||
    ticket.status === "manual_pickup" ||
    ticket.status === "needs_human_review" ||
    stalled
  ) {
    actions.push({ kind: "retry", enabled: true });
  }

  if (ticket.status === "intake" || ticket.status === "in_progress") {
    actions.push({ kind: "escalate", enabled: true });
  } else if (ticket.status === "pr_open") {
    // A PR is already open — this isn't "Artisan is stuck", it's "this PR has gone quiet and a
    // human should pick it up", so the generic escalate wording/confirm would be misleading here.
    actions.push({
      kind: "escalate",
      enabled: true,
      label: "Flag for manual review",
      confirm: {
        title: "Flag this PR for manual review?",
        body: "Use this if the open PR has stalled and needs a human to pick it up. This notifies via GitHub and Jira — it does not close or modify the PR itself.",
        confirmLabel: "Flag for review",
        destructive: true,
      },
    });
  }

  if (
    ticket.status === "pr_open" ||
    ticket.status === "escalated" ||
    ticket.status === "manual_pickup" ||
    ticket.status === "needs_human_review"
  ) {
    actions.push({
      kind: "mark-done",
      enabled: true,
      label: ticket.status === "pr_open" ? "Close ticket" : "Mark resolved",
    });
  } else if (live) {
    actions.push({
      kind: "mark-done",
      enabled: false,
      disabledReason: actively
        ? "Artisan is still working this ticket — force-escalate first if you need to take over."
        : "Nothing to merge yet — this ticket hasn't opened a PR.",
    });
  }

  return actions;
}

export type PostTicketActionResult = { ok: true } | { ok: false; message: string };

export async function postTicketAction(
  ticketId: string,
  kind: TicketActionKind,
  body: Record<string, unknown> = {},
): Promise<PostTicketActionResult> {
  const idempotencyKey =
    typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());

  try {
    const res = await fetch(`/api/tickets/${ticketId}/actions/${ACTION_META[kind].path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    });

    if (res.ok) return { ok: true };

    if (res.status === 401) return { ok: false, message: "Your session expired — sign in again." };
    if (res.status === 404) return { ok: false, message: "Ticket not found." };
    if (res.status === 409) {
      return { ok: false, message: "This ticket already changed state. Refresh and try again." };
    }

    const payload = await res.json().catch(() => null);
    return {
      ok: false,
      message: (payload && typeof payload.error === "string" && payload.error) || `Request failed (${res.status}).`,
    };
  } catch {
    return { ok: false, message: "Couldn't reach the server." };
  }
}
