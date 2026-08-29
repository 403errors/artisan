import { auth } from "@/auth";
import { getTicket } from "@/lib/tickets";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session) return new Response(null, { status: 401 });

  const { id } = await params;
  const ticket = await getTicket(id);
  if (!ticket) return new Response(null, { status: 404 });
  return Response.json(ticket);
}
