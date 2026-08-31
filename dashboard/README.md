# Artisan — Monitoring Dashboard

The human-facing view of [Artisan](https://github.com/403errors/artisan) (the autonomous
issue-to-PR agent): a Next.js 15 (App Router) + React 19 + TypeScript (strict) + Tailwind 4 app
that shows live ticket state across all three gates, lets a maintainer drill into any ticket's
full decision trail, and surfaces anything awaiting a human. See the root
[README](../README.md), [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) (ops runbook), and
[docs/SYSTEM_DESIGN.md §6.3](../docs/SYSTEM_DESIGN.md) for architecture context.

## Prerequisites

- Node 22 LTS + [`pnpm`](https://pnpm.io/) (`packageManager: pnpm@10.28.2` — use `corepack enable`
  if you don't have this exact version)
- A GCP project with the same Firestore data as the agents (native mode, `us-central1`), reachable
  via Application Default Credentials
- A GitHub OAuth App (see below)

## Setup

1. Install dependencies:

   ```bash
   pnpm install
   ```

2. **Create a GitHub OAuth App** — separate from the GitHub App used for webhooks (that one
   authenticates Artisan *to* GitHub; this one authenticates a maintainer *into* the dashboard).
   GitHub → Settings → Developer settings → OAuth Apps → New OAuth App:
   - Homepage URL: `http://localhost:3000`
   - Authorization callback URL: `http://localhost:3000/api/auth/callback/github`

3. **Create `.env.local`** (gitignored) from the committed example and fill it in:

   ```bash
   cp .env.example .env.local
   ```

   ```bash
   GITHUB_ID=<OAuth App client id>
   GITHUB_SECRET=<OAuth App client secret>
   AUTH_SECRET=<run: npx auth secret>
   ```

   The remaining vars in `.env.example` (`ARTISAN_TARGET_REPO`, `ARTISAN_PUBSUB_TOPIC`,
   `GCP_PROJECT_ID`, `NEXT_PUBLIC_JIRA_SITE`, `NEXT_PUBLIC_GCP_PROJECT_ID`) default to the v1
   deployment — change them only when pointing the dashboard at a different repo/board/project.

4. **GCP access**: the server uses Application Default Credentials (same as the Python services —
   no service-account key file anywhere in this repo):

   ```bash
   gcloud auth application-default login
   ```

5. Run it:

   ```bash
   pnpm dev        # http://localhost:3000
   ```

> Sign-in is gated beyond "any GitHub account": the `signIn` callback checks the signed-in user's
> real collaborator permission on the target repo (`ARTISAN_TARGET_REPO`) via the GitHub API, so
> dashboard access matches actual repo access. Use a real host/port or set `AUTH_TRUST_HOST=true`
> (the default `trustHost: true` config covers `localhost`).

## Config: runtime vs build-time

The dashboard reads its repo/board/project configuration from env vars (see
[`.env.example`](./.env.example)), split across Next.js's two mechanisms:

- **Server-runtime** (`ARTISAN_TARGET_REPO`, `ARTISAN_PUBSUB_TOPIC`, `GCP_PROJECT_ID`): read at
  request/deploy time — from `.env.local` locally, `--set-env-vars` on Cloud Run.
- **Client-visible** (`NEXT_PUBLIC_JIRA_SITE`, `NEXT_PUBLIC_GCP_PROJECT_ID`): inlined into the
  browser bundle at `pnpm build` time — set before building. A prebuilt image cannot be re-pointed
  at a different Jira site / Cloud Trace project without a rebuild.

## Scripts

| Command | What it does |
|---|---|
| `pnpm dev` | Dev server (`next dev --turbopack`) |
| `pnpm build` | Production build (`next build --turbopack`) |
| `pnpm start` | Serve a production build (`next start`) |
| `pnpm lint` | ESLint |
| `pnpm test` | Vitest + React Testing Library (unit/component) |
| `pnpm test:e2e` | Playwright end-to-end specs (see below) |

## Tests

Unit/component tests (`pnpm test`) need no external services. The Playwright e2e suite
(`pnpm test:e2e`) runs against a production build and needs browser binaries once
(`pnpm exec playwright install`). Real GitHub OAuth can't be driven headlessly, so e2e signs in via
a test-only Credentials provider gated behind `AUTH_E2E_TEST_MODE=1` — set automatically in
`playwright.config.ts`, **never** set it outside test runs.

```bash
pnpm build
pnpm test:e2e
```

## Deployment

Deployed to Cloud Run as the `dashboard` service via `dashboard/Dockerfile` (Next.js standalone
output). Full runbook — including the one-time GitHub OAuth + Secret Manager wiring and the
runtime-vs-build-time env split — lives in [docs/DEPLOYMENT.md → Dashboard](../docs/DEPLOYMENT.md#dashboard-dashboard).
