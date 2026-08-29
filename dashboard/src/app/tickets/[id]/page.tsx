import Link from "next/link";
import { notFound } from "next/navigation";

import { DashboardNav } from "@/components/dashboard-nav";
import { TicketDetailLive } from "@/components/ticket-detail-live";
import { getTicket } from "@/lib/tickets";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function TicketDetailPage({ params }: { params: Promise<{ id: string }> }) {
  await requireSession();
  const { id } = await params;
  const ticket = await getTicket(id);
  if (!ticket) notFound();

  return (
    <>
      <DashboardNav />
      <main className="mx-auto flex max-w-3xl flex-col gap-8 p-8">
        <div>
          <Link href="/tickets" className="text-sm underline underline-offset-4">
            ← All tickets
          </Link>
        </div>
        <TicketDetailLive initial={ticket} />
      </main>
    </>
  );
}
