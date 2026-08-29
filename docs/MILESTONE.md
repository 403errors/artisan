# Artisan — Closed Sprint Milestones (Sprints 1–5)

This is the phase-by-phase Definition-of-Done archive for every sprint that's fully closed — moved out of [SPRINT.md](./SPRINT.md) once Sprint 6 began, so that file stays focused on the still-open plan (cross-cutting rules, judging rubric mapping, Sprint 6–8, and the master risk register).

This is a different record from [CONTEXT.md](./CONTEXT.md#milestone-log)'s "Milestone Log": that section tells the narrative story of *how* each sprint actually went — bugs found, decisions forced, live-test outcomes — while this file is the *what was scoped and confirmed done* checklist per phase. Read this for "did Phase 3.4's DoD get met and how," read CONTEXT.md's Milestone Log for "what broke and why during Sprint 3." They're complementary, not duplicates.

---

## Sprint 1 — Foundations & Infra Setup

**Goal:** every external prerequisite exists and is wired to a secret; the repo skeleton exists; nothing downstream is blocked on "we haven't created the Jira project yet."

Since none of the prerequisites exist yet, this sprint is 100% blocking for everything else — do not start Sprint 2 in parallel with an unfinished Phase 1.2/1.3.

- **Phase 1.1 — GCP project & IAM baseline**
  - Create/select the GCP project; enable required APIs (Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace/Logging).
  - Create least-privilege service accounts per [SYSTEM_DESIGN.md §8](./SYSTEM_DESIGN.md#8-auth--security): `orchestrator`, `execution-sandbox`, `dashboard`.
  - DoD: `gcloud` (or Terraform, see Sprint 7) can authenticate and list resources in the project; service accounts exist with scoped roles only.

- **Phase 1.2 — Jira Cloud site/project**
  - Create the Jira Cloud site + project that will be the linked board; decide and record the project key.
  - Create the Artisan service account + API token; store in Secret Manager (`jira-api-token`).
  - Resolve the open decision from CONTEXT.md: pin exact `mcp-atlassian` image version.
  - DoD: a manual API token test call against the Jira Cloud REST API succeeds; token lives only in Secret Manager.

- **Phase 1.3 — GitHub App + target demo repo**
  - Pick/confirm the target GitHub repo for the demo.
  - Create the GitHub App: webhook URL (placeholder until Sprint 2's Pub/Sub push endpoint exists), permission scopes (issues, issue_comment, pull_request, contents — read/write as needed), generate + store private key and webhook secret in Secret Manager.
  - Install the App on the target repo.
  - DoD: App installation succeeds; a test webhook delivery (GitHub's built-in redelivery/ping) is receivable (even to a temporary echo endpoint).

- **Phase 1.4 — Repo scaffold**
  - Create the monorepo layout from [TECH_STACK.md](./TECH_STACK.md#repo-layout): `agents/`, `execution-sandbox/`, `dashboard/`, `infra/` (docs/ already exists).
  - `agents/`: `pyproject.toml` + `uv.lock`, pin `google-adk` exact version (resolves the other open decision from CONTEXT.md), pin `gemini-3.7-flash` model id.
  - `dashboard/`: `pnpm` + Next.js 15 (App Router) + TypeScript strict + Tailwind 4 scaffold.
  - `execution-sandbox/`: `pyproject.toml` scaffold, no logic yet.
  - DoD: `uv run pytest` (empty pass) and `pnpm build` both succeed on the bare scaffold; committed.

- **Phase 1.5 — Firestore schema + mcp-atlassian deployment** ✅ done
  - Firestore native-mode DB created (`artisan-multiagent-ai`, region `us-central1`). Schema-validation fixture (`TicketDoc` in `agents/src/artisan_agents/firestore_schema.py`) matching [SYSTEM_DESIGN.md §6.4](./SYSTEM_DESIGN.md#64-firestore-document-schema--ticketsticketid) — verified with a real write/read round-trip against the live DB (`agents/tests/test_firestore_schema.py`).
  - `mcp-atlassian` deployed as an internal-ingress, auth-required Cloud Run service (`ghcr.io/sooperset/mcp-atlassian:0.23.1`), wired to `jira-api-token`/`JIRA_URL`/`JIRA_USERNAME`. Healthy per startup probe + logs.
  - Retry cap `N = 3` decided and recorded.
  - **DoD partially deferred:** a full MCP-protocol tool call (initialize → tools/call) against `mcp-atlassian` from outside GCP hit a Google-Frontend-level 404 via `gcloud run services proxy` — likely an ingress/proxy-tool interaction, not an app bug (container logs show a clean start; widening ingress to debug further was correctly blocked by sandbox guardrails and wasn't the right call anyway, since testing an internal-only service from outside GCP isn't the real production call path). **Moved to Sprint 2 Phase 2.2**, where the orchestrator will call it for real, Cloud-Run-to-Cloud-Run. What's independently confirmed: the Jira token + project work directly via REST API, and the container is correctly configured and healthy.

**Sprint 1 tests/docs:** update `CONTEXT.md` (all "Open Decisions" from this sprint resolved), add a root `README.md` with initial setup instructions (this becomes the seed for Sprint 8's reproducible-setup requirement — start it now, don't write it from scratch on the last day).

---

## Sprint 2 — Gate 1: Intake end-to-end ✅ closed

**Goal:** a real GitHub issue, opened on the demo repo, either auto-advances to Jira *In Progress* or gets a specific clarifying comment back — with no human touching Jira. **Confirmed live on both branches** (issues #2/#3 on `403errors/artisan-demo` → real Gemini calls via Vertex AI → Jira `ART-8` In Progress / `ART-9` left untouched with a clarifying comment posted) — see `CONTEXT.md` Milestone 3.

- **Phase 2.1 — Webhook → Pub/Sub → orchestrator**
  - Create Pub/Sub topic `artisan-github-events` + push subscription.
  - Point the GitHub App webhook (from Phase 1.3) at the real endpoint.
  - Orchestrator Cloud Run service: Pub/Sub push handler, verifies webhook signature using the Secret Manager secret.
  - Idempotency: check `X-GitHub-Delivery` against `processed_deliveries` before any side effect (cross-cutting rule 5). **Reworked in Sprint 3's close-out:** the original check-then-mark-after-success shape left a real window open for a concurrent duplicate delivery to slip through undetected during a long-running Gate 2 attempt — it's now a transactional claim made *before* `handle_event` runs, not a flag set after (see `docs/CONTEXT.md`'s "Known follow-up" on the duplicate-delivery race, and `docs/SYSTEM_DESIGN.md` §7).
  - DoD: opening a test issue produces a log line in the orchestrator with the parsed payload; duplicate delivery (manual redelivery) is provably a no-op.

- **Phase 2.2 — Ticket bootstrap**
  - On first sight of an issue, orchestrator creates the Firestore `tickets/{ticketId}` doc and the Jira ticket via `mcp-atlassian`, storing the GitHub↔Jira mapping.
  - This is also where Sprint 1's deferred `mcp-atlassian` MCP-protocol verification finally happens for real (Cloud-Run-to-Cloud-Run, the actual production call path) — confirm the ADK tool call round-trips into an actual Jira ticket on project `ART`, not just that the container is healthy.
  - DoD: one GitHub issue → exactly one Jira ticket → exactly one Firestore doc, verified with a duplicate-webhook test.

- **Phase 2.3 — Intake Agent**
  - Implement as an ADK agent (Gemini 3.7 Flash) returning the `IntakeVerdict` Pydantic model ([SYSTEM_DESIGN.md §6.2](./SYSTEM_DESIGN.md#62)).
  - Input: GitHub issue body/thread + Jira ticket fields.
  - DoD: unit tests with a deliberately vague issue (expects `sufficient: false` + a specific question) and a well-specified issue (expects `sufficient: true`).

- **Phase 2.4 — Clarification loop + caps**
  - Insufficient → post the question as a GitHub issue comment via the App's installation token (never a PAT), increment `clarification_rounds` transactionally.
  - A reply on the issue re-triggers Phase 2.3's evaluation.
  - 3rd insufficient round → `status: manual_pickup`, Jira annotated, no further automated attempts.
  - Sufficient → Jira transitions to *In Progress*; this is the trigger into Sprint 3.
  - DoD: integration test simulating 3 insufficient rounds ends in `manual_pickup` and does *not* attempt a 4th.

- **Phase 2.5 — Observability for Gate 1**
  - One OpenTelemetry span per gate decision (`proceed`/`ask`/`escalate`), tagged `ticket_id`, `gate: "1"`, exported to Cloud Trace.
  - DoD: a span is visible in Cloud Trace for both the sufficient and insufficient paths.

**Sprint 2 tests/docs:** `pytest` coverage for Phases 2.1–2.4 (webhook idempotency, IntakeVerdict branching, cap enforcement); update `CONTEXT.md` milestone log.

---

## Sprint 3 — Gate 2: Plan → Execute → Verify → PR ✅ closed

**Goal:** a sufficiently-specified ticket goes from *In Progress* to an open, reviewable PR with zero manual intervention, tests and docs included. **Confirmed live:** issue `403errors/artisan-demo#4` ("Add a simple static landing page") → sufficient → Jira `ART-10` *In Progress* → routing (`frontend`) → planning → execution → verification green on the first attempt, zero retries → real PR `403errors/artisan-demo#5` opened, Jira comment posted — see `docs/CONTEXT.md` Milestone 5.

- **Phase 3.1 — Orchestrator routing** ✅ done
  - High-thinking orchestrator decision: which domain-expert persona(s) apply (start with `frontend`; keep `backend`/`infra-devops` as extensible stubs), and whether they run in parallel or sequentially.
  - **Scope boundary (folded in from the now-deleted `artisan.md` §6, per this section's own note — the original file's exact wording didn't survive since it was never committed to this repo, so this restates the intent, not the literal text):** the specialist/domain-expert roster is *extensible, not exhaustive* — `frontend` is the only persona with a fully fleshed-out reasoning lens for the Sprint 3 demo scope, `backend`/`infra-devops` exist as real, callable personas sharing the same `DomainExpertOutput` contract but with a thinner lens, addable without a new agent registration (see `agents/src/artisan_agents/agents/domain_expert_agent.py`). And: Artisan has **no dependency on an external coding agent** (Claude Code, Cursor, etc.) anywhere in the resolution loop — the Execution sandbox's code-writing step (Phase 3.4) is Artisan's own bounded ADK/Gemini function-calling agent, never a shelled-out third-party CLI, per `docs/PRD.md` §5's non-goal.
  - DoD: unit test with a multi-domain issue confirms parallel dispatch; a single-domain issue confirms sequential/single dispatch. Met — `agents/tests/test_routing_agent.py`, `agents/tests/test_gate2.py`.

- **Phase 3.2 — Domain-Expert Agent(s)** ✅ done
  - At least the `frontend` persona implemented and returning `DomainExpertOutput` ([SYSTEM_DESIGN.md §6.2](./SYSTEM_DESIGN.md#62)). Implemented as a single parameterized `Agent` instance shared across all three personas (persona injected into the prompt, not the schema) — see `agents/src/artisan_agents/agents/domain_expert_agent.py`.
  - DoD: given a sample frontend-flavored issue, produces a technical summary + relevant file list that a human reviewer would call reasonable. Unit-tested with a stubbed model (`agents/tests/test_domain_expert_agent.py`); reasoning *quality* under real Gemini calls is a live/manual judgment call, not something a unit test can assert.

- **Phase 3.3 — Planning Agent** ✅ done
  - Consumes `DomainExpertOutput` (+ prior retry feedback if looping back) and, when available, `RepoContext` (WS3), emits `Plan` (steps, touched files, **test cases**, **doc updates**, and **removed_code** — Sprint 7 WS5). See `agents/src/artisan_agents/agents/planning_agent.py`.
  - DoD: plan output always includes non-empty `test_cases` and `doc_updates` fields, for every domain — enforced as a post-hoc Python validation (one amended-prompt retry) unconditionally, no longer gated on a `frontend` domain output being present (Sprint 7 WS5 generalization). `touched_files`/`removed_code` entries must be grounded in the real repo context when it's given, and stale symbols the change fully supersedes are identified explicitly via `removed_code` (file + symbol + reason) for the coding agent to delete. Given a high `thinking_level` (`google.genai.types.ThinkingConfig`) — the only agent in the pipeline configured this way. `agents/tests/test_planning_agent.py`.

- **Phase 3.4 — Execution sandbox (Cloud Run Job)** ✅ done — live deploy + manual trigger confirmed
  - One job per attempt: clone repo, create branch, execute the plan, write tests/docs, run the full suite, exit with `ExecutionResult` (success+diff or failure+logs). Built from scratch in `execution-sandbox/` (previously a bare scaffold): `git_ops.py` (subprocess `git` CLI wrappers), `coding_agent.py` (a bounded ADK function-calling agent — deliberately **not** ADK's built-in `bash_tool`, which unconditionally requires human confirmation before every command and would stall forever unattended; custom `read_file`/`write_file`/`list_directory`/`run_shell_command`/`finish` tools instead, capped at `MAX_CODING_AGENT_TOOL_CALLS`), `test_runner.py` (single config-driven test command, `ARTISAN_DEMO_REPO_TEST_COMMAND`), `github_auth.py` (mints its own installation token), `firestore_write.py`, `main.py` (entrypoint, always exits 0 — a red test run or incomplete attempt is data, not a crash).
  - Triggered by the orchestrator with plan + repo ref as job args — `agents/src/artisan_agents/gcp/cloud_run_jobs.py::trigger_execution`, via env-var overrides on a synchronous `run_job(...).result()` call (no new async completion infra — see `docs/CONTEXT.md`).
  - Code-sharing: `agents/` and `execution-sandbox/` now share `Plan`/`ExecutionResult`/`TicketDoc`/`ticket_doc_id`/GitHub-auth-construction via a new `uv` workspace + `packages/artisan_shared/` package, not duplicated logic — see `docs/TECH_STACK.md`.
  - DoD: a manually-triggered job run against a trivial plan produces a real branch with a real commit and a real test run in logs. **Done** — `execution-sandbox@` granted `secretAccessor` on `github-app-private-key` plus `aiplatform.user` (a second Gemini-wiring gap found live, mirroring Sprint 2's), deployed as a Cloud Run Job, and a manual trigger with the trivial `Plan` fixture from the test suite produced a real branch (`artisan/manual-smoke-test`), a real commit, and `tests_passed=True` in Firestore. Everything mockable was already unit-tested (`execution-sandbox/tests/`, 13 tests, including a real-local-git-repo test for the git wrappers and a stuck-model tool-call-ceiling test for the coding agent).

- **Phase 3.5 — Verification Agent + retry loop** ✅ done
  - Compares `ExecutionResult` against the `Plan` and original issue; emits `VerificationVerdict`. Short-circuits to `green=false` without a model call when `tests_passed` is already `False` (`agents/src/artisan_agents/agents/verification_agent.py`).
  - Not green, or green-but-tests-failed → feedback appended to Firestore, `retry_count` incremented transactionally, loop back to Phase 3.3 with feedback in context. Retry cap mirrors the clarification-round cap's exact commit-then-raise transactional shape (`gcp/firestore_client.py::increment_retry_round`/`RetryCapExceeded`).
  - Retry cap `N` (decided in Phase 1.5) exceeded → `status: escalated`, last failure attached (`append_escalation`, via `firestore.ArrayUnion` — atomic append, not read-modify-write), Jira + GitHub both notified (cross-cutting rule 3 applies here directly). Loop lives in `agents/src/artisan_agents/gate2.py::start_gate2`.
  - DoD: integration test forcing N consecutive failures ends in `escalated` with a populated `escalation_history` entry, and does not attempt an (N+1)th run. Met — `agents/tests/test_gate2.py::test_n_consecutive_failures_end_in_escalated_with_no_nplus1th_attempt`.

- **Phase 3.6 — PR + Jira sync** ✅ done — confirmed live end-to-end
  - Green + tests pass → orchestrator opens the PR via the GitHub App (tags the issue, summarizes approach), mirrors the summary as a Jira comment. **Discovered live** (queried real transitions on `ART-8`/`ART-9`): this Jira site's team-managed Kanban workflow only has `Backlog` / `Selected for Development` / `In Progress` / `Done` — there is **no** "PR Open — Awaiting Review" status to transition into, despite that being this doc's/the PRD's phrasing. Gate 2 does not attempt a Jira status transition on the PR-open path; the ticket stays `In Progress` in Jira and the PR link/summary is communicated via a Jira comment instead (which Jira does support). Firestore's own `TicketDoc.status` still tracks `"pr_open"` precisely — see `agents/src/artisan_agents/gate2.py`'s module docstring.
  - DoD: end-to-end run on a real (simple) test issue produces an actual open PR with a correct summary and a matching Jira comment. **Done** — issue `403errors/artisan-demo#4` produced real PR `403errors/artisan-demo#5` (branch `artisan/ART-10-attempt-1`) with a correct summary, plus a matching Jira comment on `ART-10`, green and PR-opened on the first attempt with zero retries. Control-flow coverage: `agents/tests/test_gate2.py::test_green_on_second_attempt_reaches_pr_open_with_retry_count_one`, plus `agents/tests/test_github_client.py` for `open_pull_request`.

- **Phase 3.7 — Observability for Gate 2** ✅ done
  - Spans for orchestrator routing, each retry iteration, and the final PR-open decision, tagged `gate: "2"`. `tracing.gate_span`'s `decision` literal widened to include `"retry"` (distinct from Gate 1's `"ask"`, which means something specific to the clarification loop) so Gate 3's future spans stay unambiguous too.

**Sprint 3 tests/docs:** this is the sprint most worth over-testing — it's 40% of the judging weight. 79 tests passing across all three `uv` workspace packages (`agents/`: 54, `packages/artisan_shared/`: 12, `execution-sandbox/`: 13) as of close-out — up from 75 at code-complete, net new coverage from replacing the single duplicate-delivery test with the claim-lifecycle tests (see Sprint 2's Phase 2.1 note above). `docs/CONTEXT.md`, `docs/SYSTEM_DESIGN.md`, `docs/TECH_STACK.md`, and the root `README.md` updated for the workspace/shared-package split and the Jira workflow-status finding. **Sprint 3 is closed** — live deploy, the manual smoke test, and one real end-to-end issue (`403errors/artisan-demo#4` → PR `#5`) are all confirmed; see `docs/CONTEXT.md` Milestone 5 for the full account, including two bugs caught along the way (a duplicate-delivery race in the idempotency guard, fixed by making it a claim made before processing rather than a flag set after — see Sprint 2's Phase 2.1 above; and a missing `roles/cloudtrace.agent` grant on `orchestrator@` that had been silently breaking every gate span's export to Cloud Trace since Sprint 2).

---

## Sprint 4 — Gate 3: Merge Conflict Triage ✅ closed

**Goal:** a conflicting second PR is classified correctly and either auto-resolved-and-reverified or escalated with a clear side-by-side comparison — never silently guessed at.

- **Phase 4.1 — Conflict signal ingestion** ✅ done
  - `pull_request` webhook (`opened`/`synchronize`) → Pub/Sub → orchestrator, same idempotency path as Gate 1. **Detection is Artisan's own authoritative trial merge, not GitHub's `mergeable_state`** (frequently stale/null right when the webhook fires — unacceptable for a must-be-live demo): the orchestrator resolves the PR to its ticket via a new `pr_index` pointer doc (a no-op if untracked), then triggers `execution-sandbox` in `detect_conflict` mode to actually attempt the merge. See `docs/SYSTEM_DESIGN.md` §5 for the full mechanics, including why the merge checks out **head** and merges **base** into it (never the reverse — the reverse would force a force-push on resolution, forbidden by `docs/PRD.md` §5).

- **Phase 4.2 — Conflict Agent classification** ✅ done
  - Reads diff + conflict markers + both sides' stated intent, emits `ConflictVerdict` (`trivial` | `semantic`) — `agents/src/artisan_agents/agents/conflict_agent.py`.
  - DoD: unit tests with a synthetic non-overlapping-region conflict (expects `trivial`) and a synthetic same-logic-different-intent conflict (expects `semantic`). Met — `agents/tests/test_conflict_agent.py`.

- **Phase 4.3 — Trivial resolution** ✅ done
  - `execution-sandbox`'s `resolve_conflict` job mode re-does the trial merge, runs the bounded conflict-resolution coding agent against the markers, and only pushes if the full suite passes. Failure escalates immediately — capped at exactly 1 attempt via a new transactional `increment_trivial_conflict_attempt` (claimed *before* the attempt runs, cross-cutting rule 3 — its comparison is deliberately `>` not `>=`, unlike the clarification/retry caps, since there's no free first attempt here; see `docs/CONTEXT.md` Milestone 6 for the bug this would have been).
  - DoD: forced-failure test confirms no second attempt is made; failure path escalates correctly. Met — `execution-sandbox/tests/test_main.py::test_conflict_resolution_forced_test_failure_does_not_push_and_reports_failed` (sandbox half) and `agents/tests/test_gate3.py::test_trivial_conflict_forced_resolution_failure_escalates_with_exactly_one_attempt` (control-flow half, proves a second `start_gate3` call is blocked by the cap before ever triggering a second resolution job).

- **Phase 4.4 — Semantic escalation** ✅ done
  - No resolution attempted; posts structured comparison (both sides' intent + diff) as a PR comment, escalates to maintainer — via GitHub (PR comment, reusing `github_client.post_issue_comment`) **and** Jira, per `SYSTEM_DESIGN.md` §9's dual-notify rule. Gate 2's own `_escalate` now also notifies GitHub (a short reporter-facing issue comment, added post-Sprint-4) but deliberately isn't full dual-detail parity with this — see `docs/CONTEXT.md`.
  - DoD: comparison comment is legible and clearly separates "side A intent" vs "side B intent," not just a raw diff dump. Met — `agents/tests/test_conflict_agent.py` asserts both phrases appear in the model's `comparison` output; `agents/tests/test_gate3.py::test_semantic_conflict_escalates_with_dual_comments_containing_both_sides` asserts they reach both the PR comment and the Jira comment.

- **Phase 4.5 — Observability** ✅ done
  - Spans tagged `gate: "3"` for both classification and resolution/escalation outcome — reuses the existing `decision: "proceed"|"escalate"` values (no `tracing.py` schema change needed), one span at classification time and one at the resolution/escalation outcome, per `gate3.py`.

**Sprint 4 tests/docs:** 118 tests passing across all three `uv` workspace packages (`agents/`: 78, `packages/artisan_shared/`: 13, `execution-sandbox/`: 29) after close-out. `docs/CONTEXT.md` and `docs/SYSTEM_DESIGN.md` updated. This sprint directly produces the demo's step 4 (deliberately conflicting second PR) — the real-local-git-repo conflict fixtures built for `execution-sandbox/tests/test_git_ops.py` double as demo rehearsal material in Sprint 8, per this section's own instruction. **Closed live** (`docs/CONTEXT.md` Milestone 7): two real conflicting-PR pairs run through the deployed pipeline — the first surfaced and got a real bug fixed live (`execution-sandbox`'s trial-merge crashed without a configured git identity), the second confirmed the fix with a clean, correctly-classified `semantic` escalation. Two new gaps found live and flagged for Sprint 6, not fixed here: semantic escalation has no dedup cap (duplicate maintainer-facing comments possible), and a `pull_request.opened`/`write_pr_pointer` race can silently no-op Gate 3's very first check.

---

## Sprint 5 — Monitoring Dashboard (full F5 scope) ✅ closed

**Goal:** an authenticated maintainer can see live ticket state across all three gates, drill into any ticket's full decision trail, and find anything currently awaiting them — without touching Cloud Trace or Jira directly.

- **Phase 5.1 — App scaffold + auth** ✅ done
  - Next.js 15 App Router, React 19 (Server Components default), TypeScript strict, Tailwind 4.
  - Auth.js v5, a new GitHub OAuth App (separate from the webhook GitHub App), scope `read:user user:email repo` (the default omits `repo`) so dashboard access matches the signed-in user's actual GitHub repo permissions — enforced via a real collaborator-permission API check in the `signIn` callback, not just "any authenticated account."
  - DoD: sign-in flow works against a real GitHub OAuth App; unauthenticated requests to any protected route are rejected. Met — but *not* via middleware: `export { auth as middleware }` silently broke Turbopack's static `config.matcher` extraction (verified empirically, fell back to matching every path), and an `authorized` callback turned out to affect every `auth()` call app-wide rather than just middleware-matched paths. Fixed by dropping middleware entirely for explicit per-page `requireSession()` checks (pages) / per-route `await auth()` checks (API routes) — see `dashboard/src/lib/require-session.ts`. Also needed `trustHost: true` (any non-default host/port).

- **Phase 5.2 — Server-side read API** ✅ done
  - `GET /api/tickets`, `GET /api/tickets/:id` per [SYSTEM_DESIGN.md §6.3](./SYSTEM_DESIGN.md#63-dashboard-read-api-nextjs-route-handlers-server-side-only) — server-side Firestore reads only, browser never talks to Firestore directly.
  - DoD: both routes return correctly-shaped data behind auth; a Playwright test confirms an unauthenticated browser session gets a clean 401 with no ticket data. Met — `dashboard/e2e/auth.spec.ts`.

- **Phase 5.3 — Live ticket list** ✅ done
  - Card-grid overview (not a table, per product direction from this sprint's design review): status tag per ticket, current gate + live sub-step, GitHub/Jira/PR links, last-updated — updating live via a server-side Firestore `onSnapshot` listener bridged to the browser over Server-Sent Events (`/api/tickets/stream`), not polling.
  - DoD: opening a real ticket and watching it move through gates is visible without a manual refresh. Met for gate/status transitions (already written to Firestore); also added a new `current_step` field (Sprint 5, e.g. `"planning (attempt 2)"`) written at each sub-step transition in `dispatch.py`/`gate2.py`/`gate3.py`, since Firestore was previously only written to at gate *decision* points — without it there was no live signal between "Gate 2 started" and "Gate 2 opened a PR."

- **Phase 5.4 — Drill-in detail view** ✅ done
  - Full decision trail (`/tickets/:id`): clarification/retry counts, plan, execution results (summary + tests_passed + a link to full logs, never raw logs inline), conflict detection/resolution, escalation history, PR link, Cloud Trace links.
  - DoD: every count/history entry matches the underlying Firestore doc exactly. Met — `dashboard/src/components/__tests__/decision-trail.test.tsx`. Cloud Trace links required fixing a real gap first: `trace_ids` was declared in the schema but never written (Sprints 2–4) — `tracing.gate_span` is now an `asynccontextmanager` that appends the span's trace id via a new `firestore_client.append_trace_id` on exit. (Cloud Trace *export* of `gate.*` spans is still broken per Milestone 7 — Sprint 6 scope — so a link may not resolve to a visible span yet; `trace_ids` itself is correct regardless since the id is computed locally.)

- **Phase 5.5 — Escalation surfacing** ✅ done
  - A distinct "awaiting human" view (`/escalations`) — `status in {escalated, manual_pickup}`, same live card grid, server-filtered.

- **Phase 5.6 — Tests** ✅ done
  - 20 Vitest + React Testing Library component/unit tests; 6 Playwright e2e specs covering unauthenticated 401 + redirect, sign-in, ticket list, and ticket detail — run against a real production build (`pnpm build && pnpm test:e2e`), not just dev mode. Real GitHub OAuth can't be driven headlessly, so e2e sign-in uses a test-only Credentials provider gated behind `AUTH_E2E_TEST_MODE=1` (never set outside test runs).

**Sprint 5 tests/docs:** `README.md` updated with the dashboard's new external prerequisite (OAuth App) and env vars; `SYSTEM_DESIGN.md` §6.3/§6.4/§8/§10 updated (the two new SSE routes, the corrected — previously stale — Firestore schema, the collaborator-permission-check mechanism, `trace_ids` now populated); `CONTEXT.md` Milestone 8. **Deliberately deferred, not built:** a manual "re-check/un-escalate" action on an already-escalated ticket — `CONTEXT.md`'s Milestone 6 flagged it as a possible Sprint 5 item, but neither this phase list nor PRD F5's acceptance criteria require a write/mutation action; it needs its own write-authorization design and a Gate-3 re-entry point that doesn't exist yet, so it's picked up separately in Sprint 6/7. Also created (via `gcloud`, not yet in Sprint 7's IaC) two Firestore composite indexes the dashboard's queries require.

