import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TicketStatus } from "@/types/ticket";

const STATUS_COPY: Record<TicketStatus, { label: string; className: string }> = {
  intake: {
    label: "Triaging",
    className: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-200",
  },
  in_progress: {
    label: "Being Handled by Artisan",
    className: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/40 dark:text-blue-200",
  },
  pr_open: {
    label: "PR Open — Awaiting Review",
    className:
      "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-900/40 dark:text-purple-200",
  },
  escalated: {
    label: "Needs Manual Review",
    className: "bg-red-100 text-red-700 border-red-200 dark:bg-red-900/40 dark:text-red-200",
  },
  manual_pickup: {
    label: "Needs Manual Review",
    className: "bg-red-100 text-red-700 border-red-200 dark:bg-red-900/40 dark:text-red-200",
  },
  done: {
    label: "Done",
    className: "bg-green-100 text-green-700 border-green-200 dark:bg-green-900/40 dark:text-green-200",
  },
};

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  const copy = STATUS_COPY[status];
  return <Badge className={cn("border", copy.className)}>{copy.label}</Badge>;
}
