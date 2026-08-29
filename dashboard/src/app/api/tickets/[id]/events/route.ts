import { auth } from "@/auth";
import { getFirestore } from "@/lib/firestore";
import { toTicketEvent, type RawTicketEvent } from "@/lib/tickets";

export const runtime = "nodejs";

// One-shot fallback for dashboard/src/hooks/use-ticket-events.ts, used when the SSE route (
// events/stream) fails before its first message — e.g. this route not existing yet on an older
// deployment.
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session) return new Response(null, { status: 401 });

  const { id } = await params;
  const snapshot = await getFirestore()
    .collection("tickets")
    .doc(id)
    .collection("events")
    .orderBy("at")
    .get();

  const events = snapshot.docs.map((d) => toTicketEvent(d.id, d.data() as RawTicketEvent));
  return Response.json(events);
}
