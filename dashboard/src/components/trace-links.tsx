import { WaypointsIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ResourceLink } from "@/components/resource-link";
import { cloudTraceUrl } from "@/lib/config";
import type { TraceEntry } from "@/types/ticket";

export function TraceLinks({ traceIds }: { traceIds: TraceEntry[] }) {
  if (traceIds.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cloud Trace</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <ul className="flex flex-col gap-1">
          {traceIds.map(({ traceId, label }) => (
            <li key={traceId} className="flex flex-col">
              <ResourceLink variant="subtle" icon={WaypointsIcon} href={cloudTraceUrl(traceId)}>
                {label}
              </ResourceLink>
              <span className="pl-5 font-mono text-[11px] text-muted-foreground">{traceId}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
