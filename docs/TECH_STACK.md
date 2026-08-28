# Artisan — Tech Stack

Explicit versions and libraries, so implementation doesn't drift onto deprecated syntax or ambiguous defaults. Update this file the moment a version below is deliberately bumped or replaced — don't let it go stale.

## Repo layout

Single monorepo, greenfield:

```
artisan/
  agents/                    # Python — orchestrator + all ADK agents
  execution-sandbox/         # Python — Cloud Run Job image (Execution Agent runtime)
  packages/artisan_shared/   # Python — shared models/Firestore-id-scheme/GitHub-auth (Sprint 3)
  dashboard/                 # TypeScript — Next.js app
  infra/                     # deploy config (Dockerfiles, gcloud/Terraform)
  docs/                      # PRD.md, SYSTEM_DESIGN.md, TECH_STACK.md, CONTEXT.md
```

**Sprint 3:** `agents/` and `execution-sandbox/` are two `uv` workspace members (root `pyproject.toml` declares `[tool.uv.workspace] members = ["agents", "execution-sandbox", "packages/artisan_shared"]`) sharing a third member, `packages/artisan_shared/` — the typed Pydantic models (`Plan`, `ExecutionResult`, `TicketDoc`, etc.), the Firestore `ticket_doc_id` scheme, and GitHub App installation-auth construction. This exists because `execution-sandbox` (Sprint 3's execution job) needs the exact same `Plan`/`ExecutionResult` shapes and the exact same ticket-doc-id derivation as the orchestrator — duplicating that logic risked silent drift between the two sides of Gate 2's contract. Run `uv sync` from the repo root to sync all three members at once, or `uv sync --package <name>` for one; `uv run --package <name> pytest` runs a given member's tests.

## Agent backend (`agents/`, `execution-sandbox/`) — Python

| Library | Version | Notes |
|---|---|---|
| Python | 3.13 | |
| google-adk | latest 1.x at implementation time — pin exact version in `pyproject.toml` on first install | use the **async** agent API; do not use deprecated sync-only entry points |
| Model | `gemini-3.7-flash` | pin the explicit model id in code — never a `latest` alias |
| google-cloud-firestore | latest 2.x | async client |
| google-cloud-secret-manager | latest 2.x | |
| google-cloud-pubsub | latest 2.x | |
| google-cloud-run | latest (for triggering `execution-sandbox` Jobs from the orchestrator) | |
| opentelemetry-sdk + opentelemetry-exporter-gcp-trace | latest | one span per gate decision |
| githubkit (or PyGithub) | latest | GitHub App JWT → installation token flow; do not use a static PAT |
| httpx | latest | direct Jira Cloud REST API calls (Basic Auth, API token from Secret Manager) — see note below |
| pydantic | v2.x | all agent I/O is typed Pydantic models, never free-text dicts |
| pytest, pytest-asyncio | latest | |
| Package manager | `uv` | `pyproject.toml` + `uv.lock`, not bare `pip` |

> **Note (Sprint 2):** originally `mcp-atlassian` (a Cloud Run MCP server) sat between the orchestrator and Jira. Dropped after live testing found an unresolved auth bug in the pinned `sooperset/mcp-atlassian:0.23.1` image — see `docs/SYSTEM_DESIGN.md` §2 and `docs/CONTEXT.md` for the full diagnosis. The orchestrator now calls Jira Cloud's REST API directly via `httpx`.

> **Note (Sprint 3):** `execution-sandbox`'s coding step does **not** use ADK's built-in `google.adk.tools.bash_tool` (`ExecuteBashTool`) — that tool's `run_async` unconditionally calls `tool_context.request_confirmation(...)` before every command with no way to disable it, meaning it blocks forever waiting for human approval that will never come in an unattended Cloud Run Job. This wasn't discoverable from the tool's name/description alone; only reading its implementation surfaced it. `execution-sandbox/src/artisan_execution_sandbox/coding_agent.py` uses plain Python functions as tools instead (`read_file`/`write_file`/`list_directory`/`run_shell_command`/`finish`) — these are wrapped by ADK's `FunctionTool`, which defaults `require_confirmation=False`.

> **Note (Sprint 2):** Gemini access is via **Vertex AI**, not the Gemini Developer API — no API key/secret needed, ADK's `Agent` picks this up automatically from env vars on the orchestrator's Cloud Run service: `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai`, `GOOGLE_CLOUD_LOCATION=global`. The `orchestrator@` service account needs `roles/aiplatform.user`. **`location` must be `global`, not a regional endpoint** — `gemini-3.7-flash` 404s on `us-central1` even though the project has access to it; only the `global` Vertex AI endpoint serves this model. This was undocumented before Sprint 2's live field-testing surfaced it (see `docs/CONTEXT.md`).

## Dashboard (`dashboard/`) — TypeScript

| Library | Version | Notes |
|---|---|---|
| Node | 22 LTS | |
| Next.js | 15 | **App Router only** — no Pages Router code |
| React | 19 | Server Components by default; add `"use client"` only where interactivity is required |
| TypeScript | 5.6+ | strict mode on |
| Tailwind CSS | 4 | |
| Auth.js (NextAuth) | v5 | GitHub OAuth provider only |
| @google-cloud/firestore | latest | server-side reads only (route handlers) — the browser never talks to Firestore directly |
| shadcn/ui | latest (optional) | component layer over Tailwind, not a hard dependency |
| Package manager | `pnpm` | |
| Vitest + React Testing Library | latest | unit/component tests |
| Playwright | latest | e2e against the dashboard |

## Infra / deployment

| Tool | Notes |
|---|---|
| Docker | multi-stage builds for `agents/`, `execution-sandbox/`, `dashboard/` |
| Cloud Run (services) | `orchestrator`, `dashboard` (`mcp-atlassian` deleted in Sprint 2 after being superseded, see note above) |
| Cloud Run Jobs | `execution-sandbox` — triggered per plan-execution attempt, not long-running |
| Pub/Sub | topic `artisan-github-events`, push subscription to `orchestrator`, dead-letter topic `artisan-github-events-dlq` (max 5 delivery attempts — added Sprint 2 after a permanently-failing test message looped for ~95 minutes with no dead-letter policy configured) |
| Firestore | native mode |
| Secret Manager | `github-app-private-key`, `github-webhook-secret`, `jira-api-token` |
| CI/CD | GitHub Actions → build + push images → deploy to Cloud Run (keeps everything in the GitHub App's existing auth context) |
| IaC | Terraform preferred if time allows; otherwise checked-in `gcloud` deploy scripts under `infra/` — either way, no manual console-only setup for anything reproducible |

## Version-pin rules (apply these, don't relitigate them per-feature)

- Next.js: App Router only. Never introduce `pages/`.
- React: Server Components by default. `"use client"` is the exception, not the default.
- ADK: async agent API only.
- Gemini model id is always pinned explicitly in code (`gemini-3.7-flash`), never resolved via a "latest" alias.
- All inter-agent I/O is a typed Pydantic model — no raw string-passing between agents.
- No long-lived GitHub PAT anywhere — GitHub auth is always via the GitHub App's installation-token flow.
- Jira auth is always the single Artisan service account's API token (direct REST, Basic Auth) — never a per-user Jira login.
