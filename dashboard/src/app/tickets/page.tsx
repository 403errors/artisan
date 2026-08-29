import { listTickets } from "@/lib/tickets";
import { requireSession } from "@/lib/require-session";
import { DashboardNav } from "@/components/dashboard-nav";
import { TicketGridLive } from "@/components/ticket-grid-live";

export const dynamic = "force-dynamic";

export default async function TicketsPage() {
  await requireSession();
  const tickets = await listTickets();

  return (
    <>
      <DashboardNav />
      <main className="mx-auto max-w-6xl p-8">
        <h1 className="mb-6 text-2xl font-semibold">Tickets</h1>
        <TicketGridLive initial={tickets} emptyMessage="No tickets yet." />
      </main>
    </>
  );
}
