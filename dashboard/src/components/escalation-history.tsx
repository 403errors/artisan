import { Badge } from "@/components/ui/badge";
import type { EscalationEntry } from "@/types/ticket";

export function EscalationHistory({ entries }: { entries: EscalationEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-medium">Escalation history</h2>
      <ul className="flex flex-col gap-3">
        {entries.map((entry, i) => (
          <li key={i} className="rounded-md border p-3">
            <div className="mb-1 flex items-center gap-2">
              <Badge variant="outline">Gate {entry.gate}</Badge>
              <span className="text-xs text-muted-foreground">
                {new Date(entry.at).toLocaleString()}
              </span>
            </div>
            <p className="text-sm whitespace-pre-wrap">{entry.reason}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
