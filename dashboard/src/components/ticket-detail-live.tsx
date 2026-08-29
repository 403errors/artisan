"use client";

import { useEffect, useState } from "react";

import { DecisionTrail } from "@/components/decision-trail";
import { EscalationHistory } from "@/components/escalation-history";
import { TicketActivityFeed } from "@/components/ticket-activity-feed";
import { TicketDetailHeader } from "@/components/ticket-detail-header";
import { TicketFacts } from "@/components/ticket-facts";
import { TicketLinksCard } from "@/components/ticket-links-card";
import { TraceLinks } from "@/components/trace-links";
import { useNow } from "@/hooks/use-now";
import { isStalled } from "@/lib/ticket-status";
import type { TicketDoc } from "@/types/ticket";

export function TicketDetailLive({ initial }: { initial: TicketDoc }) {
  const [ticket, setTicket] = useState(initial);
  const now = useNow();

  useEffect(() => {
    const es = new EventSource(`/api/tickets/${initial.id}/stream`);
    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data) setTicket(data);
    };
    return () => es.close();
  }, [initial.id]);

  const stalled = isStalled({ status: ticket.status, updatedAt: ticket.updatedAt }, now);

  return (
    <div className="flex flex-col gap-6">
      <TicketDetailHeader ticket={ticket} stalled={stalled} />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-6">
          <TicketActivityFeed ticket={ticket} />
          <DecisionTrail ticket={ticket} />
        </div>
        <aside className="flex flex-col gap-4 lg:sticky lg:top-6">
          <TicketLinksCard ticket={ticket} />
          <TicketFacts ticket={ticket} />
          <EscalationHistory entries={ticket.escalationHistory} />
          <TraceLinks traceIds={ticket.traceIds} />
        </aside>
      </div>
    </div>
  );
}
