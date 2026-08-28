# Artisan — Living Context

Purpose: a single, always-current snapshot of what actually exists in this codebase right now. Update this file after every major milestone — not chronologically-append-only, but rewritten so it always reflects current state. Git history is the record of *how* we got here; this file is the record of *where we are*.

## Current Status (as of 2026-08-28)

**Stage: Sprint 2 closed — Gate 1 confirmed live end-to-end on both branches.** All infra is live: Pub/Sub topic + push subscription (now with a dead-letter policy), orchestrator on Cloud Run, GitHub App webhook pointed at it, IAM wired (including Vertex AI access). Jira access was switched from `mcp-atlassian` (MCP) to direct REST API calls after a live field-test failure (see "Known follow-up" below) — confirmed working with real tickets created on project `ART` (`ART-1`–`ART-9` so far; test artifacts commented and transitioned to Done, as the service account lacks Jira delete permission).

**Proven live, both Gate 1 branches:**
- **Sufficient path:** issue #2 on `403errors/artisan-demo` ("Password reset..."-style, well-specified) → webhook → Pub/Sub → ticket bootstrap → real Gemini call (Vertex AI) → `sufficient: true` → Jira `ART-8` → *In Progress*, Firestore `status: in_progress`.
- **Insufficient path:** issue #3 ("Login is broken", deliberately vague) → real Gemini call → specific clarifying question posted as a GitHub comment → `clarification_rounds` incremented to 1 in Firestore → Jira `ART-9` correctly left untouched (`Backlog`).

Getting the sufficient path live for the first time required two more real bugs to surface and get fixed (see "Known follow-up" below): a missing Vertex AI wiring (Gemini access was never actually configured — no API enabled, no IAM, no env vars) and a Pub/Sub infinite-retry incident (no dead-letter policy) that had been silently running for ~95 minutes before being caught.

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

## Known follow-up: Sprint 2 infra/deployment — done; Gate 1 verified live end-to-end

