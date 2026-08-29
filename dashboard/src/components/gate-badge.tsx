import { GitMergeIcon, InboxIcon, WrenchIcon, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const GATE_META: Record<"1" | "2" | "3", { name: string; icon: LucideIcon }> = {
  "1": { name: "Intake", icon: InboxIcon },
  "2": { name: "Plan → Execute → Verify", icon: WrenchIcon },
  "3": { name: "Merge-conflict triage", icon: GitMergeIcon },
};

export function GateBadge({
  gate,
  showLabel = false,
}: {
  gate: "1" | "2" | "3";
  showLabel?: boolean;
}) {
  const { name, icon: Icon } = GATE_META[gate];
  return (
    <Tooltip>
      <TooltipTrigger render={<span className="inline-flex" />}>
        <Badge variant="outline" className="gap-1">
          <Icon aria-hidden="true" />
          Gate {gate}
          {showLabel ? ` — ${name}` : ""}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{name}</TooltipContent>
    </Tooltip>
  );
}
