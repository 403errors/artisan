// Pure derivations off a TicketDoc — deliberately has NO import of
// `@/lib/firestore` (unlike `@/lib/tickets.ts`), because it's imported by
// client components. Importing anything from `@/lib/tickets` in a client
// component pulls @google-cloud/firestore's gRPC transport into the browser
// bundle (it needs Node's `tls`/`net`, which the client build can't resolve).
import type { TicketDoc } from "@/types/ticket";

const GATE2_STEPS = new Set([
  "routing",
  "domain_expert",
  "planning",
  "executing",
  "verifying",
  "opening_pr",
]);
const GATE3_STEPS = new Set(["detecting_conflict", "classifying_conflict", "resolving_conflict"]);

function stepPrefix(step: string | null): string | null {
  return step ? step.split(" ")[0] : null;
}

export function currentGate(doc: TicketDoc): "1" | "2" | "3" {
  const prefix = stepPrefix(doc.currentStep);
  if (prefix && GATE3_STEPS.has(prefix)) return "3";
  if (prefix && GATE2_STEPS.has(prefix)) return "2";
  if (doc.status === "intake" || doc.status === "duplicate_review") return "1";
  const lastGate = doc.escalationHistory.at(-1)?.gate;
  if (lastGate) return lastGate;
  if (doc.lastConflictDetection) return "3";
  if (doc.prUrl) return "2";
  return "1";
}

export function lastDecision(doc: TicketDoc): string {
  const lastEscalation = doc.escalationHistory.at(-1);
  if (
    doc.status === "escalated" ||
    doc.status === "manual_pickup" ||
    doc.status === "needs_human_review"
  ) {
    return lastEscalation?.reason ?? "awaiting manual pickup";
  }
  if (doc.status === "duplicate_review") return "awaiting duplicate confirmation";
  if (doc.status === "pr_open") return `PR opened: ${doc.prUrl}`;
  if (doc.status === "done") return "merged";
  return doc.status;
}
