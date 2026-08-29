import { cloudTraceUrl } from "@/lib/config";

export function TraceLinks({ traceIds }: { traceIds: string[] }) {
  if (traceIds.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-medium">Cloud Trace</h2>
      <ul className="flex flex-col gap-1">
        {traceIds.map((traceId) => (
          <li key={traceId}>
            <a
              href={cloudTraceUrl(traceId)}
              target="_blank"
              rel="noreferrer"
              className="text-sm underline underline-offset-4"
            >
              {traceId}
            </a>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Known gap (Sprint 6, Milestone 7): custom `gate.*` spans don&apos;t currently export to
        Cloud Trace, so a link above may not resolve to a visible span yet.
      </p>
    </section>
  );
}
