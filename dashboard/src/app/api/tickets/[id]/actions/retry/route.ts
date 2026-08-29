import { postManualAction } from "@/lib/ticket-actions-server";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const gate = body?.gate as "1" | "2" | "3" | undefined;
  const action = gate === "1" ? "retry_gate1" : gate === "3" ? "retry_gate3" : "retry_gate2";
  return postManualAction(id, action);
}
