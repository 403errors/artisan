// v1 is single-repo/single-board by design (PRD.md §5 non-goal). These values are env-driven so a
// clean-machine run-through in any GCP project works (reproducible setup); the current v1 values
// remain the defaults, so nothing changes when they aren't set.
//
// Two Next.js env mechanisms (the distinction matters):
// - Server-runtime values (plain `process.env.X`): read at request/deploy time from the deployment
//   env (Cloud Run `--set-env-vars`; `.env.local` for local dev). Server-only consumers.
// - Client-visible values (`process.env.NEXT_PUBLIC_*`): inlined into the browser bundle at
//   `next build` time — set via build args in dashboard/Dockerfile (or `.env.local` before
//   `pnpm build`), never at runtime on a prebuilt image.

// --- Server-runtime (server-only consumers: auth.ts, api routes, lib/firestore.ts, lib/pubsub.ts)
export const TARGET_REPO = process.env.ARTISAN_TARGET_REPO ?? "403errors/artisan-demo";
// Same topic `agents/`'s real GitHub webhooks publish to (agents/config.py's PUBSUB_TOPIC
// default) — a manual action rides the exact same OIDC-authenticated ingress, at-least-once
// delivery, and claim_delivery idempotency as a real webhook, discriminated by envelope `kind`.
export const PUBSUB_TOPIC = process.env.ARTISAN_PUBSUB_TOPIC ?? "artisan-github-events";
// GCP project for the server-side Firestore/PubSub admin clients — falls back through
// GOOGLE_CLOUD_PROJECT (the name agents/ and the rest of the stack use) then the v1 project.
export const GCP_PROJECT_ID =
  process.env.GCP_PROJECT_ID ?? process.env.GOOGLE_CLOUD_PROJECT ?? "artisan-multiagent-ai";

// --- Client-visible (browser bundle; baked at build time, see module comment)
export const JIRA_SITE = process.env.NEXT_PUBLIC_JIRA_SITE ?? "pieisnot22by7.atlassian.net";
// Cloud Trace deep-links resolve in the viewer's own console for the project they deployed
// against. Falls back to the server project id, then the v1 project.
export const CLIENT_GCP_PROJECT_ID =
  process.env.NEXT_PUBLIC_GCP_PROJECT_ID ?? GCP_PROJECT_ID ?? "artisan-multiagent-ai";

export function githubIssueUrl(repo: string, issueNumber: number): string {
  return `https://github.com/${repo}/issues/${issueNumber}`;
}

export function jiraTicketUrl(jiraKey: string): string {
  return `https://${JIRA_SITE}/browse/${jiraKey}`;
}

export function cloudTraceUrl(traceId: string): string {
  return `https://console.cloud.google.com/traces/list?project=${CLIENT_GCP_PROJECT_ID}&tid=${traceId}`;
}
