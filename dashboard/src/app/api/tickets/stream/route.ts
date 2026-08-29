import type { Query } from "@google-cloud/firestore";

import { auth } from "@/auth";
import { getFirestore } from "@/lib/firestore";
import { TARGET_REPO } from "@/lib/config";
import { sseResponse } from "@/lib/sse";
import { toTicketDoc, toTicketSummary, type RawTicketDoc } from "@/lib/tickets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const session = await auth();
  if (!session) return new Response(null, { status: 401 });

  const statusFilter = new URL(request.url).searchParams.get("status")?.split(",");

  return sseResponse((send) => {
    let query: Query = getFirestore().collection("tickets").where("github_repo", "==", TARGET_REPO);
    if (statusFilter) query = query.where("status", "in", statusFilter);
    const unsubscribe = query.onSnapshot(
        (snapshot) => {
          const tickets = snapshot.docs.map((d) =>
            toTicketSummary(toTicketDoc(d.id, d.data() as RawTicketDoc)),
          );
          send(tickets);
        },
        (err) => send({ error: String(err) }),
      );
    return unsubscribe;
  }, request.signal);
}
