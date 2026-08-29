import { randomUUID } from "crypto";

import { auth } from "@/auth";
import { getTicket } from "@/lib/tickets";
import { publishManualAction, type ManualActionKind } from "@/lib/pubsub";

// Shared by the three actions/* route files — same auth check, ticket lookup, envelope shape,
// and fire-and-forget 202 response for all of them; only the action kind (and an optional
// reason) differs per route.
export async function postManualAction(
  ticketId: string,
  action: ManualActionKind,
  reason?: string,
): Promise<Response> {
  const session = await auth();
  if (!session) return new Response(null, { status: 401 });

  const ticket = await getTicket(ticketId);
  if (!ticket) return new Response(null, { status: 404 });

  const actionId = randomUUID();
  await publishManualAction({
    kind: "manual_action",
    action_id: actionId,
    action,
    repo: ticket.githubRepo,
    issue_number: ticket.githubIssueNumber,
    actor: session.login ?? session.user?.name ?? "unknown",
    ...(reason ? { reason } : {}),
  });

  return Response.json({ actionId }, { status: 202 });
}
