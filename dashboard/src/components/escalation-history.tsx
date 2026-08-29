import { ShieldAlertIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GateBadge } from "@/components/gate-badge";
import { CodeBlock } from "@/components/code-block";
import { formatDateTime, looksLikeCode } from "@/lib/format";
import type { EscalationEntry } from "@/types/ticket";

export function EscalationHistory({ entries }: { entries: EscalationEntry[] }) {
  if (entries.length === 0) return null;
  const newestFirst = [...entries].reverse();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Escalations</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="relative flex flex-col gap-4 before:absolute before:top-2 before:bottom-2 before:left-[11px] before:w-px before:bg-border">
          {newestFirst.map((entry, i) => (
            <li key={i} className="relative flex gap-3 pl-8">
              <span className="absolute left-0 top-0 flex size-6 shrink-0 items-center justify-center rounded-full bg-status-urgent/10 text-status-urgent ring-1 ring-status-urgent/25">
                <ShieldAlertIcon aria-hidden="true" className="size-3.5" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2">
                  <GateBadge gate={entry.gate} />
                  <span className="text-xs text-muted-foreground">{formatDateTime(entry.at)}</span>
                </div>
                {looksLikeCode(entry.reason) ? (
                  <CodeBlock>{entry.reason}</CodeBlock>
                ) : (
                  <p className="text-sm">{entry.reason}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
