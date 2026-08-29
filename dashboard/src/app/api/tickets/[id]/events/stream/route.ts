import { auth } from "@/auth";
import { getFirestore } from "@/lib/firestore";
import { sseResponse } from "@/lib/sse";
import { toTicketEvent, type RawTicketEvent } from "@/lib/tickets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session) return new Response(null, { status: 401 });

  const { id } = await params;

  return sseResponse((send) => {
    const unsubscribe = getFirestore()
      .collection("tickets")
      .doc(id)
      .collection("events")
      .orderBy("at")
      .onSnapshot(
        (snapshot) => {
          const events = snapshot.docs.map((d) => toTicketEvent(d.id, d.data() as RawTicketEvent));
          send(events);
        },
        (err) => send({ error: String(err) }),
      );
    return unsubscribe;
  }, request.signal);
}
