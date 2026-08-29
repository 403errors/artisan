// v1 is single-repo/single-board by design (PRD.md §5 non-goal) — hardcoded, not an env override.
export const TARGET_REPO = "403errors/artisan-demo";
export const JIRA_SITE = "pieisnot22by7.atlassian.net";
export const GCP_PROJECT_ID = "artisan-multiagent-ai";
// Same topic `agents/`'s real GitHub webhooks publish to (agents/config.py's PUBSUB_TOPIC
// default) — a manual action rides the exact same OIDC-authenticated ingress, at-least-once
// delivery, and claim_delivery idempotency as a real webhook, discriminated by envelope `kind`.
export const PUBSUB_TOPIC = "artisan-github-events";

export function githubIssueUrl(repo: string, issueNumber: number): string {
  return `https://github.com/${repo}/issues/${issueNumber}`;
}

export function jiraTicketUrl(jiraKey: string): string {
  return `https://${JIRA_SITE}/browse/${jiraKey}`;
}

export function cloudTraceUrl(traceId: string): string {
  return `https://console.cloud.google.com/traces/list?project=${GCP_PROJECT_ID}&tid=${traceId}`;
}
