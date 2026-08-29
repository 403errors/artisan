import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { TicketDoc } from "@/types/ticket";

function ExecutionResultCard({
  title,
  result,
}: {
  title: string;
  result: { branch: string; diffSummary: string; testsPassed: boolean; logsUri: string };
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-1 flex items-center gap-2">
        <p className="font-medium">{title}</p>
        <Badge variant={result.testsPassed ? "default" : "destructive"}>
          {result.testsPassed ? "Tests passed" : "Tests failed"}
        </Badge>
      </div>
      <p className="text-sm text-muted-foreground">Branch: {result.branch}</p>
      <p className="mt-1 text-sm whitespace-pre-wrap">{result.diffSummary}</p>
      <a href={result.logsUri} target="_blank" rel="noreferrer" className="text-xs underline underline-offset-4">
        View full logs
      </a>
    </div>
  );
}

export function DecisionTrail({ ticket }: { ticket: TicketDoc }) {
  const showGate1 = ticket.clarificationRounds > 0 || ticket.status === "intake" || ticket.status === "manual_pickup";
  const showGate2 = ticket.domains.length > 0 || ticket.plan !== null || ticket.lastExecutionResult !== null;
  const showGate3 = ticket.lastConflictDetection !== null;

  return (
    <div className="flex flex-col gap-8">
      {showGate1 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-medium">Gate 1 — Intake</h2>
          <p className="text-sm text-muted-foreground">
            Clarification rounds: {ticket.clarificationRounds}
          </p>
        </section>
      ) : null}

      {showGate1 && showGate2 ? <Separator /> : null}

      {showGate2 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Gate 2 — Plan → Execute → Verify</h2>
          {ticket.domains.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {ticket.domains.map((d) => (
                <Badge key={d} variant="outline">
                  {d}
                </Badge>
              ))}
            </div>
          ) : null}
          {ticket.plan ? (
            <div className="rounded-md border p-3">
              <p className="mb-1 font-medium">Plan</p>
              <ul className="list-inside list-disc text-sm">
                {ticket.plan.steps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                Touched files: {ticket.plan.touchedFiles.join(", ")}
              </p>
              <p className="text-xs text-muted-foreground">
                Test cases: {ticket.plan.testCases.join(", ")}
              </p>
              <p className="text-xs text-muted-foreground">
                Doc updates: {ticket.plan.docUpdates.join(", ")}
              </p>
            </div>
          ) : null}
          {ticket.lastExecutionResult ? (
            <ExecutionResultCard title="Latest execution attempt" result={ticket.lastExecutionResult} />
          ) : null}
          <p className="text-sm text-muted-foreground">Retry count: {ticket.retryCount}</p>
        </section>
      ) : null}

      {showGate2 && showGate3 ? <Separator /> : null}

      {showGate3 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Gate 3 — Merge Conflict Triage</h2>
          {ticket.lastConflictDetection ? (
            <div className="rounded-md border p-3">
              <p className="mb-1 font-medium">
                {ticket.lastConflictDetection.hasConflict ? "Conflict detected" : "No conflict"}
              </p>
              <p className="text-sm whitespace-pre-wrap">{ticket.lastConflictDetection.diffSummary}</p>
              {ticket.lastConflictDetection.conflictedFiles.length > 0 ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Conflicted files: {ticket.lastConflictDetection.conflictedFiles.join(", ")}
                </p>
              ) : null}
            </div>
          ) : null}
          {ticket.lastConflictResolution ? (
            <ExecutionResultCard title="Trivial resolution attempt" result={ticket.lastConflictResolution} />
          ) : null}
          <p className="text-sm text-muted-foreground">
            Trivial-conflict attempts: {ticket.trivialConflictAttempts}
          </p>
        </section>
      ) : null}
    </div>
  );
}
