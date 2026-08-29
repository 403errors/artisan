import { BUCKET_META, type StatusBucket } from "@/lib/ticket-status";
import { cn } from "@/lib/utils";

export function StatusDot({
  bucket,
  pulse = false,
  className,
}: {
  bucket: StatusBucket;
  pulse?: boolean;
  className?: string;
}) {
  const dotClass = BUCKET_META[bucket].dotClass;
  if (!pulse) {
    return (
      <span
        aria-hidden="true"
        className={cn("inline-block size-2 shrink-0 rounded-full", dotClass, className)}
      />
    );
  }
  return (
    <span aria-hidden="true" className={cn("relative inline-flex size-2 shrink-0", className)}>
      <span
        className={cn("absolute inset-0 rounded-full opacity-60 animate-ping", dotClass)}
      />
      <span className={cn("relative inline-block size-2 rounded-full", dotClass)} />
    </span>
  );
}
