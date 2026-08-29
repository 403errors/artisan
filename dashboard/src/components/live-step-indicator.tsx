import { TriangleAlertIcon } from "lucide-react";

import { StatusDot } from "@/components/status-dot";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useNow } from "@/hooks/use-now";
import { relativeTime, stepLabel } from "@/lib/format";
import { isActivelyWorking, isLive, isStalled } from "@/lib/ticket-status";
import type { TicketStatus } from "@/types/ticket";

interface LiveStepIndicatorProps {
  status: TicketStatus;
  currentStep: string | null;
  updatedAt: string;
  currentGate?: "1" | "2" | "3";
  className?: string;
}

// Renders one of three states: actively working (pulsing), stalled (no
// Firestore update in a while — likely crashed/hung, this is where the retry
// action becomes discoverable), or nothing when the ticket isn't live.
export function LiveStepIndicator({
  status,
  currentStep,
  updatedAt,
  currentGate,
  className,
}: LiveStepIndicatorProps) {
  const now = useNow();
  if (!isLive(status)) return null;

  const gatePrefix = currentGate ? `Gate ${currentGate} · ` : "";

  if (isActivelyWorking({ status, updatedAt }, now)) {
    return (
      <span className={`inline-flex items-center gap-1.5 text-sm text-status-active ${className ?? ""}`}>
        <StatusDot bucket="active" pulse />
        {gatePrefix}
        Working{currentStep ? ` · ${stepLabel(currentStep)}…` : "…"}
      </span>
    );
  }

  if (isStalled({ status, updatedAt }, now)) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <span
              className={`inline-flex items-center gap-1.5 text-sm text-muted-foreground ${className ?? ""}`}
            />
          }
        >
          <StatusDot bucket="active" />
          <TriangleAlertIcon className="size-3.5" aria-hidden="true" />
          {gatePrefix}
          Stalled at {currentStep ? stepLabel(currentStep) : "unknown step"} ·{" "}
          {relativeTime(updatedAt)}
        </TooltipTrigger>
        <TooltipContent>
          No agent activity for a while — Artisan may be stuck. Consider retrying this gate.
        </TooltipContent>
      </Tooltip>
    );
  }

  return null;
}
