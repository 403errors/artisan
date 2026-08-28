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

This includes the orchestrator (the Cloud Run service handling Gate 1 intake — see [SYSTEM_DESIGN.md §3](./docs/SYSTEM_DESIGN.md#3-data-flow--gate-1-intake)). To run it locally:

```bash
cd agents
uv run artisan-agents   # serves on :8080 (or $PORT)
```

Requires GCP Application Default Credentials (`gcloud auth application-default login`) for Firestore/Secret Manager/Pub/Sub access, and these env vars for anything beyond the Sprint 1 defaults:

| Var | Purpose | Default |
|---|---|---|
| `ARTISAN_GCP_PROJECT_ID` | GCP project for Firestore/Secret Manager/Pub/Sub | `artisan-multiagent-ai` |
| `ARTISAN_PUBSUB_TOPIC` | Topic the ingestion route publishes to | `artisan-github-events` |
| `ARTISAN_PUBSUB_PUSH_AUDIENCE` | Expected audience on the Pub/Sub push OIDC token — must be the full push endpoint URL *including* `/pubsub/push`, since that's what Cloud Run's default push OIDC audience actually is | *(unset — set at deploy time)* |
| `ARTISAN_JIRA_URL` | Jira Cloud site base URL | `https://pieisnot22by7.atlassian.net` |
| `ARTISAN_JIRA_USERNAME` | Jira service-account email (paired with the `jira-api-token` secret, Basic Auth) | `pieisnot22by7@gmail.com` |
| `ARTISAN_JIRA_PROJECT_KEY` | Jira project tickets are created under | `ART` |
| `ARTISAN_GITHUB_APP_ID` / `ARTISAN_GITHUB_INSTALLATION_ID` | GitHub App identity for installation-token auth | Sprint 1's provisioned App/installation |
| `GOOGLE_GENAI_USE_VERTEXAI` | Routes ADK's Gemini calls through Vertex AI (no API key needed — uses ADC) instead of the Gemini Developer API | `TRUE` |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI project | `artisan-multiagent-ai` |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI location — **must be `global`**, not a region; `gemini-3.7-flash` isn't served from regional endpoints like `us-central1` (see [CONTEXT.md](./docs/CONTEXT.md) Milestone 3) | `global` |

Jira access is a direct REST API call (Basic Auth, email + `jira-api-token` from Secret Manager) — not routed through the `mcp-atlassian` service from Sprint 1, which was deleted after being superseded (see [CONTEXT.md](./docs/CONTEXT.md) for why).

Gemini access requires `aiplatform.googleapis.com` enabled on the project and `roles/aiplatform.user` granted to the orchestrator's service account — see [CONTEXT.md](./docs/CONTEXT.md) Milestone 3 for the exact commands (this wasn't a Sprint 1 default; it was missing until Sprint 2's live field-testing caught it).

Deploying to Cloud Run (`agents/Dockerfile`):

```bash
cd agents
gcloud run deploy orchestrator --source . --region us-central1 \
  --set-env-vars ARTISAN_PUBSUB_PUSH_AUDIENCE=<this-service-url>/pubsub/push
```

then point the GitHub App's webhook URL (App settings → Webhook) at `<orchestrator-url>/webhooks/github`, and create the Pub/Sub topic/push subscription (with a dead-letter policy — see [CONTEXT.md](./docs/CONTEXT.md) Milestone 3) targeting `<orchestrator-url>/pubsub/push` (see [CONTEXT.md](./docs/CONTEXT.md) "Known follow-up: Sprint 2 infra/deployment — done; Gate 1 verified live end-to-end" for the exact commands and required IAM grants — none of this is automated yet; Sprint 7 adds IaC).

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

Cloud Run (services: `orchestrator`, `dashboard`; job: `execution-sandbox`; `mcp-atlassian` was deployed in Sprint 1 and deleted in Sprint 2 after being superseded, see above). `orchestrator` has a Dockerfile and a manual `gcloud run deploy` path (see above) as of Sprint 2; full IaC + CI/CD automation for all services lands in Sprint 7 — see [SPRINT.md](./docs/SPRINT.md#sprint-7--deployment--cicd).
