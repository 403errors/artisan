import { listEscalatedTickets } from "@/lib/tickets";
import { requireSession } from "@/lib/require-session";
import { DashboardNav } from "@/components/dashboard-nav";
import { TicketGridLive } from "@/components/ticket-grid-live";

export const dynamic = "force-dynamic";

export default async function EscalationsPage() {
  await requireSession();
  const tickets = await listEscalatedTickets();

  return (
    <>
      <DashboardNav />
      <main className="mx-auto max-w-6xl p-8">
        <h1 className="mb-6 text-2xl font-semibold">Awaiting human review</h1>
        <TicketGridLive
          initial={tickets}
          emptyMessage="Nothing is waiting on a human right now."
          streamUrl="/api/tickets/stream?status=escalated,manual_pickup"
          showFilter={false}
        />
      </main>
    </>
  );
}
