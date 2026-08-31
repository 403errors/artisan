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

Full IaC (Terraform in `infra/terraform/` and bootstrap script in `infra/scripts/setup-gcp-infra.sh`)
and CI/CD automation (`.github/workflows/deploy.yml`) cover all three services (`orchestrator`,
`execution-sandbox`, `dashboard`).

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

Then copy `dashboard/.env.example` to `dashboard/.env.local` (gitignored) and fill in the values:

```
GITHUB_ID=<OAuth App client id>
GITHUB_SECRET=<OAuth App client secret>
AUTH_SECRET=<run: npx auth secret>

# Server-runtime config (optional — defaults match the v1 deployment)
ARTISAN_TARGET_REPO=403errors/artisan-demo
ARTISAN_PUBSUB_TOPIC=artisan-github-events
GCP_PROJECT_ID=artisan-multiagent-ai

# Client-visible config — baked into the browser bundle at `pnpm build` time
NEXT_PUBLIC_JIRA_SITE=pieisnot22by7.atlassian.net
NEXT_PUBLIC_GCP_PROJECT_ID=artisan-multiagent-ai
```

### Config: runtime vs build-time

The dashboard reads its repo/board/project configuration from env vars (see `dashboard/.env.example`),
split across Next.js's two mechanisms:

- **Server-runtime** (`ARTISAN_TARGET_REPO`, `ARTISAN_PUBSUB_TOPIC`, `GCP_PROJECT_ID`): read at
  request/deploy time. On Cloud Run set these with `--set-env-vars`; locally from `.env.local`.
- **Client-visible** (`NEXT_PUBLIC_JIRA_SITE`, `NEXT_PUBLIC_GCP_PROJECT_ID`): inlined into the
  browser bundle at `pnpm build` — set before building (`--build-arg` in `dashboard/Dockerfile`, or
  `.env.local` before a local build). A prebuilt image cannot be re-pointed at a different Jira
  site / Cloud Trace project without a rebuild.

Firestore access uses plain Application Default Credentials, exactly like `agents/` — no service
account key file, no extra env var:

```bash
gcloud auth application-default login
```

Sign-in itself is gated beyond "any GitHub account": the `signIn` callback in `auth.ts` calls `hasRepoAccess` (`dashboard/src/lib/github-auth.ts`), which checks:
1. Designated hackathon evaluator emails (`testing@devpost.com`, `cloudhackathons@google.com`, `testing@challengepost.com`) against both public profile and verified emails API (`/user/emails`).
2. Actual collaborator permission on the target repository (`GET /repos/{owner}/{repo}/collaborators/{username}/permission`) using the OAuth access token.

This ensures both hackathon judges and repository maintainers have access while rejecting unauthenticated third parties. Cloud Trace access for `group:testing@devpost.com` and `group:cloudhackathons@google.com` is provisioned with `roles/cloudtrace.user` on the GCP project.

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

## Automated deploys (GitHub Actions → GCP)

A `push` to `main` now rebuilds the deployed images and redeploys Cloud Run via
`.github/workflows/deploy.yml` (Workload Identity Federation — no long-lived keys). Images are
tagged with the commit SHA in the `cloud-run-source-deploy` Artifact Registry repo (`us-central1`):

| Component | Image | Deploy |
|---|---|---|
| `orchestrator` | `…/cloud-run-source-deploy/orchestrator:<sha>` | `gcloud run deploy orchestrator --image …` |
| `execution-sandbox` | `…/cloud-run-source-deploy/execution-sandbox:<sha>` | `gcloud run jobs deploy execution-sandbox --image …` |
| `dashboard` | `…/cloud-run-source-deploy/dashboard:<sha>` | `gcloud run deploy dashboard --image …` |

Deploying with `--image` only preserves each component's existing env vars, service account, and
timeout — a push can never silently drop configuration. `workflow_dispatch` is also wired in so a
deploy can be re-run from the Actions tab.

### One-time setup (run once per GCP project)

