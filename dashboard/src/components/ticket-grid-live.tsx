"use client";

import { useEffect, useState } from "react";

import { TicketGrid } from "@/components/ticket-grid";
import type { TicketSummary } from "@/types/ticket";

export function TicketGridLive({
  initial,
  emptyMessage,
  streamUrl = "/api/tickets/stream",
}: {
  initial: TicketSummary[];
  emptyMessage: string;
  streamUrl?: string;
}) {
  const [tickets, setTickets] = useState(initial);

  useEffect(() => {
    const es = new EventSource(streamUrl);
    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (Array.isArray(data)) setTickets(data);
    };
    return () => es.close();
  }, [streamUrl]);

  return <TicketGrid tickets={tickets} emptyMessage={emptyMessage} />;
}
