# Artisan

An expert co-developer that closes the loop between your coding-agent fleet and Jira.

Full product context lives in [`docs/`](./docs): [PRD.md](./docs/PRD.md) (what/why), [SYSTEM_DESIGN.md](./docs/SYSTEM_DESIGN.md) (how), [TECH_STACK.md](./docs/TECH_STACK.md) (exact versions), [SPRINT.md](./docs/SPRINT.md) (sprint plan), [CONTEXT.md](./docs/CONTEXT.md) (current state — read this first).

## Repo layout

```
agents/            Python — orchestrator + all ADK agents
execution-sandbox/ Python — Cloud Run Job image (Execution Agent runtime)
dashboard/         TypeScript — Next.js monitoring dashboard
infra/             Deploy config (Dockerfiles, Terraform/gcloud)
docs/              Living project docs
```

## Prerequisites

- Python 3.13 (managed via `uv` — no separate install needed)
- [`uv`](https://docs.astral.sh/uv/) — Python package manager
- Node 22 LTS + [`pnpm`](https://pnpm.io/)
- A GCP project with billing enabled, and the `gcloud` CLI authenticated
- A GitHub App installed on the target repo, and a Jira Cloud site/project (see [CONTEXT.md](./docs/CONTEXT.md) for the specific identifiers already provisioned for this deployment)

## Setup

### Agents (`agents/`)

```bash
cd agents
uv sync
uv run pytest
```

### Execution sandbox (`execution-sandbox/`)

```bash
cd execution-sandbox
uv sync
uv run pytest
```

### Dashboard (`dashboard/`)

```bash
cd dashboard
pnpm install
pnpm test        # Vitest + React Testing Library
pnpm build
pnpm dev          # http://localhost:3000
```

End-to-end tests (requires a running build):

```bash
cd dashboard
pnpm exec playwright install   # first run only
pnpm test:e2e
```

## Secrets

None of this repo's code ever takes a raw secret as a literal. Everything (`github-app-private-key`, `github-webhook-secret`, `jira-api-token`) lives in Google Secret Manager, scoped per-secret to the service account that needs it. See [SYSTEM_DESIGN.md §8](./docs/SYSTEM_DESIGN.md#8-auth--security).

## Deployment

Cloud Run (services: `orchestrator`, `mcp-atlassian`, `dashboard`; job: `execution-sandbox`). Deployment automation lands in Sprint 7 — see [SPRINT.md](./docs/SPRINT.md#sprint-7--deployment--cicd).
