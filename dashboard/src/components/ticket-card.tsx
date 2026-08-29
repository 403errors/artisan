"use client";

import { CircleDotIcon, GitPullRequestArrowIcon, SquareKanbanIcon } from "lucide-react";
import { useRouter } from "next/navigation";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TicketStatusBadge } from "@/components/ticket-status-badge";
import { LiveStepIndicator } from "@/components/live-step-indicator";
import { ResourceLink } from "@/components/resource-link";
import { githubIssueUrl, jiraTicketUrl } from "@/lib/config";
import { relativeTime } from "@/lib/format";
import { useNow } from "@/hooks/use-now";
import { bucketOf, isStalled } from "@/lib/ticket-status";
import type { TicketSummary } from "@/types/ticket";

const BORDER_ACCENT: Record<string, string> = {
  active: "border-l-status-active",
  review: "border-l-status-review",
  urgent: "border-l-status-urgent",
  resolved: "border-l-status-resolved",
};

export function TicketCard({ ticket }: { ticket: TicketSummary }) {
  const router = useRouter();
  const now = useNow();
  const bucket = bucketOf(ticket.status);
  const stalled = isStalled({ status: ticket.status, updatedAt: ticket.updatedAt }, now);
  const href = `/tickets/${ticket.id}`;

  return (
    <Card
      role="link"
      tabIndex={0}
      aria-label={`View ${ticket.jiraKey}`}
      data-bucket={bucket}
      onClick={() => router.push(href)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          router.push(href);
        }
      }}
      className={`cursor-pointer border-l-2 ${BORDER_ACCENT[bucket]} transition-shadow hover:shadow-md hover:ring-foreground/20`}
    >
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <p className="font-medium">{ticket.jiraKey}</p>
          <p className="text-sm text-muted-foreground">#{ticket.githubIssueNumber}</p>
        </div>
        <TicketStatusBadge status={ticket.status} stalled={stalled} />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <span>Gate {ticket.currentGate}</span>
          <LiveStepIndicator
            status={ticket.status}
            currentStep={ticket.currentStep}
            updatedAt={ticket.updatedAt}
          />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <ResourceLink
            variant="chip"
            icon={CircleDotIcon}
            href={githubIssueUrl(ticket.githubRepo, ticket.githubIssueNumber)}
            onClick={(e) => e.stopPropagation()}
          >
            Issue
          </ResourceLink>
          <ResourceLink
            variant="chip"
            icon={SquareKanbanIcon}
            href={jiraTicketUrl(ticket.jiraKey)}
            onClick={(e) => e.stopPropagation()}
          >
            Jira
          </ResourceLink>
          {ticket.prUrl ? (
            <ResourceLink
              variant="chip"
              icon={GitPullRequestArrowIcon}
              href={ticket.prUrl}
              onClick={(e) => e.stopPropagation()}
            >
              PR
            </ResourceLink>
          ) : null}
          <span className="ml-auto text-muted-foreground">{relativeTime(ticket.updatedAt)}</span>
        </div>
      </CardContent>
    </Card>
  );
}
