# Artisan — Living Context

Purpose: a single, always-current snapshot of what actually exists in this codebase right now. Update this file after every major milestone — not chronologically-append-only, but rewritten so it always reflects current state. Git history is the record of *how* we got here; this file is the record of *where we are*.

## Current Status (as of 2026-08-28)

**Stage: Sprint 2 deployed; Jira integration switched from mcp-atlassian to direct REST after a live field-test failure.** All infra is live: Pub/Sub topic + push subscription created, orchestrator deployed to Cloud Run, GitHub App webhook URL pointed at it, IAM wired. A real GitHub issue opened on `403errors/artisan-demo` was confirmed flowing through webhook → Pub/Sub → dispatch → the point of calling Jira — where it hit an unresolved auth bug in the pinned `mcp-atlassian` image (see "Known follow-up" below). Jira access has been rewritten to call the Jira Cloud REST API directly instead; that change is tested (34 passing tests) but not yet redeployed/re-verified against a real issue as of this doc's last edit — that's the immediate next step.

- [PRD.md](./PRD.md), [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md), [TECH_STACK.md](./TECH_STACK.md), and [SPRINT.md](./SPRINT.md) are finalized and reflect the full v1 vision (all 3 gates, full dashboard), phased into 8 sprints.
- Repo layout: single monorepo (`agents/`, `execution-sandbox/`, `dashboard/`, `infra/`, `docs/`).
- Target submission: All Things Agentic Hackathon 2026, deadline August 31, 2026.

## What Exists Right Now

