# Artisan — Deployment & Operations

Operational runbook for running Artisan in Google Cloud. The [README](../README.md) keeps a
shortened getting-started path; this file is the full detail: prerequisites, environment
variables, IAM grants, and build/deploy commands for every component.

## Prerequisites

- Python 3.13 (managed via `uv` — no separate install needed)
- [`uv`](https://docs.astral.sh/uv/) — Python package manager
- Node 22 LTS + [`pnpm`](https://pnpm.io/)
- A GCP project with billing enabled, and the `gcloud` CLI authenticated
- A GitHub App installed on the target repo, and a Jira Cloud site/project (see
  [CONTEXT.md](./CONTEXT.md) for the specific identifiers already provisioned for this deployment)

## Deployment topology

Two Cloud Run **services** (`orchestrator`, `dashboard`) and one Cloud Run **job**
(`execution-sandbox`), plus supporting GCP resources:

| Component | Kind | Role |
|---|---|---|
| `orchestrator` | Cloud Run service | Owns all three gates; hosts the ADK agents; calls the Jira Cloud REST API directly |
| `execution-sandbox` | Cloud Run job | Per-attempt ephemeral compute: clone repo, run the bounded coding agent, run tests, push branch |
| `dashboard` | Cloud Run service | Next.js monitoring UI, GitHub OAuth login |
| Firestore (native mode) | — | Single source of truth for per-ticket state |
| Secret Manager | — | `github-app-private-key`, `github-webhook-secret`, `jira-api-token` |
| Pub/Sub (`artisan-github-events`) | — | Webhook decoupling; at-least-once delivery |

> **Note:** an `mcp-atlassian` MCP server was deployed in Sprint 1 and deleted in Sprint 2 after
> being superseded by direct Jira REST calls (see [CONTEXT.md](./CONTEXT.md) for the diagnosis).
> The orchestrator now calls Jira Cloud's REST API directly (`agents/src/artisan_agents/jira/client.py`).

Full IaC + CI/CD automation for all services lands in Sprint 7 — see
[SPRINT.md](./SPRINT.md#sprint-7--deployment--cicd).

## Environment variables

### Orchestrator (`agents/`)

Requires GCP Application Default Credentials (`gcloud auth application-default login`) for
Firestore/Secret Manager/Pub/Sub access, and these env vars for anything beyond the Sprint 1
defaults:

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
| `GOOGLE_CLOUD_LOCATION` | Vertex AI location — **must be `global`**, not a region; `gemini-3.7-flash` isn't served from regional endpoints like `us-central1` (see [CONTEXT.md](./CONTEXT.md) Milestone 3) | `global` |
| `ARTISAN_CLOUD_RUN_REGION` | Region of the `execution-sandbox` Cloud Run Job the orchestrator triggers (Sprint 3, Gate 2) | `us-central1` |
| `ARTISAN_EXECUTION_SANDBOX_JOB_NAME` | Name of that Cloud Run Job | `execution-sandbox` |

Jira access is a direct REST API call (Basic Auth, email + `jira-api-token` from Secret Manager) —
not routed through the `mcp-atlassian` service from Sprint 1, which was deleted after being
superseded (see [CONTEXT.md](./docs/CONTEXT.md) for why).

Gemini access requires `aiplatform.googleapis.com` enabled on the project and
`roles/aiplatform.user` granted to the orchestrator's service account — see
[CONTEXT.md](./docs/CONTEXT.md) Milestone 3 for the exact commands (this wasn't a Sprint 1 default;
it was missing until Sprint 2's live field-testing caught it).

### Execution sandbox (`execution-sandbox/`)

Beyond the Sprint 1 defaults it shares with `agents/` (`ARTISAN_GCP_PROJECT_ID`,
`ARTISAN_GITHUB_APP_ID` / `ARTISAN_GITHUB_INSTALLATION_ID`):

| Var | Purpose | Default |
|---|---|---|
| `ARTISAN_CLOUD_RUN_REGION` | Used to build a Cloud Logging link for this execution's `ExecutionResult.logs_uri` | `us-central1` |
| `ARTISAN_DEMO_REPO_TEST_COMMAND` | The single test command run against the checkout — v1 is scoped to one fixed demo repo ([PRD.md §5](./PRD.md#5-non-goals--out-of-scope-v1)), so a hardcoded command is legitimate rather than generic multi-language test detection | `npm test` |

At runtime (as a Cloud Run Job execution, not a long-running service), the orchestrator's
`gcp/cloud_run_jobs.py::trigger_execution` sets `GITHUB_REPO`, `ISSUE_NUMBER`, `BRANCH_NAME`,
`ATTEMPT_NUMBER`, `PLAN_JSON`, and `PRIOR_FEEDBACK` as per-execution env var overrides — these
aren't meant to be set by hand except for a manual smoke-test trigger.

## Secrets

None of this repo's code ever takes a raw secret as a literal. Everything
(`github-app-private-key`, `github-webhook-secret`, `jira-api-token`) lives in Google Secret
Manager, scoped per-secret to the service account that needs it. See
[SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security). The dashboard's OAuth App credentials
(`GITHUB_ID` / `GITHUB_SECRET` / `AUTH_SECRET`, Sprint 5) are the one deliberate exception for now —
local-only, in `dashboard/.env.local` (gitignored) — moving them to Secret Manager is Sprint 7
deploy scope.

## Deploying the orchestrator (`agents/`)

`agents/pyproject.toml` has a `uv` workspace path dependency on `packages/artisan_shared`, so the
Docker build context must be the **repo root**, not `agents/`. `gcloud run deploy --source .` can
no longer be used directly since it doesn't support an out-of-context Dockerfile path:

```bash
# from the repo root
docker build -f agents/Dockerfile -t <your-registry>/orchestrator .
docker push <your-registry>/orchestrator
gcloud run deploy orchestrator --image <your-registry>/orchestrator --region us-central1 \
  --set-env-vars ARTISAN_PUBSUB_PUSH_AUDIENCE=<this-service-url>/pubsub/push
```

Then:

1. Point the GitHub App's webhook URL (App settings → Webhook) at
   `<orchestrator-url>/webhooks/github`.
2. Create the Pub/Sub topic and push subscription (with a dead-letter policy — see
   [CONTEXT.md](./CONTEXT.md) Milestone 3) targeting `<orchestrator-url>/pubsub/push`.

See [CONTEXT.md](./CONTEXT.md) "Known follow-up: Sprint 2 infra/deployment — done; Gate 1 verified
live end-to-end" for the exact commands and required IAM grants — none of this is automated yet;
Sprint 7 adds IaC.

## Deploying the execution sandbox (`execution-sandbox/`)

Gate 2's per-attempt Cloud Run Job — clones the repo, runs a bounded ADK coding agent against the
orchestrator's `Plan`, runs the test suite, pushes a branch, and writes the result back to
Firestore. See [SYSTEM_DESIGN.md §4](./SYSTEM_DESIGN.md#4-data-flow--gate-2-plan--execute--verify--pr).

Needs two IAM grants beyond Sprint 1's `execution-sandbox@` (`datastore.user`): `secretAccessor`
on the `github-app-private-key` secret, since this job mints its own GitHub App installation token
rather than being handed one by the orchestrator; and `aiplatform.user`, for the coding agent's own
Gemini calls (see [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security)).

Same repo-root build-context requirement as `agents/` above. Deploy as a Cloud Run Job with
`--task-timeout=1800` and `ARTISAN_DEMO_REPO_TEST_COMMAND` set (see [CONTEXT.md](./CONTEXT.md)
Milestone 5):

```bash
# from the repo root
docker build -f execution-sandbox/Dockerfile -t <your-registry>/execution-sandbox .
docker push <your-registry>/execution-sandbox
gcloud run jobs deploy execution-sandbox --image <your-registry>/execution-sandbox --region us-central1
```

### Building without a local Docker daemon

If Docker isn't available locally, `gcloud builds submit` with a small `cloudbuild.yaml`
(`docker build -f <dockerfile> -t <image> .`, repo root as context) builds the same Dockerfile in
Cloud Build and pushes automatically — this is how both images were actually built for Sprint 3's
close-out, since no local Docker daemon existed in that environment either.

## Dashboard (`dashboard/`)

**External prerequisite: a GitHub OAuth App** (separate from the GitHub App used for webhooks —
that one authenticates Artisan *to* GitHub; this one authenticates a maintainer *into* the
dashboard). Create it at GitHub → Settings → Developer settings → OAuth Apps → New OAuth App:

- Homepage URL: `http://localhost:3000`
- Authorization callback URL: `http://localhost:3000/api/auth/callback/github`

Then create `dashboard/.env.local` (gitignored):

```
GITHUB_ID=<OAuth App client id>
GITHUB_SECRET=<OAuth App client secret>
AUTH_SECRET=<run: npx auth secret>
```

Firestore access uses plain Application Default Credentials, exactly like `agents/` — no service
account key file, no extra env var:

```bash
gcloud auth application-default login
```

Sign-in itself is gated beyond "any GitHub account": the `signIn` callback checks the signed-in
user's real collaborator permission on the target repo via the GitHub API, so dashboard access
matches actual repo access (see [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security)).

```bash
cd dashboard
pnpm install
pnpm test        # Vitest + React Testing Library
pnpm build
pnpm dev          # http://localhost:3000
```

### End-to-end tests

Requires a running build. Real GitHub OAuth can't be driven headlessly, so Playwright signs in via a
test-only Credentials provider gated behind `AUTH_E2E_TEST_MODE=1` (set automatically for the test
run in `playwright.config.ts` — never set this in real local dev or in a real deployment):

```bash
cd dashboard
pnpm exec playwright install   # first run only
pnpm build
pnpm test:e2e
```
