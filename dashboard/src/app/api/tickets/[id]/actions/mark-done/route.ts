import { postManualAction } from "@/lib/ticket-actions-server";

export const runtime = "nodejs";

export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return postManualAction(id, "mark_done");
}
