import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/status-dot";
import { BUCKET_META, bucketOf } from "@/lib/ticket-status";
import { cn } from "@/lib/utils";
import type { TicketStatus } from "@/types/ticket";

const STATUS_LABEL: Record<TicketStatus, string> = {
  intake: "Triaging",
  in_progress: "Being Handled by Artisan",
  pr_open: "PR Open — Awaiting Review",
  escalated: "Needs Manual Review",
  manual_pickup: "Needs Manual Review",
  needs_human_review: "Needs Human Review",
  duplicate_review: "Duplicate Check",
  done: "Done",
};

export function TicketStatusBadge({
  status,
  stalled = false,
}: {
  status: TicketStatus;
  stalled?: boolean;
}) {
  const bucket = bucketOf(status);
  const meta = BUCKET_META[bucket];
  return (
    <Badge
      variant={stalled ? "outline" : undefined}
      className={cn("border gap-1.5", !stalled && meta.softClass)}
    >
      <StatusDot bucket={stalled ? "active" : bucket} />
      {STATUS_LABEL[status]}
    </Badge>
  );
}
