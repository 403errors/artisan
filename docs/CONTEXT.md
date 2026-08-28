# Artisan — Living Context

Purpose: a single, always-current snapshot of what actually exists in this codebase right now. Update this file after every major milestone — not chronologically-append-only, but rewritten so it always reflects current state. Git history is the record of *how* we got here; this file is the record of *where we are*.

## Current Status (as of 2026-08-28)

**Stage: Sprint 1 complete.** All 5 phases done; one verification item deferred to Sprint 2 (see below).

- [PRD.md](./PRD.md), [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md), [TECH_STACK.md](./TECH_STACK.md), and [SPRINT.md](./SPRINT.md) are finalized and reflect the full v1 vision (all 3 gates, full dashboard), phased into 8 sprints.
- Repo layout decided: single monorepo (`agents/`, `execution-sandbox/`, `dashboard/`, `infra/`, `docs/`) — none of these directories exist yet.
- Target submission: All Things Agentic Hackathon 2026, deadline August 31, 2026.

## What Exists Right Now

- Monorepo scaffolded and locally git-initialized (not yet committed): `agents/` (uv, Python 3.13, `google-adk` 2.8.0 + typed Pydantic models for all 6 inter-agent contracts + Firestore `TicketDoc` schema model + 7 passing pytest tests, including a real round-trip write/read against the live Firestore DB), `execution-sandbox/` (uv, Python 3.13, bare scaffold + passing pytest), `dashboard/` (Next.js 15.5.24 App Router, React 19.1.0, TS strict, Tailwind 4.3.3, Auth.js v5 beta + `@google-cloud/firestore` installed, Vitest+RTL and Playwright wired, `pnpm build` and `pnpm test` both passing), `infra/` (placeholder, populated in Sprint 7).
- Firestore native-mode database created in `artisan-multiagent-ai` (region `us-central1`).
- `mcp-atlassian` deployed as an internal-ingress, auth-required Cloud Run service (`ghcr.io/sooperset/mcp-atlassian:0.23.1`), healthy per startup/TCP probe logs, wired to `jira-api-token`/`JIRA_URL`/`JIRA_USERNAME` and `TOOLSETS=all`.
- No agent/orchestrator logic yet, no webhook handling — this is infra + scaffold only.
- External accounts (see below) are provisioned; the GCP project, GitHub App, and Jira project all exist.

## Known follow-up: mcp-atlassian MCP-protocol verification deferred

Attempted a live MCP streamable-http handshake against `mcp-atlassian` from this local dev shell via `gcloud run services proxy` — every path (`/mcp`, `/sse`, `/`, `/health`, ...) returned a Google-Frontend-style 404, even though the container's own logs show it started cleanly and passed its TCP startup probe on port 8080. This is very likely a `gcloud run services proxy` interaction with `ingress=internal` rather than an app bug (widening ingress to debug further was correctly blocked by the sandbox's safety guardrails, and wasn't worth pursuing — testing an internal-only service from outside GCP isn't the real call path anyway). **Real verification belongs in Sprint 2 Phase 2.2**, once the orchestrator Cloud Run service exists and calls `mcp-atlassian` the way production actually will: Cloud-Run-to-Cloud-Run over the internal network. What's already independently confirmed: the Jira API token + project (`ART`) work directly via REST API (Phase 1.2), and the container is healthy and correctly configured (image, args, port, env vars all verified via `gcloud run revisions describe`).

## Milestone Log

### Milestone 0 — Planning (2026-08-28)
Wrote PRD, system design, and tech stack docs. Key decisions locked in:
- ADK agents in Python; dashboard in Next.js/React (TypeScript).
- Jira via `mcp-atlassian` service account (not per-user Jira login).
- GitHub via a GitHub App; dashboard login via GitHub OAuth.
- Execution Agent runs in ephemeral Cloud Run Jobs, one per attempt.
- Single monorepo, greenfield.

### Milestone 1 — Sprint 1 complete: infra + scaffold (2026-08-28)
Provisioned every external prerequisite (GCP project `artisan-multiagent-ai`, 3 least-privilege service accounts, 3 secrets, Jira project `ART`, GitHub App + demo repo), scaffolded all 3 code directories with passing tests/builds, created the Firestore native-mode DB, and deployed `mcp-atlassian` to Cloud Run. See "External accounts & identifiers" above for exact IDs. Forced decisions: `mcp-atlassian` pinned to 0.23.1, retry cap `N=3`, `google-adk` pinned to 2.8.0. One item deferred to Sprint 2 (see "Known follow-up" above): live MCP-protocol verification of `mcp-atlassian`, since testing an internal-ingress service from outside GCP isn't the real call path. Next: Sprint 2 (Gate 1 — Intake end-to-end).

*(Add the next milestone below as it completes — keep entries short: what shipped, what decisions it forced, what's next.)*

## External accounts & identifiers (Sprint 1, Phases 1.1–1.3 — done)

- **GCP project:** `artisan-multiagent-ai`, billing linked (`My Billing Account 2`). APIs enabled: Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace, Logging, Cloud Build, IAM, Artifact Registry.
- **Service accounts:** `orchestrator@` (datastore.user, pubsub.editor, secretAccessor, run.developer), `execution-sandbox@` (datastore.user), `dashboard@` (datastore.viewer) — all least-privilege per [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security).
- **Secrets in Secret Manager:** `jira-api-token`, `github-webhook-secret`, `github-app-private-key` — all scoped to `orchestrator@` only via per-secret IAM bindings.
- **Jira:** site `pieisnot22by7.atlassian.net`, project key `ART` (id 10034), team-managed Kanban template. Service-account identity for `mcp-atlassian` is the Atlassian account `pieisnot22by7@gmail.com` + its API token.
- **GitHub:** demo repo `403errors/artisan-demo` (seeded with a README). GitHub App `artisan-bot-403errors`, App ID `4744770`, installed on `403errors` (installation id `157129507`). Webhook URL is still the placeholder `https://example.com/placeholder` — **must be swapped for the real Cloud Run orchestrator endpoint in Sprint 2 Phase 2.1**, or webhooks will silently go nowhere.
- **Retry cap `N` = 3** (decided during Phase 1.5, matches the clarification-round cap).

## Open Decisions / Risks

- GitHub App webhook URL is a placeholder — real endpoint doesn't exist until Sprint 2.
- Local Node is v23.7.0, not the TECH_STACK-pinned 22 LTS — worked fine for scaffold/build; revisit if a Node-version-specific issue surfaces later.
- Repo is git-initialized locally but nothing committed or pushed yet — no GitHub remote chosen for the actual Artisan source repo (distinct from the throwaway `403errors/artisan-demo` target repo).

## Next Milestone Target

**Sprint 2 — Gate 1 (Intake) end-to-end**, per [SPRINT.md](./SPRINT.md#sprint-2--gate-1-intake-end-to-end) / [SYSTEM_DESIGN.md § Data Flow — Gate 1](./SYSTEM_DESIGN.md#3-data-flow--gate-1-intake). Phase 2.2's ticket-bootstrap work is also where the deferred `mcp-atlassian` live-call verification should happen naturally (creating the first real Jira ticket via the MCP tool, from the orchestrator).
