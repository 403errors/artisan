# Artisan — Living Context

Purpose: a single, always-current snapshot of what actually exists in this codebase right now. Update this file after every major milestone — not chronologically-append-only, but rewritten so it always reflects current state. Git history is the record of *how* we got here; this file is the record of *where we are*.

## Current Status (as of 2026-08-28)

**Stage: Sprint 2 code complete; deployment/infra wiring still pending.** All 5 phases' code (webhook ingestion, ticket bootstrap, Intake Agent, clarification loop + caps, tracing) is implemented and tested against the real Firestore DB. What's **not** done yet: creating the real Pub/Sub topic/subscription, deploying the orchestrator to Cloud Run, and flipping the GitHub App's webhook URL from its Sprint 1 placeholder — none of that has been executed against the live GCP project yet, so no real GitHub webhook has been processed end-to-end. See "Known follow-up" below.

- [PRD.md](./PRD.md), [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md), [TECH_STACK.md](./TECH_STACK.md), and [SPRINT.md](./SPRINT.md) are finalized and reflect the full v1 vision (all 3 gates, full dashboard), phased into 8 sprints.
- Repo layout: single monorepo (`agents/`, `execution-sandbox/`, `dashboard/`, `infra/`, `docs/`).
- Target submission: All Things Agentic Hackathon 2026, deadline August 31, 2026.

## What Exists Right Now

