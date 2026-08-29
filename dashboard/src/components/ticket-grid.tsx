import { TicketCard } from "@/components/ticket-card";
import type { TicketSummary } from "@/types/ticket";

export function TicketGrid({ tickets, emptyMessage }: { tickets: TicketSummary[]; emptyMessage: string }) {
  if (tickets.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {tickets.map((ticket) => (
        <TicketCard key={ticket.id} ticket={ticket} />
      ))}
    </div>
  );
}