- `agents/` (uv, Python 3.13): Sprint 1's scaffold (`config.py`, `models.py` — now 7 typed contracts including `GitHubWebhookEnvelope`, `firestore_schema.py`) plus Sprint 2's orchestrator code:
  - `app.py` — FastAPI service, two routes: `POST /webhooks/github` (HMAC signature verification, publishes to Pub/Sub) and `POST /pubsub/push` (OIDC push-token verification, idempotency check, dispatch).
  - `dispatch.py` — Gate 1 control flow: ticket bootstrap, Intake Agent invocation, clarification loop with the 3-round cap, gate-decision tracing.
  - `gcp/` — `secrets.py` (Secret Manager), `pubsub.py` (publish + push-token verification), `firestore_client.py` (ticket CRUD + the transactional `clarification_rounds` cap + the `processed_deliveries` idempotency guard).
  - `github/` — `webhook.py` (signature verify + envelope parsing), `auth.py` (App JWT → installation token via `githubkit`'s `AppAuthStrategy`), `client.py` (post comment, read issue thread).
  - `jira/client.py` — direct Jira Cloud REST API v2 calls (`httpx`, Basic Auth with `ARTISAN_JIRA_USERNAME` + the `jira-api-token` secret). Originally implemented against `mcp-atlassian` over MCP; switched after a live field-test failure (see "Known follow-up" below).
  - `agents/intake_agent.py` — real ADK `Agent` (`output_schema=IntakeVerdict`), run per-invocation via a fresh `Runner`/`InMemorySessionService` session (stateless between calls, per SYSTEM_DESIGN.md §7).
  - `tracing.py` — OTel `TracerProvider` + `CloudTraceSpanExporter`, one span per gate decision.
  - `Dockerfile` + `.dockerignore` — multi-stage `uv` build, deployed to Cloud Run as the `orchestrator` service.
  - 34 passing pytest tests (`uv run pytest`), including live round-trips against the real Firestore DB (ticket CRUD, the clarification-round cap hitting `manual_pickup` on the 3rd round, the delivery-idempotency guard), FastAPI route tests for both endpoints, and mocked-`httpx` tests for the Jira REST client.
  - Pinned deps: `fastapi==0.141.1`, `uvicorn[standard]==0.52.4`, `httpx==0.28.1`, `githubkit[auth-app]==0.16.1` (the `auth-app` extra pulls in `pyjwt`, needed for GitHub App JWT signing — this was previously present only as an incidental transitive dependency of the now-removed `mcp` package, and had to be added explicitly once `mcp` was dropped).
- `execution-sandbox/`, `dashboard/`: unchanged since Sprint 1.
- Firestore native-mode database in `artisan-multiagent-ai` (region `us-central1`) — now also holds a top-level `processed_deliveries` collection (Phase 2.1's pre-ticket idempotency guard) alongside `tickets/`.
- **Deployed to GCP:** Pub/Sub topic `artisan-github-events` + push subscription `artisan-github-events-push`; orchestrator Cloud Run service (public ingress for `/webhooks/github`, in-app OIDC check protects `/pubsub/push`); GitHub App webhook URL pointed at the deployed orchestrator. `mcp-atlassian` was deployed in Sprint 1 and **deleted** in Sprint 2 once superseded (see below) — it pulled a public image, so nothing custom was lost.

## Known follow-up: mcp-atlassian dropped after a live field-test failure

Sprint 1 deferred live MCP-protocol verification of `mcp-atlassian` to "once the orchestrator exists and calls it Cloud-Run-to-Cloud-Run." That happened in Sprint 2 — and surfaced a real, unresolved bug in the pinned `sooperset/mcp-atlassian:0.23.1` image itself, not a config or credentials problem on our side:

- Networking was fine once `mcp-atlassian`'s ingress was opened from `internal` to `all` (Cloud Run's `ingress: internal` only accepts traffic that routes through Google's internal VPC network, and by default a Cloud Run service's outbound calls to *another* Cloud Run service's public URL do **not** count as internal, even same-project — this needs a Serverless VPC Access connector to actually work as "internal," which wasn't provisioned. Since IAM auth — `roles/run.invoker` scoped to `orchestrator@` only — still fully gated access, opening ingress didn't weaken the actual security property).
- Once reachable, the real MCP session (initialize → tools/call) worked correctly, and `mcp-atlassian` correctly routed the `jira_create_issue` tool call.
- But `mcp-atlassian` itself then failed with `401 Unauthorized` calling Atlassian's own `/rest/api/2/myself` — **with two different, independently-verified-valid API tokens** (each confirmed working via a direct `curl -u email:token` REST call, both immediately after rotating them in Secret Manager and after forcing a fresh Cloud Run revision to pick up each new secret version). This rules out a bad/expired token; the failure is inside `mcp-atlassian`'s own Jira-auth code path (its traceback shows it runs Jira calls through an SSRF-protection hook, `attach_ssrf_hook=True`, which appears to interfere with outbound Basic Auth in this environment) — a third-party image bug, not something fixable from our side without much deeper investigation.

**Resolution:** `jira/client.py` now calls the Jira Cloud REST API directly (same credentials, same Secret Manager token, Basic Auth) — proven reliable throughout this diagnosis. `mcp-atlassian` was deleted. If MCP-based tool access is ever wanted again (e.g. for a future domain-expert agent), it would need either a from-scratch re-implementation or a different pinned image version, and should be smoke-tested against real Jira auth *before* being wired into the orchestrator's critical path again.

## Known follow-up: Sprint 2 infra/deployment — done, full end-to-end verification pending

Deployed: Pub/Sub topic + subscription, orchestrator Cloud Run service, IAM grants (`orchestrator@` → `iam.serviceAccountTokenCreator` for Pub/Sub's push-service-agent, needed for push-auth token minting — this was *not* auto-granted by `--push-auth-service-account` and had to be added explicitly), GitHub App webhook URL. Verified live: webhook signature verification (401 on forged signature), Pub/Sub publish → push delivery → OIDC verification → dispatch (confirmed with both a no-op `pull_request` event and a real `issues opened` event that correctly reached the Jira call before failing on the now-resolved `mcp-atlassian` bug above). **Not yet re-verified**: a full happy-path run using the new direct-REST Jira client — the fix is written and tested locally (34 passing tests) but hasn't been redeployed and re-verified against a real Jira ticket creation yet as of this doc's last edit. That's the immediate next step, not a deployment gap.

## Milestone Log

### Milestone 0 — Planning (2026-08-28)
Wrote PRD, system design, and tech stack docs. Key decisions locked in:
- ADK agents in Python; dashboard in Next.js/React (TypeScript).
- Jira via `mcp-atlassian` service account (not per-user Jira login).
- GitHub via a GitHub App; dashboard login via GitHub OAuth.
- Execution Agent runs in ephemeral Cloud Run Jobs, one per attempt.
- Single monorepo, greenfield.

### Milestone 1 — Sprint 1 complete: infra + scaffold (2026-08-28)
Provisioned every external prerequisite (GCP project `artisan-multiagent-ai`, 3 least-privilege service accounts, 3 secrets, Jira project `ART`, GitHub App + demo repo), scaffolded all 3 code directories with passing tests/builds, created the Firestore native-mode DB, and deployed `mcp-atlassian` to Cloud Run. See "External accounts & identifiers" above for exact IDs. Forced decisions: `mcp-atlassian` pinned to 0.23.1, retry cap `N=3`, `google-adk` pinned to 2.8.0. One item deferred to Sprint 2: live MCP-protocol verification of `mcp-atlassian`, since testing an internal-ingress service from outside GCP isn't the real call path.

### Milestone 2 — Sprint 2 built + deployed: Gate 1 intake pipeline (2026-08-28)
Implemented all 5 phases of Gate 1 in `agents/`: webhook ingestion + Pub/Sub publish (`app.py`, `github/webhook.py`, `gcp/pubsub.py`), ticket bootstrap (`dispatch.py`, `gcp/firestore_client.py`, `jira/client.py`), the Intake Agent as a real ADK `Agent` (`agents/intake_agent.py`), the clarification loop with the transactional 3-round cap (`gcp/firestore_client.py::increment_clarification_round`), and per-gate-decision OTel tracing (`tracing.py`). Deployed to GCP: Pub/Sub topic/subscription, orchestrator Cloud Run service, IAM grants, GitHub App webhook URL pointed at the live endpoint. A real test issue confirmed the pipeline works end-to-end through webhook verification, Pub/Sub delivery, and dispatch — which is also how the `mcp-atlassian` bug (see "Known follow-up" above) got caught: found by field-testing, not by guessing. Switched Jira access to direct REST API calls as a result; `mcp-atlassian` deleted. Forced decisions: (1) two HTTP routes on one orchestrator service — `/webhooks/github` verifies+publishes, `/pubsub/push` verifies+dispatches; (2) the Firestore transactional-cap function returns a `(count, at_cap)` tuple rather than raising inside the transaction, since a Firestore transactional callable's writes only commit on normal return — raising inside it would have rolled back the very cap-flip it was supposed to persist; (3) Cloud Run's default Pub/Sub push OIDC audience is the *full push endpoint URL including path* (`.../pubsub/push`), not just the service origin — caught via a live 401 during the first push-subscription smoke test; (4) dropped `mcp-atlassian` for direct Jira REST after two independently-valid API tokens both failed identically through it (see "Known follow-up" above) — a third-party image bug, not fixable from our side in the time available. 34 pytest tests pass, including live Firestore round-trips and mocked-`httpx` Jira client tests. Next: redeploy + re-verify a full real-issue-to-real-Jira-ticket run with the new client, then Sprint 3 (Gate 2 — Plan → Execute → Verify → PR).

*(Add the next milestone below as it completes — keep entries short: what shipped, what decisions it forced, what's next.)*

## External accounts & identifiers (Sprint 1, Phases 1.1–1.3 — done)

- **GCP project:** `artisan-multiagent-ai`, billing linked (`My Billing Account 2`). APIs enabled: Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace, Logging, Cloud Build, IAM, Artifact Registry.
- **Service accounts:** `orchestrator@` (datastore.user, pubsub.editor, secretAccessor, run.developer, + `iam.serviceAccountTokenCreator` for Pub/Sub's push service agent — added in Sprint 2), `execution-sandbox@` (datastore.user), `dashboard@` (datastore.viewer) — all least-privilege per [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security).
- **Secrets in Secret Manager:** `jira-api-token`, `github-webhook-secret`, `github-app-private-key` — all scoped to `orchestrator@` only via per-secret IAM bindings. `jira-api-token` has been rotated twice during Sprint 2 debugging (versions 1–3 all `enabled`); current value confirmed working via direct REST call.
- **Jira:** site `pieisnot22by7.atlassian.net`, project key `ART` (id 10034), team-managed Kanban template. Orchestrator authenticates directly as the Atlassian account `pieisnot22by7@gmail.com` + its API token (Basic Auth, REST) — no MCP intermediary as of Sprint 2.
- **GitHub:** demo repo `403errors/artisan-demo` (seeded with a README). GitHub App `artisan-bot-403errors`, App ID `4744770`, installed on `403errors` (installation id `157129507`). Webhook URL now points at the deployed orchestrator's `/webhooks/github` (updated from the Sprint 1 placeholder in Sprint 2).
- **Orchestrator Cloud Run service:** deployed in `us-central1`, public ingress (required for GitHub to reach `/webhooks/github`; `/pubsub/push` is separately protected by in-app OIDC verification), runs as `orchestrator@`.
- **Retry cap `N` = 3** (decided during Phase 1.5, matches the clarification-round cap).

## Open Decisions / Risks

- The direct-REST Jira client (`jira/client.py`) is tested locally (34 passing tests, mocked `httpx`) but hasn't yet been re-verified end-to-end against a real GitHub issue since replacing `mcp-atlassian` — do that before considering Sprint 2 fully closed.
- Two Jira API tokens were pasted in plaintext into a terminal session during debugging (now sitting in that session's history/scrollback) — recommend rotating `jira-api-token` one more time from a clean terminal once Sprint 2 is confirmed working, so no exposed value stays live.
- Local Node is v23.7.0, not the TECH_STACK-pinned 22 LTS — worked fine for scaffold/build; revisit if a Node-version-specific issue surfaces later.
- Repo is git-initialized locally but nothing committed or pushed yet — no GitHub remote chosen for the actual Artisan source repo (distinct from the throwaway `403errors/artisan-demo` target repo).

## Next Milestone Target

**Close out Sprint 2**: redeploy the orchestrator with the direct-REST Jira client, re-run the real-issue smoke test, confirm an actual `ART-*` ticket is created and the full Gate 1 happy path (clarification and sufficient-context branches) works against the live system. Then **Sprint 3 — Gate 2 (Plan → Execute → Verify → PR)**, per [SPRINT.md](./SPRINT.md#sprint-3--gate-2-plan--execute--verify--pr).