- `agents/` (uv, Python 3.13): Sprint 1's scaffold (`config.py`, `models.py` — now 7 typed contracts including `GitHubWebhookEnvelope`, `firestore_schema.py`) plus Sprint 2's orchestrator code:
  - `app.py` — FastAPI service, two routes: `POST /webhooks/github` (HMAC signature verification, publishes to Pub/Sub) and `POST /pubsub/push` (OIDC push-token verification, idempotency check, dispatch).
  - `dispatch.py` — Gate 1 control flow: ticket bootstrap, Intake Agent invocation, clarification loop with the 3-round cap, gate-decision tracing.
  - `gcp/` — `secrets.py` (Secret Manager), `pubsub.py` (publish + push-token verification), `firestore_client.py` (ticket CRUD + the transactional `clarification_rounds` cap + the `processed_deliveries` idempotency guard).
  - `github/` — `webhook.py` (signature verify + envelope parsing), `auth.py` (App JWT → installation token via `githubkit`'s `AppAuthStrategy`), `client.py` (post comment, read issue thread).
  - `jira/client.py` — `mcp-atlassian` access via the raw `mcp` SDK (streamable-HTTP `ClientSession`, ID-token-authenticated Cloud-Run-to-Cloud-Run), not ADK's `McpToolset` — these are deterministic orchestration calls, not an LLM picking a tool, so `McpToolset`'s `ToolContext` requirement wasn't worth the machinery. See the module docstring for the reasoning.
  - `agents/intake_agent.py` — real ADK `Agent` (`output_schema=IntakeVerdict`), run per-invocation via a fresh `Runner`/`InMemorySessionService` session (stateless between calls, per SYSTEM_DESIGN.md §7).
  - `tracing.py` — OTel `TracerProvider` + `CloudTraceSpanExporter`, one span per gate decision.
  - `Dockerfile` + `.dockerignore` — multi-stage `uv` build, not yet built/pushed/deployed.
  - 29 passing pytest tests (`uv run pytest`), including live round-trips against the real Firestore DB (ticket CRUD, the clarification-round cap hitting `manual_pickup` on the 3rd round, the delivery-idempotency guard) and FastAPI route tests for both endpoints.
  - New pinned deps: `fastapi==0.141.1`, `uvicorn[standard]==0.52.4`, `google-adk[mcp]==2.8.0` (adds the `mcp==1.29.1` extra).
- `execution-sandbox/`, `dashboard/`: unchanged since Sprint 1.
- Firestore native-mode database in `artisan-multiagent-ai` (region `us-central1`) — now also holds a top-level `processed_deliveries` collection (Phase 2.1's pre-ticket idempotency guard) alongside `tickets/`.
- `mcp-atlassian` deployed as an internal-ingress, auth-required Cloud Run service (`ghcr.io/sooperset/mcp-atlassian:0.23.1`) — unchanged since Sprint 1, still not yet called live end-to-end (see below).

## Known follow-up: mcp-atlassian MCP-protocol verification still deferred

Sprint 1 deferred this to "once the orchestrator exists and calls it Cloud-Run-to-Cloud-Run." The orchestrator's `jira/client.py` now exists and is unit-tested (tool-name/error-path logic), but the *live* call still hasn't happened — this dev environment has no network path to the internal-ingress `mcp-atlassian` service, and the orchestrator itself isn't deployed yet either. **Still deferred, now to whenever the orchestrator is actually deployed and IAM-wired**: grant `orchestrator@` `roles/run.invoker` on `mcp-atlassian` specifically (Sprint 1's baseline — `datastore.user`, `pubsub.editor`, `secretAccessor`, `run.developer` — does not include this; `run.developer` manages Cloud Run resources, it doesn't grant invoke rights on another private service), then exercise `jira/client.create_ticket` against a real test issue and confirm a real `ART-*` ticket appears. `jira/client.py`'s tool names (`jira_create_issue`, `jira_transition_issue`, `jira_add_comment`, `jira_get_transitions`) are based on the `sooperset/mcp-atlassian` 0.23.1 image's documented surface — confirm against a live `session.list_tools()` call the first time this runs for real.

## Known follow-up: Sprint 2 infra/deployment not yet executed

The following from SPRINT.md Phase 2.1 still needs to be run against the live GCP project (all are real, external-facing actions — deliberately not run automatically as part of writing the code):
- `gcloud pubsub topics create artisan-github-events` + a push subscription targeting the deployed orchestrator's `/pubsub/push`.
- Build + push the orchestrator image (`agents/Dockerfile`) and `gcloud run deploy orchestrator`.
- Grant `orchestrator@` `roles/run.invoker` on `mcp-atlassian` (see above) and `roles/iam.serviceAccountTokenCreator` if not already implied, for Pub/Sub's push-auth token minting.
- Update the GitHub App's webhook URL from the Sprint 1 placeholder (`https://example.com/placeholder`) to the real deployed `/webhooks/github` endpoint.
- Set the orchestrator's env vars (`ARTISAN_PUBSUB_PUSH_AUDIENCE`, `ARTISAN_MCP_ATLASSIAN_URL`) to the real deployed URLs — both default to empty string in `config.py` until set.

Until these run, the code is verified by its test suite (including live-Firestore round-trips) but not yet by a real GitHub issue moving through the system.

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

### Milestone 2 — Sprint 2 code complete: Gate 1 intake pipeline (2026-08-28)
Implemented all 5 phases of Gate 1 in `agents/`: webhook ingestion + Pub/Sub publish (`app.py`, `github/webhook.py`, `gcp/pubsub.py`), ticket bootstrap (`dispatch.py`, `gcp/firestore_client.py`, `jira/client.py`), the Intake Agent as a real ADK `Agent` (`agents/intake_agent.py`), the clarification loop with the transactional 3-round cap (`gcp/firestore_client.py::increment_clarification_round`), and per-gate-decision OTel tracing (`tracing.py`). 29 pytest tests pass, including live round-trips against the real Firestore DB. Forced decisions: (1) two HTTP routes on one orchestrator service rather than a separate ingestion function — `/webhooks/github` verifies+publishes, `/pubsub/push` verifies+dispatches; (2) `jira/client.py` calls `mcp-atlassian` via the raw `mcp` SDK directly rather than ADK's `McpToolset`, since these are fixed deterministic calls, not agent tool-selection, and `McpToolset` requires a full agent `ToolContext`; (3) the Firestore transactional-cap function returns a `(count, at_cap)` tuple rather than raising inside the transaction, since a Firestore transactional callable's writes only commit on normal return — raising inside it would have rolled back the very cap-flip it was supposed to persist. **Not yet done** (deliberately, since these are real external/infra actions): creating the actual Pub/Sub topic/subscription, deploying the orchestrator to Cloud Run, flipping the GitHub App's webhook URL, and the live `mcp-atlassian` call — see "Known follow-up" sections above. Next: run those deployment steps, then Sprint 3 (Gate 2 — Plan → Execute → Verify → PR).

*(Add the next milestone below as it completes — keep entries short: what shipped, what decisions it forced, what's next.)*

## External accounts & identifiers (Sprint 1, Phases 1.1–1.3 — done)

- **GCP project:** `artisan-multiagent-ai`, billing linked (`My Billing Account 2`). APIs enabled: Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace, Logging, Cloud Build, IAM, Artifact Registry.
- **Service accounts:** `orchestrator@` (datastore.user, pubsub.editor, secretAccessor, run.developer), `execution-sandbox@` (datastore.user), `dashboard@` (datastore.viewer) — all least-privilege per [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security).
- **Secrets in Secret Manager:** `jira-api-token`, `github-webhook-secret`, `github-app-private-key` — all scoped to `orchestrator@` only via per-secret IAM bindings.
- **Jira:** site `pieisnot22by7.atlassian.net`, project key `ART` (id 10034), team-managed Kanban template. Service-account identity for `mcp-atlassian` is the Atlassian account `pieisnot22by7@gmail.com` + its API token.
- **GitHub:** demo repo `403errors/artisan-demo` (seeded with a README). GitHub App `artisan-bot-403errors`, App ID `4744770`, installed on `403errors` (installation id `157129507`). Webhook URL is still the placeholder `https://example.com/placeholder` — **still needs to be swapped for the real Cloud Run orchestrator endpoint** once deployed (code is ready in `app.py`; the deploy + URL swap itself hasn't run yet).
- **Retry cap `N` = 3** (decided during Phase 1.5, matches the clarification-round cap).

## Open Decisions / Risks

- GitHub App webhook URL is still the Sprint 1 placeholder — the orchestrator code that will receive it exists now, but nothing has been deployed yet, so the swap hasn't happened.
- `orchestrator@` does not yet have `roles/run.invoker` on `mcp-atlassian` — needs granting before `jira/client.py` can succeed against the live service.
- `jira/client.py`'s Jira MCP tool names (`jira_create_issue`, `jira_transition_issue`, `jira_add_comment`, `jira_get_transitions`) are based on public documentation for the pinned `sooperset/mcp-atlassian:0.23.1` image, not a live `session.list_tools()` call — confirm on first real use.
- `ARTISAN_PUBSUB_PUSH_AUDIENCE` and `ARTISAN_MCP_ATLASSIAN_URL` (agents/src/artisan_agents/config.py) default to empty string — must be set to real values at deploy time or `/pubsub/push` token verification and Jira calls will fail closed.
- Local Node is v23.7.0, not the TECH_STACK-pinned 22 LTS — worked fine for scaffold/build; revisit if a Node-version-specific issue surfaces later.
- Repo is git-initialized locally but nothing committed or pushed yet — no GitHub remote chosen for the actual Artisan source repo (distinct from the throwaway `403errors/artisan-demo` target repo).

## Next Milestone Target

**Finish Sprint 2's deployment/infra** (Pub/Sub topic+subscription, `gcloud run deploy orchestrator`, IAM grant, GitHub webhook URL swap — see "Known follow-up: Sprint 2 infra/deployment not yet executed" above), verify a real GitHub issue moves through Gate 1 end-to-end, then **Sprint 3 — Gate 2 (Plan → Execute → Verify → PR)**, per [SPRINT.md](./SPRINT.md#sprint-3--gate-2-plan--execute--verify--pr).
