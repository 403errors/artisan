import { GitPullRequestArrowIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { GateBadge } from "@/components/gate-badge";
import { LiveStepIndicator } from "@/components/live-step-indicator";
import { TicketActions } from "@/components/ticket-actions";
import { TicketStatusBadge } from "@/components/ticket-status-badge";
import { currentGate } from "@/lib/ticket-derived";
import type { TicketDoc } from "@/types/ticket";

export function TicketDetailHeader({
  ticket,
  stalled,
}: {
  ticket: TicketDoc;
  stalled: boolean;
}) {
  const gate = currentGate(ticket);
  
  // Extract just the title from "[GH#N] Title" format
  const displayTitle = ticket.jiraSummary
    ? ticket.jiraSummary.replace(/^\[GH#\d+\]\s*/, '')
    : ticket.jiraKey;
  
  return (
    <header className="flex flex-col gap-2 border-b border-border pb-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">{displayTitle}</h1>
        <TicketStatusBadge status={ticket.status} stalled={stalled} />
        <div className="ml-auto flex items-center gap-2">
          {ticket.status === "pr_open" && ticket.prUrl ? (
            <Button
              variant="default"
              size="sm"
              nativeButton={false}
              render={<a href={ticket.prUrl} target="_blank" rel="noreferrer" />}
            >
              <GitPullRequestArrowIcon />
              View PR on GitHub
            </Button>
          ) : null}
          <TicketActions ticket={ticket} />
        </div>
      </div>
      <p className="font-mono text-xs text-muted-foreground">
        #{ticket.githubIssueNumber} · {ticket.githubRepo}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <GateBadge gate={gate} />
        <LiveStepIndicator
          status={ticket.status}
          currentStep={ticket.currentStep}
          updatedAt={ticket.updatedAt}
        />
      </div>
    </header>
  );
}
