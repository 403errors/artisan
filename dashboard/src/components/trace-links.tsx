import { InfoIcon, WaypointsIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ResourceLink } from "@/components/resource-link";
import { cloudTraceUrl } from "@/lib/config";

export function TraceLinks({ traceIds }: { traceIds: string[] }) {
  if (traceIds.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cloud Trace</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <ul className="flex flex-col gap-1">
          {traceIds.map((traceId) => (
            <li key={traceId}>
              <ResourceLink variant="subtle" icon={WaypointsIcon} href={cloudTraceUrl(traceId)}>
                <span className="font-mono">{traceId}</span>
              </ResourceLink>
            </li>
          ))}
        </ul>
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <InfoIcon aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
          Known gap (Sprint 6, Milestone 7): custom `gate.*` spans don&apos;t currently export to
          Cloud Trace, so a link above may not resolve to a visible span yet.
        </p>
      </CardContent>
    </Card>
  );
}
