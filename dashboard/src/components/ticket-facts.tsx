import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GateBadge } from "@/components/gate-badge";
import { formatDateTime } from "@/lib/format";
import { currentGate } from "@/lib/ticket-derived";
import type { TicketDoc } from "@/types/ticket";

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="text-sm tabular-nums">{value}</dd>
    </div>
  );
}

export function TicketFacts({ ticket }: { ticket: TicketDoc }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Details</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3">
          <Fact label="Gate" value={<GateBadge gate={currentGate(ticket)} />} />
          <Fact label="Current step" value={ticket.currentStep} />
          <Fact label="Retries" value={ticket.retryCount} />
          <Fact label="Clarification rounds" value={ticket.clarificationRounds} />
          <Fact label="Conflict attempts" value={ticket.trivialConflictAttempts} />
          <Fact
            label="Branch"
            value={
              ticket.lastExecutionResult ? (
                <span className="font-mono text-xs" title={ticket.lastExecutionResult.branch}>
                  {ticket.lastExecutionResult.branch}
                </span>
              ) : null
            }
          />
          <Fact label="Pull request" value={ticket.prNumber ? `#${ticket.prNumber}` : null} />
          <Fact label="Created" value={formatDateTime(ticket.createdAt)} />
          <Fact label="Updated" value={formatDateTime(ticket.updatedAt)} />
        </dl>
      </CardContent>
    </Card>
  );
}