1. **Deployer service account + roles:**

   ```bash
   export PROJECT_ID=artisan-multiagent-ai
   gcloud config set project $PROJECT_ID

   gcloud iam service-accounts create github-actions-deployer \
     --display-name="GitHub Actions deployer"
   export DEPLOYER_SA="github-actions-deployer@$PROJECT_ID.iam.gserviceaccount.com"

   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:$DEPLOYER_SA" --role="roles/artifactregistry.writer"
   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:$DEPLOYER_SA" --role="roles/run.admin"
   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:$DEPLOYER_SA" --role="roles/iam.serviceAccountUser"
   ```

2. **Workload Identity pool + GitHub OIDC provider:**

   ```bash
   gcloud iam workload-identity-pools create github-actions \
     --location=global --display-name="GitHub Actions"
   export WIP_ID="$(gcloud iam workload-identity-pools describe github-actions \
     --location=global --format='value(name)')"

   gcloud iam workload-identity-pools providers create-oidc github \
     --location=global --workload-identity-pool=github-actions \
     --display-name="GitHub" \
     --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
     --attribute-condition="assertion.repository_owner == '403errors'" \
     --issuer-uri="https://token.actions.githubusercontent.com"

   gcloud iam service-accounts add-iam-policy-binding $DEPLOYER_SA \
     --role="roles/iam.workloadIdentityUser" \
     --member="principalSet://iam.googleapis.com/$WIP_ID/attribute.repository/403errors/artisan"
   ```

3. **GitHub repository secrets** (Settings → Secrets and variables → Actions):

   | Secret | Value |
   |---|---|
   | `GCP_SERVICE_ACCOUNT` | `github-actions-deployer@artisan-multiagent-ai.iam.gserviceaccount.com` |
   | `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<NUMBER>/locations/global/workloadIdentityPools/github-actions/providers/github` |

   Get `<NUMBER>` with `gcloud projects describe $PROJECT_ID --format='value(projectNumber)'`.

   The GCP project id (`artisan-multiagent-ai`) is hardcoded in the workflow — it's the same
   constant used throughout the repo, so it needs no secret of its own.

### Notes

- **Path-filtered**: `deploy.yml` only runs when a push touches deploy-relevant paths
  (`agents/`, `execution-sandbox/`, `packages/artisan_shared/`, `pyproject.toml`, `uv.lock`,
  `.dockerignore`, or the workflow file itself). Docs-only or dashboard-only pushes skip deploys
  entirely; `workflow_dispatch` forces one regardless.
- The deploy workflow runs in **parallel** with the CI workflow on the same push. To gate deploys
  on CI passing first, switch `deploy.yml`'s trigger to a `workflow_run` of `ci.yml`.
- Deploying with `--image` only preserves each component's existing env vars, service account,
  and timeout — a push can never silently drop configuration.
- `workflow_dispatch` is wired in, so a deploy can be re-run from the Actions tab.
- The dashboard image (when it's enabled) is a Next.js standalone build; runtime env comes from
  Cloud Run, never the image.

## CI / testing without GCP credentials

GitHub Actions (`.github/workflows/ci.yml`) runs the whole suite on runners with **no Application
Default Credentials** and no GCP metadata server, so anything that would construct a real Google
Cloud client must not crash the tests:

- `tracing.setup_tracing()` degrades gracefully: if ADC is unavailable it logs a warning and skips
  Cloud Trace registration instead of raising `DefaultCredentialsError` (`gate_span` then runs on
  OpenTelemetry's no-op tracer). The app also boots this way in any non-GCP environment.
- The real-Firestore integration tests (`agents/tests/test_firestore_client.py`,
  `test_firestore_schema.py`) self-skip via `_require_credentials()` when no credentials exist;
  every other GCP touchpoint in the unit tests is stubbed/faked (autouse conftest fixtures stub the
  Firestore event sink and `tracing.setup_tracing`; Pub/Sub, Secret Manager, and Cloud Run Jobs
  clients are only ever faked).
- The dashboard job's `pnpm/action-setup@v4` step points `package_json_file` at
  `dashboard/package.json` (the repo root is a Python/uv workspace with no `package.json`), so the
  action reads the pinned `packageManager: pnpm@10.28.2` instead of failing with
  "No pnpm version is specified".

If real-Firestore coverage is ever needed in CI, add a dedicated job that runs the Firestore
emulator and exports `FIRESTORE_EMULATOR_HOST` — not required today.
