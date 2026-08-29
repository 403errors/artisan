export function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

// "executing (attempt 2)" -> "Executing (attempt 2)"; "domain_expert" -> "Domain Expert"
export function stepLabel(step: string): string {
  const [head, ...rest] = step.split(" ");
  const label = head
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
  return rest.length ? `${label} ${rest.join(" ")}` : label;
}
