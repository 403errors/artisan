import { listTickets } from "@/lib/tickets";
import { requireSession } from "@/lib/require-session";
import { DashboardNav } from "@/components/dashboard-nav";
import { TicketGridLive } from "@/components/ticket-grid-live";
import { BUCKET_ORDER, type StatusBucket } from "@/lib/ticket-status";

export const dynamic = "force-dynamic";

function parseBuckets(show: string | undefined): StatusBucket[] {
  if (!show) return [];
  const requested = show.split(",");
  return BUCKET_ORDER.filter((bucket) => requested.includes(bucket));
}

export default async function TicketsPage({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  await requireSession();
  const tickets = await listTickets();
  const { show } = await searchParams;

  return (
    <>
      <DashboardNav />
      <main className="mx-auto max-w-6xl p-8">
        <h1 className="mb-6 text-2xl font-semibold">Tickets</h1>
        <TicketGridLive
          initial={tickets}
          emptyMessage="No tickets yet."
          initialBuckets={parseBuckets(show)}
        />
      </main>
    </>
  );
}
