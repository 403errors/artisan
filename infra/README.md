# infra

Deployment config for Artisan: Dockerfiles, IaC (Terraform preferred, `gcloud` scripts as fallback).

Populated in Sprint 7 — see [../docs/SPRINT.md](../docs/SPRINT.md#sprint-7--deployment--cicd).

One script exists ahead of Sprint 7: `scripts/create-dashboard-secrets.sh` — creates the dashboard's GitHub OAuth App credentials in Secret Manager and grants `dashboard@` scoped `secretAccessor` on each, closing the Sprint 6 Phase 6.3 audit gap (see `docs/SYSTEM_DESIGN.md` §8). Everything else (Dockerfiles, Cloud Run/Pub/Sub/Firestore IaC, CI/CD) is still an empty scaffold for now.
