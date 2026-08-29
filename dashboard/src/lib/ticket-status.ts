import type { TicketStatus } from "@/types/ticket";

export type StatusBucket = "active" | "review" | "urgent" | "resolved";

// User-confirmed mapping: green = resolved, orange = review, red = urgent.
// intake/in_progress are "actively handled" and get their own live indicator
// instead of one of the three filter buckets (see isActivelyWorking/isStalled).
export const STATUS_BUCKET: Record<TicketStatus, StatusBucket> = {
  intake: "active",
  in_progress: "active",
  pr_open: "review",
  manual_pickup: "review",
  needs_human_review: "review",
  duplicate_review: "review",
  escalated: "urgent",
  done: "resolved",
};

export function bucketOf(status: TicketStatus): StatusBucket {
  return STATUS_BUCKET[status];
}

export const BUCKET_ORDER: StatusBucket[] = ["active", "review", "urgent", "resolved"];

export const BUCKET_META: Record<
  StatusBucket,
  { label: string; dotClass: string; textClass: string; softClass: string }
> = {
  active: {
    label: "Being handled",
    dotClass: "bg-status-active",
    textClass: "text-status-active",
    softClass:
      "bg-status-active/10 text-status-active border-status-active/25 dark:bg-status-active/15",
  },
  review: {
    label: "Needs review",
    dotClass: "bg-status-review",
    textClass: "text-status-review",
    softClass:
      "bg-status-review/10 text-status-review border-status-review/25 dark:bg-status-review/15",
  },
  urgent: {
    label: "Failed / urgent",
    dotClass: "bg-status-urgent",
    textClass: "text-status-urgent",
    softClass:
      "bg-status-urgent/10 text-status-urgent border-status-urgent/25 dark:bg-status-urgent/15",
  },
  resolved: {
    label: "Resolved",
    dotClass: "bg-status-resolved",
    textClass: "text-status-resolved",
    softClass:
      "bg-status-resolved/10 text-status-resolved border-status-resolved/25 dark:bg-status-resolved/15",
  },
};

export const LIVE_STATUSES: ReadonlySet<TicketStatus> = new Set(["intake", "in_progress"]);

export function isLive(status: TicketStatus): boolean {
  return LIVE_STATUSES.has(status);
}

// How long a live ticket can go without a Firestore update before we stop
// trusting that Artisan is still actively working it. Gates write current_step
// on every transition, so a gap this long means the run likely crashed/hung.
export const STALE_AFTER_MS = 10 * 60_000;

interface TicketLikeForStaleness {
  status: TicketStatus;
  updatedAt: string;
}

// `now: null` means "not yet mounted" (see useNow) — treat as fresh so SSR and
// the first client render agree and we never flash a false "stalled" state.
export function isActivelyWorking(ticket: TicketLikeForStaleness, now: number | null): boolean {
  if (!isLive(ticket.status)) return false;
  if (now === null) return true;
  return now - new Date(ticket.updatedAt).getTime() < STALE_AFTER_MS;
}

export function isStalled(ticket: TicketLikeForStaleness, now: number | null): boolean {
  return isLive(ticket.status) && !isActivelyWorking(ticket, now);
}
