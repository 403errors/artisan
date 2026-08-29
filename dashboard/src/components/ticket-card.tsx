"use client";

import { useRouter } from "next/navigation";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TicketStatusBadge } from "@/components/ticket-status-badge";
import { githubIssueUrl, jiraTicketUrl } from "@/lib/config";
import { relativeTime, stepLabel } from "@/lib/format";
import type { TicketSummary } from "@/types/ticket";

const LIVE_STATUSES = new Set(["intake", "in_progress"]);

export function TicketCard({ ticket }: { ticket: TicketSummary }) {
  const router = useRouter();
  const showLiveStep = LIVE_STATUSES.has(ticket.status) && ticket.currentStep;
  const href = `/tickets/${ticket.id}`;

  return (
    <Card
      role="link"
      tabIndex={0}
      aria-label={`View ${ticket.jiraKey}`}
      onClick={() => router.push(href)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          router.push(href);
        }
      }}
      className="cursor-pointer transition-shadow hover:shadow-md"
    >
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <p className="font-medium">{ticket.jiraKey}</p>
          <p className="text-sm text-muted-foreground">#{ticket.githubIssueNumber}</p>
        </div>
        <TicketStatusBadge status={ticket.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Gate {ticket.currentGate}
          {showLiveStep ? ` · ${stepLabel(ticket.currentStep!)}…` : ""}
        </p>
        <div className="flex items-center gap-3 text-xs">
          <a
            href={githubIssueUrl(ticket.githubRepo, ticket.githubIssueNumber)}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="underline underline-offset-4"
          >
            Issue
          </a>
          <a
            href={jiraTicketUrl(ticket.jiraKey)}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="underline underline-offset-4"
          >
            Jira
          </a>
          {ticket.prUrl ? (
            <a
              href={ticket.prUrl}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="underline underline-offset-4"
            >
              PR
            </a>
          ) : null}
          <span className="ml-auto text-muted-foreground">{relativeTime(ticket.updatedAt)}</span>
        </div>
      </CardContent>
    </Card>
  );
}
