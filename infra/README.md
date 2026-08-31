# infra

Deployment configuration and Infrastructure as Code for Artisan: Dockerfiles, CI/CD, and Terraform definitions / `gcloud` provisioning scripts.

Populated in Sprint 7 — see [../docs/SPRINT.md](../docs/SPRINT.md#sprint-7--deployment--cicd).

## Contents

- **`terraform/`** — Declarative Terraform manifests defining the complete GCP infrastructure topology:
  - `versions.tf` / `variables.tf` / `outputs.tf` — Terraform configuration, variables, and output URLs/identifiers.
  - `apis.tf` — Enables all required Google Cloud APIs (Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace, Vertex AI, Artifact Registry, etc.).
  - `service_accounts.tf` — Four least-privilege service accounts (`orchestrator`, `execution-sandbox`, `dashboard`, `github-actions-deployer`).
  - `iam.tf` — Scoped IAM role bindings per service account.
  - `pubsub.tf` — Pub/Sub topics (`artisan-github-events`, `artisan-github-events-dlq`) and push subscription (`artisan-github-events-push` with DLQ + max 5 attempts + 600s ack deadline + OIDC).
  - `firestore.tf` — Native-mode Firestore database and composite query indexes.
  - `secrets.tf` — Secret Manager secrets with scoped `secretAccessor` permissions per service account.
  - `cloud_run.tf` — Cloud Run services (`orchestrator`, `dashboard`) and Cloud Run job (`execution-sandbox`).
  - `wif.tf` — Workload Identity Federation (WIP `github-actions` + OIDC provider `github`) for GitHub Actions.

- **`scripts/`**:
  - `setup-gcp-infra.sh` — One-command idempotent bash script to bootstrap all GCP infrastructure from zero-to-one using `gcloud`.
  - `create-dashboard-secrets.sh` — Creates dashboard OAuth App credentials in Secret Manager and grants `dashboard@` scoped `secretAccessor`.

- **Dockerfiles**:
  - `agents/Dockerfile` — Multi-stage `uv` build for `orchestrator` service.
  - `execution-sandbox/Dockerfile` — Multi-stage build with Python 3.13, `uv`, `git`, `gitleaks` v8.21.2, and `semgrep`.
  - `dashboard/Dockerfile` — Multi-stage Next.js 15 standalone build for `dashboard` service.

- **CI/CD (`.github/workflows/`)**:
  - `ci.yml` — Automated linting (ruff, eslint), Python workspace test suites (316 tests), dashboard tests (110 vitest tests), and Next.js build.
  - `deploy.yml` — Automated build, push to Artifact Registry, and deployment of all three services (`orchestrator`, `execution-sandbox`, `dashboard`) on push to `main` via Workload Identity Federation.
