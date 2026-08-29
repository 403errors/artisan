import { BookOpenIcon, FileDiffIcon, FlaskConicalIcon, ListChecksIcon, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Plan } from "@/types/ticket";

function GroupLabel({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
      <Icon aria-hidden="true" className="size-3" />
      {label}
    </p>
  );
}

// For short, file-path-like items — rendered as mono pills.
function ChipGroup({ icon, label, items }: { icon: LucideIcon; label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <GroupLabel icon={icon} label={label} />
      <div className="flex flex-wrap gap-1">
        {items.map((item) => (
          <Badge key={item} variant="outline" className="font-mono text-[11px]">
            {item}
          </Badge>
        ))}
      </div>
    </div>
  );
}

// For sentence-length items (test case descriptions, doc-update notes) — a
// pill would either overflow its container or force ugly mid-word wrapping,
// so these read as a normal wrapped list instead.
function TextGroup({ icon, label, items }: { icon: LucideIcon; label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <GroupLabel icon={icon} label={label} />
      <ul className="list-inside list-disc text-sm">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function PlanCard({ plan }: { plan: Plan }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <ListChecksIcon aria-hidden="true" className="size-4" />
          Plan
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ol className="list-inside list-decimal text-sm">
          {plan.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        <ChipGroup icon={FileDiffIcon} label="Touched files" items={plan.touchedFiles} />
        <TextGroup icon={FlaskConicalIcon} label="Test cases" items={plan.testCases} />
        <TextGroup icon={BookOpenIcon} label="Doc updates" items={plan.docUpdates} />
      </CardContent>
    </Card>
  );
}
