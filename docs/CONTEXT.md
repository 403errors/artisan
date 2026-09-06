# Artisan — Living Context

Purpose: a single, always-current snapshot of what actually exists in this codebase right now. Rewrite this file after every major milestone so it always reflects current state — never append chronologically. Git history is the record of *how* we got here; this file is the record of *where we are*. (Pre-v2 sprint/milestone narrative was removed in the 2026-09 cleanup; see git history of this file.)

## Current Status (as of 2026-09-06)

**Stage: v1 shipped (all 3 gates live + dashboard + CI/CD); v2 in progress on branch `v2` (`main` frozen).** v2 waves 1, 1.5, 1.6, 1.7 are done code-side: model bumped to `gemini-3.8-flash`, 10-lens domain-expert registry, routing/verification hardening, full-funnel eval harness + external bench adapter, eval-driven hardening (expert precision split, verification criteria hard-gate, sibling-omission fixtures). **The v2 changes are not yet deployed** — they take effect on the next `orchestrator`/`execution-sandbox` deploy from `v2`.

Roadmap and wave scope live in `docs/miscellaneous/V2_SCOPE.md` (local-only, gitignored). Next up: **#7 per-repo build/test matrix** (last wave-1 item), then the first external bench run (manual — see `agents/evals/bench/README.md`).

## Benchmarks

Latest full-funnel eval run (live Gemini, **2026-09-06**, wave 1.7 record run; per-stage detail in `agents/evals/PIPELINE_REPORT.md`):

| Stage | Metric | Value |
|---|---|---|
| Routing | exact-set match (28 goldens × 3 reps) | **100.0%** (stability 96.0%) |
| Domain expert | file precision / modify-recall / hallucination | **60.4%** / 93.8% / **0.0%** |
| Verification | verdict agreement / criteria agreement (16 scenarios × 2 reps) | **100%** / **100%** (criteria hard-gate enabled) |
| End-to-end | verified-correct rate (11 seeded-bug fixtures) | **100.0%** — false-green 0.0% |
| External bench | SWE-bench Verified/Multilingual/Pro/Live, Multi-SWE-bench, SWE-PolyBench | adapter ready, 50 frozen instances each — **no official run yet** |

Unit tests (2026-09-06): **409 Python** (agents 308, artisan_shared 41, execution-sandbox 60) + **110 dashboard** (Vitest), all green in CI.

## What Exists Right Now

- `agents/` (uv, Python 3.13) — the orchestrator. FastAPI (`app.py`: `POST /webhooks/github` with HMAC verify, `POST /pubsub/push` with OIDC verify + claim-based idempotency); Gate 1 intake + duplicate check (`dispatch.py`); Gate 2 plan→execute→verify→PR with retry cap (`gate2.py`); Gate 3 merge-conflict triage (`gate3.py`); manual actions + completion (`manual_actions.py`, `completion.py`); five reasoning ADK agents under `agents/agents/` sharing `_run_agent.py`; Jira direct REST (`jira/client.py`); GitHub App auth (`github/`); Firestore (`gcp/firestore_client.py`); OTel → Cloud Trace (`tracing.py`, `force_flush` per gate span). Deployed on Cloud Run as `orchestrator`.
- `execution-sandbox/` (uv, Python 3.13) — Cloud Run Job, `JOB_MODE`-branched (`execute` / `detect_conflict` / `resolve_conflict`). Bounded ADK coding agent with custom function tools (fail-closed shell allowlist), subprocess `git_ops.py`, `test_runner.py`, pre-push `security_scan.py` (gitleaks hard-block, semgrep ERROR-gate, both fail-open on missing binary). Shared auth/secrets come from `artisan_shared`.
- `packages/artisan_shared/` — typed inter-agent models, `TicketDoc` Firestore schema, deterministic ticket/PR-pointer id scheme, `prompt_safety` (untrusted-content wrapping), GitHub App auth + Secret Manager helpers.
- `dashboard/` — Next.js 15 + Auth.js v5: ticket grid, gate-by-gate drill-in, `/escalations`, SSE live updates, manual actions (retry/escalate/mark-done) published onto the same Pub/Sub topic as real webhooks. Deployed on Cloud Run as `dashboard`.
- `infra/` — full Terraform topology (`infra/terraform/`) + one-command bootstrap (`infra/scripts/setup-gcp-infra.sh`); CI (`.github/workflows/ci.yml`) and WIF-based deploy (`.github/workflows/deploy.yml`) for all three services.
- Event log: `tickets/{id}/events` Firestore subcollection (secrets redacted, `EVENT_LOG_ENABLED` kill switch, `NoOpEventSink` default).

