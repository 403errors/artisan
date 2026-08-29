// Fixed locale/timezone-agnostic-enough formatting for anything rendered by a
// client component that's also SSR-ed: relying on the runtime's default
// locale (plain toLocaleString()) causes a hydration mismatch whenever the
// server and browser disagree on locale (e.g. en-US server vs en-GB browser).
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

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

const DIFF_LINE_PATTERN = /^(\+|-|@@|diff --git|index [0-9a-f]{7})/m;

// diffSummary/reason fields are sometimes a real unified diff and sometimes a
// plain LLM sentence — render the former as a code block, the latter as prose.
export function looksLikeCode(text: string): boolean {
  if (DIFF_LINE_PATTERN.test(text)) return true;
  const lines = text.split("\n");
  if (lines.length > 3) return true;
  return lines.some((line) => line.length > 120);
}
