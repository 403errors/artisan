"use client";

import { useEffect, useState } from "react";

import { DecisionTrail } from "@/components/decision-trail";
import { EscalationHistory } from "@/components/escalation-history";
import { TicketStatusBadge } from "@/components/ticket-status-badge";
import { TraceLinks } from "@/components/trace-links";
import { githubIssueUrl, jiraTicketUrl } from "@/lib/config";
import { stepLabel } from "@/lib/format";
import type { TicketDoc } from "@/types/ticket";

const LIVE_STATUSES = new Set(["intake", "in_progress"]);

export function TicketDetailLive({ initial }: { initial: TicketDoc }) {
  const [ticket, setTicket] = useState(initial);

  useEffect(() => {
    const es = new EventSource(`/api/tickets/${initial.id}/stream`);
    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data) setTicket(data);
    };
    return () => es.close();
  }, [initial.id]);

  const showLiveStep = LIVE_STATUSES.has(ticket.status) && ticket.currentStep;

  return (
    <>
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{ticket.jiraKey}</h1>
          <TicketStatusBadge status={ticket.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          #{ticket.githubIssueNumber}
          {showLiveStep ? ` · ${stepLabel(ticket.currentStep!)}…` : ""}
        </p>
        <div className="flex items-center gap-4 text-sm">
          <a
            href={githubIssueUrl(ticket.githubRepo, ticket.githubIssueNumber)}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-4"
          >
            GitHub issue
          </a>
          <a
            href={jiraTicketUrl(ticket.jiraKey)}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-4"
          >
            Jira ticket
          </a>
          {ticket.prUrl ? (
            <a
              href={ticket.prUrl}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-4"
            >
              Pull request
            </a>
          ) : null}
        </div>
      </header>

      <DecisionTrail ticket={ticket} />
      <EscalationHistory entries={ticket.escalationHistory} />
      <TraceLinks traceIds={ticket.traceIds} />
    </>
  );
}
