"use client";

import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/status-dot";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { BUCKET_META, BUCKET_ORDER, type StatusBucket } from "@/lib/ticket-status";

export function TicketFilterBar({
  counts,
  selected,
  onChange,
  total,
  hiddenActiveCount,
  onShowActive,
}: {
  counts: Record<StatusBucket, number>;
  selected: StatusBucket[];
  onChange: (next: StatusBucket[]) => void;
  total: number;
  hiddenActiveCount: number;
  onShowActive: () => void;
}) {
  return (
    <div className="mb-4 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup
          multiple
          variant="outline"
          size="sm"
          value={selected}
          onValueChange={(next) => onChange(next as StatusBucket[])}
        >
          {BUCKET_ORDER.map((bucket) => {
            const meta = BUCKET_META[bucket];
            const count = counts[bucket] ?? 0;
            return (
              <ToggleGroupItem key={bucket} value={bucket} disabled={count === 0}>
                <StatusDot bucket={bucket} pulse={bucket === "active" && count > 0} />
                {meta.label}
                <span className="tabular-nums text-muted-foreground">{count}</span>
              </ToggleGroupItem>
            );
          })}
        </ToggleGroup>
        {selected.length === 0 ? (
          <span className="text-sm text-muted-foreground">Showing all {total}</span>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onChange([])}>
            <XIcon aria-hidden="true" />
            Clear
          </Button>
        )}
      </div>
      {hiddenActiveCount > 0 ? (
        <p className="text-xs text-muted-foreground">
          {hiddenActiveCount} {hiddenActiveCount === 1 ? "ticket is" : "tickets are"} being worked
          right now —{" "}
          <button
            type="button"
            onClick={onShowActive}
            className="underline underline-offset-4 hover:text-foreground"
          >
            Show
          </button>
        </p>
      ) : null}
    </div>
  );
}
