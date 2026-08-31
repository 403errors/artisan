# infra

Deployment config for Artisan: Dockerfiles, CI/CD, and IaC (Terraform preferred, `gcloud` scripts as fallback).

Populated in Sprint 7 — see [../docs/SPRINT.md](../docs/SPRINT.md#sprint-7--deployment--cicd).

Done so far (2026-08-31):

- **CI/CD is live**: `.github/workflows/ci.yml` (lint + tests + Next.js build on every push/PR) and
  `.github/workflows/deploy.yml` (rebuilds `orchestrator` + `execution-sandbox` images and
  redeploys Cloud Run on push to `main`, via Workload Identity Federation). One-time WIF +
  deployer-service-account setup and the required GitHub secrets are documented in
  [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md#automated-deploys-github-actions--gcp).
- **Dashboard deploy deferred**: the dashboard has never been on Cloud Run (local-only today).
  `dashboard/Dockerfile` (Next.js standalone) is committed and ready but not auto-deployed until
  its one-time Cloud Run config lands — see `docs/DEPLOYMENT.md` -> "Dashboard".
- **Dockerfiles**: `agents/Dockerfile`, `execution-sandbox/Dockerfile`, and the new
  `dashboard/Dockerfile` (Next.js standalone). All three use the repo root as build context.
- `scripts/create-dashboard-secrets.sh` — creates the dashboard's GitHub OAuth App credentials in
  Secret Manager and grants `dashboard@` scoped `secretAccessor` on each, closing the Sprint 6
  Phase 6.3 audit gap (see `docs/SYSTEM_DESIGN.md` §8).

Still pending (rest of Sprint 7): checked-in Terraform (or `gcloud` scripts) defining every
resource (Pub/Sub topic, Firestore db, Secret Manager secrets, Cloud Run services/jobs, IAM
bindings) in code.