Deployed: Pub/Sub topic + subscription (+ dead-letter topic, see below), orchestrator Cloud Run service, IAM grants (`orchestrator@` → `iam.serviceAccountTokenCreator` for Pub/Sub's push-service-agent, needed for push-auth token minting — this was *not* auto-granted by `--push-auth-service-account` and had to be added explicitly; `roles/aiplatform.user` for Vertex AI, see below), GitHub App webhook URL.

**Verified live:** webhook signature verification (401 on forged signature); Pub/Sub publish → push delivery → OIDC verification → dispatch; ticket bootstrap end-to-end — `issues opened` → Firestore ticket doc created → real Jira ticket created via direct REST; the Intake Agent's real Gemini call (both `sufficient` and `insufficient` verdicts); `github_client.get_issue_thread`/`post_issue_comment` against real issues (`#2`, `#3` on `403errors/artisan-demo`); `jira_client.transition_ticket`/`add_comment` against real tickets (`ART-8` → In Progress, `ART-9` left untouched). Gate 1 is now fully closed — no remaining "unit-tested only" gap.

## Known follow-up: Gemini access was never actually wired up (found + fixed Sprint 2)

The very first live test of the Intake Agent's real Gemini call failed with `ValueError: No API key was provided.` Investigation found neither `aiplatform.googleapis.com` (Vertex AI) nor `generativelanguage.googleapis.com` (Gemini Developer API) was enabled on the project at all — this had been silently assumed done since Sprint 1, but was never actually a completed prerequisite, and no unit test could have caught it since unit tests mock the model.

**Resolution (Vertex AI, no new secret needed — consistent with the rest of the architecture's "orchestrator's own service account" pattern):**
- Enabled `aiplatform.googleapis.com`.
- Granted `orchestrator@` → `roles/aiplatform.user`.
- Added Cloud Run env vars: `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai`, `GOOGLE_CLOUD_LOCATION=global`.

That last one caught a second, non-obvious bug: with `GOOGLE_CLOUD_LOCATION=us-central1` (matching every other resource in this project), Gemini calls 404'd with "Publisher model ... was not found or your project does not have access to it" — even though the model *was* visible in `client.models.list()` and the Cloud Console Model Garden page for it showed no access/enablement gate at all. Confirmed via a standalone script that `gemini-2.5-flash` worked fine on `us-central1` while `gemini-3.7-flash` only responds on Vertex AI's **`global`** location. `TECH_STACK.md`/`SYSTEM_DESIGN.md` now call this out explicitly since it's not discoverable from the Console UI.

## Known follow-up: Pub/Sub infinite-retry incident (found + fixed Sprint 2)

While field-testing the above, discovered the orchestrator had been in a continuous Pub/Sub redelivery storm since 01:47 UTC — **~95 minutes and 4,400+ failed requests** by the time it was caught — because the push subscription had no dead-letter policy and no retry-policy backoff cap configured. Two Firestore tickets were stuck permanently retrying: `ART-7` (from synthetic test issue `990006`, which never existed on GitHub — a 404 that could never resolve, retried forever) and transiently `ART-8` (issue #2 itself, before the Vertex AI fix).

**Resolution:** created dead-letter topic `artisan-github-events-dlq`, wired the required IAM (Pub/Sub service agent → `roles/pubsub.publisher` on the DLQ topic, `roles/pubsub.subscriber` on the source subscription), and set `max-delivery-attempts=5` on `artisan-github-events-push`. `ART-7`/the `990006` Firestore ticket was manually marked `manual_pickup` and the Jira ticket commented + transitioned to Done, same as the `ART-1`–`ART-6` cleanup. **This is a real gap in Phase 2.1's failure-handling story** (a non-retriable failure — like a GitHub 404 that will never resolve — must not be allowed to retry forever just because the handler raises rather than terminating gracefully); worth a proper code-level fix in Sprint 6's hardening pass, not just the infra-level mitigation done here.

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

### Milestone 2 — Sprint 2 built + deployed: Gate 1 ticket-bootstrap confirmed live (2026-08-28)
Implemented all 5 phases of Gate 1 in `agents/`: webhook ingestion + Pub/Sub publish (`app.py`, `github/webhook.py`, `gcp/pubsub.py`), ticket bootstrap (`dispatch.py`, `gcp/firestore_client.py`, `jira/client.py`), the Intake Agent as a real ADK `Agent` (`agents/intake_agent.py`), the clarification loop with the transactional 3-round cap (`gcp/firestore_client.py::increment_clarification_round`), and per-gate-decision OTel tracing (`tracing.py`). Deployed to GCP: Pub/Sub topic/subscription, orchestrator Cloud Run service, IAM grants, GitHub App webhook URL pointed at the live endpoint. Live field-testing (real webhook deliveries, not just unit tests) caught three real bugs before they could reach a demo: (1) Cloud Run's default Pub/Sub push OIDC audience is the *full push endpoint URL including path* (`.../pubsub/push`), not just the service origin; (2) a Firestore transactional callable's writes only commit on normal return — raising inside it would have rolled back the very cap-flip it was supposed to persist, so `increment_clarification_round` returns a `(count, at_cap)` tuple and the caller raises after commit; (3) the pinned `mcp-atlassian:0.23.1` image has an unresolved auth bug (two independently-valid API tokens both failed identically through it) — dropped for direct Jira REST calls, proven with 6 real tickets created live (`ART-1`–`ART-6`, cleaned up after). Also caught: removing the `mcp` extra silently dropped `pyjwt`, needed for GitHub App JWT signing (fixed via `githubkit[auth-app]`). 34 pytest tests pass. **Ticket bootstrap (webhook → Jira ticket) is now confirmed live end-to-end; the Intake Agent → clarification/sufficient branches are still only unit-tested** — all live smoke tests used synthetic GitHub issue numbers that don't exist, so `get_issue_thread` 404s before reaching the agent. Next: verify against a real GitHub issue, then Sprint 3 (Gate 2 — Plan → Execute → Verify → PR).

### Milestone 3 — Sprint 2 closed: Gate 1 confirmed live on both branches (2026-08-28)

Closed the one gap left after Milestone 2 by opening two real GitHub issues on `403errors/artisan-demo` and watching them through the full live pipeline. Doing so surfaced two more real bugs, both fixed live:

1. **Gemini access was never actually configured** (`ValueError: No API key was provided`) — neither Vertex AI nor the Gemini Developer API was enabled on the project. Fixed by wiring Vertex AI: enabled `aiplatform.googleapis.com`, granted `orchestrator@` → `roles/aiplatform.user`, set `GOOGLE_GENAI_USE_VERTEXAI=TRUE`/`GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` env vars on Cloud Run. Then hit a second layer of the same bug: `GOOGLE_CLOUD_LOCATION=us-central1` 404'd on `gemini-3.7-flash` specifically (confirmed `gemini-2.5-flash` worked fine on that region) — the model is only served from Vertex AI's `global` location, not discoverable from the Console UI. Fixed by setting `GOOGLE_CLOUD_LOCATION=global`.
2. **Pub/Sub infinite-retry incident** — separately discovered while debugging (1), predating it: no dead-letter policy on the push subscription meant a permanently-failing message (a synthetic test issue number that never existed on GitHub) had been retrying non-stop for ~95 minutes, ~4,400+ failed requests. Fixed with a dead-letter topic (`artisan-github-events-dlq`, max 5 attempts) and cleaned up the stuck Firestore ticket + Jira ticket (`ART-7`).

With both fixed, issue #2 (well-specified) went sufficient → real Gemini call → Jira `ART-8` → *In Progress*, and issue #3 (deliberately vague) went insufficient → real Gemini call → clarifying question posted → `clarification_rounds: 1`, Jira `ART-9` correctly left untouched. **Sprint 2 is now closed.** Next: Sprint 3 (Gate 2 — Plan → Execute → Verify → PR).

*(Add the next milestone below as it completes — keep entries short: what shipped, what decisions it forced, what's next.)*

## External accounts & identifiers (Sprint 1, Phases 1.1–1.3 — done)

- **GCP project:** `artisan-multiagent-ai`, billing linked (`My Billing Account 2`). APIs enabled: Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace, Logging, Cloud Build, IAM, Artifact Registry.
- **Service accounts:** `orchestrator@` (datastore.user, pubsub.editor, secretAccessor, run.developer, `aiplatform.user` for Vertex AI, + `iam.serviceAccountTokenCreator` for Pub/Sub's push service agent — added in Sprint 2), `execution-sandbox@` (datastore.user), `dashboard@` (datastore.viewer) — all least-privilege per [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security).
- **Vertex AI:** `aiplatform.googleapis.com` enabled Sprint 2. Orchestrator's Gemini calls run via `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai`, `GOOGLE_CLOUD_LOCATION=global` (must be `global`, not a region — see Milestone 3). No API key/secret involved.
- **Pub/Sub dead-letter:** topic `artisan-github-events-dlq`, `max-delivery-attempts=5` on `artisan-github-events-push` (added Sprint 2 after an infinite-retry incident — see Milestone 3).
- **Secrets in Secret Manager:** `jira-api-token`, `github-webhook-secret`, `github-app-private-key` — all scoped to `orchestrator@` only via per-secret IAM bindings. `jira-api-token` has been rotated twice during Sprint 2 debugging (versions 1–3 all `enabled`); current value confirmed working via direct REST call.
- **Jira:** site `pieisnot22by7.atlassian.net`, project key `ART` (id 10034), team-managed Kanban template. Orchestrator authenticates directly as the Atlassian account `pieisnot22by7@gmail.com` + its API token (Basic Auth, REST) — no MCP intermediary as of Sprint 2.
- **GitHub:** demo repo `403errors/artisan-demo` (seeded with a README). GitHub App `artisan-bot-403errors`, App ID `4744770`, installed on `403errors` (installation id `157129507`). Webhook URL now points at the deployed orchestrator's `/webhooks/github` (updated from the Sprint 1 placeholder in Sprint 2).
- **Orchestrator Cloud Run service:** deployed in `us-central1`, public ingress (required for GitHub to reach `/webhooks/github`; `/pubsub/push` is separately protected by in-app OIDC verification), runs as `orchestrator@`.
- **Retry cap `N` = 3** (decided during Phase 1.5, matches the clarification-round cap).

## Open Decisions / Risks

- `docs/SPRINT.md` is not tracked by git at all — it exists only in the main checkout's working directory, untracked since Sprint 1. At risk of being lost; commit it.
- Two Jira API tokens were pasted in plaintext into a terminal session during debugging (now sitting in that session's history/scrollback) — recommend rotating `jira-api-token` one more time from a clean terminal now that Sprint 2 is confirmed working, so no exposed value stays live.
- The Pub/Sub dead-letter policy (added Sprint 2) is an infra-level mitigation only — the underlying code issue (a non-retriable failure like a GitHub 404 causes `handle_event` to raise and retry forever instead of terminating gracefully) hasn't been fixed at the code level yet. Worth doing properly in Sprint 6's hardening pass, not just relying on the dead-letter cap.
- Local Node is v23.7.0, not the TECH_STACK-pinned 22 LTS — worked fine for scaffold/build; revisit if a Node-version-specific issue surfaces later.
- Repo is git-initialized locally but nothing pushed yet — no GitHub remote chosen for the actual Artisan source repo (distinct from the throwaway `403errors/artisan-demo` target repo).

## Next Milestone Target

**Sprint 3 — Gate 2 (Plan → Execute → Verify → PR)**, per [SPRINT.md](./SPRINT.md#sprint-3--gate-2-plan--execute--verify--pr). Sprint 2 (Gate 1) is closed — both the sufficient and insufficient branches are confirmed live end-to-end, not just unit-tested.
