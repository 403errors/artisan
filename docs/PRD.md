# Artisan — Product Requirements Document

## 1. Problem

Engineering work increasingly runs through a *fleet* of coding agents (Claude Code, Cursor, GitHub Copilot, Factory AI) rather than one, but none of that fleet talks to Jira on its own. Two manual taxes result:

- **Ticket → agent:** translating a Jira ticket into context a coding agent can act on.
- **Agent → ticket:** noticing a PR landed, checking it against the ticket, and updating status/comments/links by hand.

Artisan owns the whole resolution loop — GitHub issue in, reviewed PR out, Jira kept in sync throughout — so no human has to shuttle context between the two systems.

## 2. Users & Personas

- **Primary — the maintainer/lead of a small engineering team.** Owns one GitHub repo with a linked Jira board, wants routine tickets resolved without personally babysitting an agent through triage, planning, execution, and status updates.
- **Secondary — a contributing engineer on that team.** Files GitHub issues, reviews the PRs Artisan opens, occasionally answers a clarification comment.
- **Tertiary — hackathon judges (All Things Agentic Hackathon 2026).** Evaluate autonomy, architectural soundness, and demo/production readiness against the published judging criteria.

## 3. Vision / Value Proposition

Artisan is an expert co-developer, not a chatbot: given a GitHub issue, it decides on its own whether it has enough context to act, and if so, carries the ticket from Jira "To Do" to an open, reviewable PR — updating Jira the entire way — without anyone re-typing the ticket into a coding agent or updating status by hand afterward.

**Design philosophy, applied at every decision point:** decide with confidence, or ask/escalate rather than guess. Artisan never silently does the wrong thing to avoid asking a question.

## 4. Core Features

### F1 — Intake & Context Gate (Gate 1)
A GitHub Issue syncs into Jira as a new ticket. Artisan reads it and judges whether there's enough context to automate.
- **User story:** As a maintainer, I file an issue and either see it start moving on its own, or get a specific, answerable question posted back on the issue — not a generic "please provide more details." If my issue is a duplicate of something already filed, Artisan flags it with links to the existing issue(s) and asks me to confirm before doing anything.
- **Acceptance criteria:** if context is sufficient, the ticket moves to *In Progress* automatically. If not, Artisan posts the exact missing piece of information as an issue comment and waits, for up to 3 clarification rounds, before flagging the ticket for manual pickup instead of guessing.
- **Duplicate check (Sprint 9):** before running intake, Artisan searches the repo's open issues for likely duplicates. On strong matches it posts a flag comment linking each candidate and asks the reporter to confirm. If the reporter confirms it's the same, Artisan closes the issue as a duplicate and closes the ticket out (Jira *Done*); if they say it's different, or the reply is ambiguous past one follow-up, Artisan proceeds with normal intake. Nothing is ever closed on Artisan's own initiative — only after the reporter's confirmation.

### F2 — Plan → Execute → Verify → PR Pipeline (Gate 2)
With enough context, an orchestrator routes the ticket to the relevant domain-expert persona(s), which feed a Planning Agent, then an Execution Agent, then a Verification Agent.
- **User story:** As a maintainer, I want a PR that already matches the ticket's intent, includes tests and doc updates, and has been verified against the plan before it ever reaches my review queue.
- **Acceptance criteria:** on a green verification and a passing full test suite, Artisan opens a PR (tagging the issue, summarizing its approach), mirrors that summary as a Jira comment, and moves the ticket to *PR Open — Awaiting Review*. On a failed verification or failed test run, Artisan loops back to planning/execution with specific feedback, up to a capped retry count, before escalating to the maintainer instead of retrying forever.

### F3 — Merge Conflict Triage (Gate 3)
If a conflict appears before merge, a Conflict Agent classifies it.
- **User story:** As a maintainer, trivial conflicts (non-overlapping regions, mechanical renames) should just get resolved and re-verified; conflicts that require a judgment call about intent should come to me with both sides laid out, not a guess.
- **Acceptance criteria:** trivial conflicts are resolved in a scratch worktree and only pushed if the full test suite passes there. Semantic conflicts (both sides changed the same logic differently) are never auto-resolved — Artisan posts a structured side-by-side comparison and escalates.

