import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GateBadge } from "@/components/gate-badge";
import { PlanCard } from "@/components/plan-card";
import { ExecutionResultCard } from "@/components/execution-result-card";
import { CodeBlock } from "@/components/code-block";
import { looksLikeCode } from "@/lib/format";
import type { TicketDoc } from "@/types/ticket";

export function DecisionTrail({ ticket }: { ticket: TicketDoc }) {
  const showGate1 =
    ticket.clarificationRounds > 0 || ticket.status === "intake" || ticket.status === "manual_pickup";
  const showGate2 = ticket.domains.length > 0 || ticket.plan !== null || ticket.lastExecutionResult !== null;
  const showGate3 = ticket.lastConflictDetection !== null;

  if (!showGate1 && !showGate2 && !showGate3) return null;

  return (
    <div className="flex flex-col gap-4">
      {showGate1 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <GateBadge gate="1" showLabel />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Clarification rounds: {ticket.clarificationRounds}
            </p>
          </CardContent>
        </Card>
      ) : null}

      {showGate2 ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <GateBadge gate="2" showLabel />
          </div>
          {ticket.domains.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {ticket.domains.map((d) => (
                <Badge key={d} variant="outline">
                  {d}
                </Badge>
              ))}
            </div>
          ) : null}
          {ticket.plan ? <PlanCard plan={ticket.plan} /> : null}
          {ticket.lastExecutionResult ? (
            <ExecutionResultCard title="Latest execution attempt" result={ticket.lastExecutionResult} />
          ) : null}
        </div>
      ) : null}

      {showGate3 ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <GateBadge gate="3" showLabel />
          </div>
          {ticket.lastConflictDetection ? (
            <Card>
              <CardHeader>
                <CardTitle>
                  {ticket.lastConflictDetection.hasConflict ? "Conflict detected" : "No conflict"}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {looksLikeCode(ticket.lastConflictDetection.diffSummary) ? (
                  <CodeBlock variant="diff">{ticket.lastConflictDetection.diffSummary}</CodeBlock>
                ) : (
                  <p className="text-sm">{ticket.lastConflictDetection.diffSummary}</p>
                )}
                {ticket.lastConflictDetection.conflictedFiles.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {ticket.lastConflictDetection.conflictedFiles.map((file) => (
                      <Badge key={file} variant="outline" className="font-mono text-[11px]">
                        {file}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
          {ticket.lastConflictResolution ? (
            <ExecutionResultCard title="Trivial resolution attempt" result={ticket.lastConflictResolution} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
