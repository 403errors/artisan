import { CircleCheckIcon, CircleXIcon, ScrollTextIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/code-block";
import { ResourceLink } from "@/components/resource-link";
import { looksLikeCode } from "@/lib/format";
import type { ExecutionResult } from "@/types/ticket";

export function ExecutionResultCard({
  title,
  result,
}: {
  title: string;
  result: ExecutionResult;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        <Badge
          variant={result.testsPassed ? undefined : "destructive"}
          className={result.testsPassed ? "bg-status-resolved/15 text-status-resolved" : undefined}
        >
          {result.testsPassed ? <CircleCheckIcon /> : <CircleXIcon />}
          {result.testsPassed ? "Tests passed" : "Tests failed"}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Branch: <span className="font-mono text-xs">{result.branch}</span>
        </p>
        {looksLikeCode(result.diffSummary) ? (
          <CodeBlock variant="diff">{result.diffSummary}</CodeBlock>
        ) : (
          <p className="text-sm">{result.diffSummary}</p>
        )}
        {result.logsUri ? (
          <ResourceLink variant="subtle" icon={ScrollTextIcon} href={result.logsUri}>
            View full logs
          </ResourceLink>
        ) : null}
      </CardContent>
    </Card>
  );
}