### F4 — Full Decision Audit Trail
Every gate decision (proceed / ask / escalate) is traced and durably recorded.
- **User story:** As a maintainer, I want to be able to answer "why did Artisan do that?" for any ticket, at any point, without digging through raw logs.
- **Acceptance criteria:** every ticket has a durable record of clarification rounds, retry counts, session/PR mapping, and escalation history; every gate decision is traceable end-to-end.

### F5 — Monitoring Dashboard
A lightweight web app scoped to one GitHub repo and its linked Jira board.
- **User story:** As a maintainer, I want one place to see what Artisan is doing right now, what's waiting on me, and what it did historically — instead of digging through Cloud Trace or Jira directly.
- **Acceptance criteria:** the dashboard shows live ticket status across all three gates, surfaces anything awaiting a human decision, and lets an authenticated user drill into a ticket's full decision trail.

## 5. Non-Goals / Out of Scope (v1)

- Not a general-purpose chatbot or IDE assistant — it has no synchronous, conversational interface.
- Not multi-repo or multi-board — v1 is scoped to exactly one GitHub repo and its linked Jira board.
- Never moves a ticket to *Done* on its own — merge by a human is the only trigger for that transition.
- Never force-pushes, merges its own PRs, or resolves a semantic merge conflict by guessing.
- No dependency on an external coding agent (Claude Code, Cursor, etc.) in the resolution loop — all reasoning and execution stays on the mandated stack.

## 6. Success Metrics

- **Autonomy:** % of intaken tickets that reach *PR Open — Awaiting Review* without a human touching Jira or the repo in between.
- **Judgment quality:** false-escalation rate (escalated tickets that a human resolves trivially) and false-proceed rate (tickets Artisan should have asked about but didn't).
- **Efficiency:** median clarification rounds per ticket; median retries per ticket before verification passes.
- **Judging alignment:** demonstrable autonomous action (Innovation & Operational Utility, 40%), clean separation of orchestrator/agents/state/secrets (Architectural Discipline, 30%), a live unedited demo plus reproducible setup on Google Cloud (Demo & Production Readiness, 30%).

## 7. Constraints

- **Tech mandate:** Gemini (3.5+) and Google's Agent Development Kit are required; the system must run on Google Cloud.
- **Deadline:** All Things Agentic Hackathon 2026 submission window closes August 31, 2026.
- **Scope:** v1 targets a single GitHub repo and its single linked Jira board — no multi-tenant configuration required at launch.

## 8. Key User Flows

1. **Happy path:** Issue filed → Jira ticket created → Gate 1 passes → orchestrator routes to domain expert(s) → plan produced → code/tests/docs written → verification passes → full suite passes → PR opened, Jira updated to *PR Open — Awaiting Review* → human reviews and merges → ticket moves to *Done*.
2. **Clarification path:** Issue filed → Gate 1 fails → Artisan comments with a specific question → user replies → Gate 1 re-evaluated (up to 3 rounds) → either passes or the ticket is flagged for manual pickup.
3. **Duplicate path:** Issue filed → search finds a likely duplicate → Artisan comments with links to the existing issue(s) and asks for confirmation → reporter replies "same" → issue closed as a duplicate and ticket closed out (Jira *Done*); or reporter replies "different" → Gate 1 intake proceeds normally.
4. **Retry path:** Verification or full test suite fails → specific feedback loops back to Planning/Execution → retried up to a capped count → on repeated failure, escalated to the maintainer with the failure detail attached.
4. **Conflict path:** PR conflicts before merge → Conflict Agent classifies → trivial: auto-resolved and re-verified in a scratch worktree → semantic: structured comparison posted, escalated to maintainer.
