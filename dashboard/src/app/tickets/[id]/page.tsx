import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Button } from "@/components/ui/button";
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
      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
        <div>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/tickets" />}>
            <ArrowLeftIcon aria-hidden="true" />
            All tickets
          </Button>
        </div>
        <TicketDetailLive initial={ticket} />
      </main>
    </>
  );
}