## External Accounts & Identifiers

- **GCP project:** `artisan-multiagent-ai` (`us-central1`). Services: `orchestrator` (Cloud Run service, public ingress for GitHub webhooks, 3600s timeout, `orchestrator@`), `execution-sandbox` (Cloud Run Job, 1800s task timeout, `execution-sandbox@`), `dashboard` (Cloud Run service, `dashboard@`).
- **Model:** `gemini-3.8-flash` via Vertex AI (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_LOCATION=global` — Gemini flash models are served from `global` only, not regional endpoints).
- **Pub/Sub:** topic `artisan-github-events` + push subscription (600s ack deadline, OIDC) + DLQ `artisan-github-events-dlq` (`max-delivery-attempts=5`).
- **Firestore:** native mode; `tickets/`, `tickets/{id}/events`, `processed_deliveries/` (claim → `in_progress`/`completed`/`failed`), `pr_index/` (`{repo}__{prNumber}` → ticket doc), `repo_context/` cache (6h TTL). Composite indexes on `(github_repo, updated_at)` and `(github_repo, status, updated_at)`.
- **Secrets (Secret Manager, per-secret IAM):** `jira-api-token`, `github-webhook-secret`, `github-app-private-key` (→ `orchestrator@`); `dashboard-oauth-client-id`/`dashboard-oauth-client-secret`/`dashboard-auth-secret` (→ `dashboard@`).
- **Jira:** site `pieisnot22by7.atlassian.net`, project `ART` (team-managed Kanban; only `Backlog`/`Selected for Development`/`In Progress`/`Done` — no PR-shaped status, so Gate 2 communicates PR-open via comment; Firestore `TicketDoc.status` is the real source of truth).
- **GitHub:** App `artisan-bot-403errors` (App ID `4744770`, installation `157129507` on `403errors`); demo repo `403errors/artisan-demo`; source repo `403errors/artisan`. Dashboard sign-in = separate OAuth App; access requires collaborator permission on the target repo.
- **Key constants:** retry cap `N=3` (mirrors clarification-round cap); `DELIVERY_CLAIM_STALE_AFTER_SECONDS=4200` (must exceed the 3600s request timeout); `MAX_TRIVIAL_CONFLICT_ATTEMPTS=1` (claimed with `>`, not `>=`); `MAX_CODING_AGENT_TOOL_CALLS=40`.
- **Images:** built via Cloud Build into the `cloud-run-source-deploy` Artifact Registry repo (no local Docker daemon in the dev environment).

## Open Decisions / Risks

- **Gate 3 never auto-recovers an `escalated` ticket** even if a human's manual fix makes a re-check come clean — a manual re-check/un-escalate action is a separately-scoped feature (new write-authorization question, no Gate-3 re-entry point today).
- **No mechanism reacts to an unrelated PR merging into a base branch** out from under an open Artisan PR (no such PR-side webhook exists; a `synchronize` on the Artisan PR is what triggers re-check).
- **Expert modify-recall at 93.8%** (union-guard 100%) — accepted: the planner sees both file lists, so nothing is lost.
- **Non-retriable failure classification is case-by-case** (GitHub 404 → ack + issue-deleted cleanup is handled); other permanent-failure classes still rely on the DLQ as sole backstop.
- **v2 undeployed** — model bump and prompt/hardening changes only take effect on the next deploy from `v2`.
