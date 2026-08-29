import { auth } from "@/auth";
import { listTickets } from "@/lib/tickets";

export const runtime = "nodejs";

export async function GET() {
  const session = await auth();
  if (!session) return new Response(null, { status: 401 });

  const tickets = await listTickets();
  return Response.json(tickets);
}
