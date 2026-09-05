"""Gate 2 control flow: routing (3.1) -> domain-expert dispatch (3.2) -> plan/execute/verify loop
with retries (3.3-3.5) -> PR + Jira sync (3.6), tracing every decision (3.7). Mirrors dispatch.py's
style (module-level firestore_client/jira_client/github_client imports, monkeypatched directly in
tests). Entered from dispatch.py's sufficient-verdict branch — nothing external re-triggers a
retry, so the whole pipeline runs as one bounded loop within a single call, unlike Gate 1's
clarification loop (which re-enters via a new webhook event)."""

import asyncio
from datetime import datetime, timezone

from artisan_shared.firestore_schema import EscalationEntry
from artisan_shared.models import (
    DomainExpertOutput,
    ExecutionResult,
    Plan,
    RepoContext,
    RoutingDecision,
)

from artisan_agents import event_context, tracing
from artisan_agents import repo_context as repo_context_module
from artisan_agents.agents.domain_expert_agent import (
    criteria_for_domains,
    run_domain_expert,
)
from artisan_agents.agents.planning_agent import run_planning
from artisan_agents.agents.routing_agent import run_routing
from artisan_agents.agents.verification_agent import run_verification
from artisan_agents.config import MAX_EXECUTION_RETRIES
from artisan_agents.gcp import cloud_run_jobs, firestore_client
from artisan_agents.gcp.firestore_client import RetryCapExceeded
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client

# Jira's real team-managed Kanban workflow (verified live against ART-8/ART-9, see
# docs/CONTEXT.md) only has Backlog / Selected for Development / In Progress / Done — there is no
# "PR Open — Awaiting Review" status to transition into, despite that being the PRD/system-design
# prose's phrasing. So Gate 2 never attempts a Jira status transition on the PR-open path — it
# stays "In Progress" in Jira, and the PR is communicated via a Jira comment instead (which Jira
# does support). Firestore's own `status` field still tracks "pr_open" precisely, per
# SYSTEM_DESIGN.md §6.4 — Firestore, not Jira's coarser workflow, is the source of truth here.


async def start_gate2(
    repo: str,
    issue_number: int,
    jira_key: str,
    *,
    issue_title: str,
    issue_body: str,
    retry_generation: int = 0,
) -> None:
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)
    event_context.set_sink(firestore_client.new_event_sink(ticket_id, gate="2"))
    await event_context.current_sink().emit(
        type="gate_started", summary="Gate 2: plan -> execute -> verify"
    )

    repo_context = await repo_context_module.get_repo_context(repo)
    # The PR opens against the repo's *actual* default branch, not a hardcoded `main` — a repo
    # whose default branch is `master`/`develop`/etc. would otherwise get PRs targeted at the
    # wrong (or non-existent) branch.
    base_branch = await github_client.get_default_branch(repo)

    await firestore_client.update_ticket(repo, issue_number, current_step="routing")
    decision = await run_routing(
        issue_title=issue_title, issue_body=issue_body, jira_key=jira_key, repo_context=repo_context
    )
    await firestore_client.update_ticket(
        repo,
        issue_number,
        domains=list(decision.domains),
        routing_rationale=decision.rationale,
        routing_confidence=decision.confidence,
    )
    async with tracing.gate_span(ticket_id, "2", "proceed", label="Gate 2: routing decided"):
        pass

    await firestore_client.update_ticket(repo, issue_number, current_step="domain_expert")
    domain_outputs = await _run_domain_experts(decision, issue_title, issue_body, repo_context)
    # v2 wave 1.5 (#17): the routed domains' lens criteria follow the ticket into verification,
    # so "verified" means the change was actually judged against the expertise routing selected.
    review_criteria = criteria_for_domains(list(decision.domains))

    feedback: str | None = None
    for attempt in range(1, MAX_EXECUTION_RETRIES + 1):
        # Issue-deleted race (Sprint 7/8): the execution job runs for minutes, and the `deleted`
        # cleanup lands the ticket in `done`. `done` mid-Gate-2 can only mean deletion — no PR
        # exists yet at this point, so a merge is impossible — so stop working the ticket rather
        # than burning a sandbox run on a dead issue.
        ticket = await firestore_client.get_ticket(repo, issue_number)
        if ticket is not None and ticket.status == "done":
            return

        await firestore_client.update_ticket(
            repo, issue_number, current_step=f"planning (attempt {attempt})"
        )
        plan = await run_planning(
            domain_outputs=domain_outputs,
            issue_title=issue_title,
            issue_body=issue_body,
            prior_feedback=feedback,
            repo_context=repo_context,
        )
        await firestore_client.update_ticket(repo, issue_number, plan=plan.model_dump(mode="json"))

        # A manual retry (Sprint 6's manual_actions.py) re-enters start_gate2 for a ticket that may
        # have already pushed artisan/{jira_key}-attempt-1 in a prior run — attempt always restarts
        # at 1 on re-entry, so without retry_generation the retry's branch collides with that stale
        # branch and its git push fails non-fast-forward (force-push is disallowed). gen==0 renders
        # today's exact format, so a normal (non-retried) run is byte-identical to before.
        branch = (
            f"artisan/{jira_key}-attempt-{attempt}"
            if retry_generation == 0
            else f"artisan/{jira_key}-r{retry_generation}-attempt-{attempt}"
        )
        await firestore_client.update_ticket(
            repo, issue_number, current_step=f"executing (attempt {attempt})"
        )
        execution_result = await cloud_run_jobs.trigger_execution(
            repo=repo, issue_number=issue_number, branch=branch, plan=plan, attempt=attempt,
            feedback=feedback,
        )
        await firestore_client.update_ticket(
            repo, issue_number, last_execution_result=execution_result.model_dump(mode="json")
        )

        await firestore_client.update_ticket(repo, issue_number, current_step="verifying")
        verdict = await run_verification(
            plan=plan, execution_result=execution_result, issue_title=issue_title,
            issue_body=issue_body, review_criteria=review_criteria,
        )

        if verdict.green:
            async with tracing.gate_span(ticket_id, "2", "proceed", label="Gate 2: verification passed"):
                pass
            await firestore_client.update_ticket(repo, issue_number, current_step="opening_pr")
            await _open_pr_and_sync(
                repo, issue_number, jira_key, issue_title, plan, execution_result, base_branch=base_branch
            )
            return

        feedback = verdict.feedback or "Verification failed with no specific feedback."
        async with tracing.gate_span(ticket_id, "2", "retry", label="Gate 2: verification failed, retrying"):
            pass
        try:
            await firestore_client.increment_retry_round(repo, issue_number)
        except RetryCapExceeded:
            await _escalate(repo, issue_number, jira_key, reason=feedback)
            async with tracing.gate_span(
                ticket_id, "2", "escalate", label="Gate 2: retry cap exceeded"
            ):
                pass
            return


async def _run_domain_experts(
    decision: RoutingDecision,
    issue_title: str,
    issue_body: str,
    repo_context: RepoContext | None = None,
) -> list[DomainExpertOutput]:
    if decision.parallel:
        return list(
            await asyncio.gather(
                *(
                    run_domain_expert(
                        domain=d,
                        issue_title=issue_title,
                        issue_body=issue_body,
                        repo_context=repo_context,
                    )
                    for d in decision.domains
                )
            )
        )
    outputs: list[DomainExpertOutput] = []
    for domain in decision.domains:
        outputs.append(
            await run_domain_expert(
                domain=domain,
                issue_title=issue_title,
                issue_body=issue_body,
                repo_context=repo_context,
            )
        )
    return outputs


def _pr_body(issue_number: int, plan: Plan, execution_result: ExecutionResult) -> str:
    steps = "\n".join(f"- {step}" for step in plan.steps)
    return (
        f"Resolves #{issue_number}.\n\n"
        f"**Approach:**\n{steps}\n\n"
        f"**Diff summary:** {execution_result.diff_summary}\n\n"
        "_Opened automatically by Artisan — Gate 2 (plan -> execute -> verify)._"
    )


async def _open_pr_and_sync(
    repo: str,
    issue_number: int,
    jira_key: str,
    issue_title: str,
    plan: Plan,
    execution_result: ExecutionResult,
    *,
    base_branch: str,
) -> None:
    # Issue-deleted race: never open a PR for an issue that was deleted while the sandbox ran —
    # the cleanup has already closed the ticket out (`done`), so a PR referencing nothing would
    # just sit open forever.
    ticket = await firestore_client.get_ticket(repo, issue_number)
    if ticket is not None and ticket.status == "done":
        return

    pr_number, pr_url = await github_client.open_pull_request(
        repo,
        head=execution_result.branch,
        base=base_branch,
        title=f"Artisan: {issue_title}",
        body=_pr_body(issue_number, plan, execution_result),
    )
    await firestore_client.update_ticket(
        repo, issue_number, status="pr_open", pr_url=pr_url, pr_number=pr_number
    )
    await event_context.current_sink().emit(type="pr_opened", summary=f"Opened PR: {pr_url}")
    # Written so Gate 3 (Sprint 4) can resolve a later `pull_request` webhook straight to this
    # ticket without a Firestore query — see firestore_client.get_ticket_by_pr.
    await firestore_client.write_pr_pointer(repo, pr_number, issue_number)
    # WS6 ready-for-review labels — a nice-to-have signal, not load-bearing: a labeling failure
    # must never abort the PR-opening flow that already succeeded.
    try:
        await github_client.add_label(repo, pr_number, "artisan:ready-for-review")
    except Exception as exc:  # noqa: BLE001 - labeling is nice-to-have; must not abort the PR flow
        await event_context.current_sink().emit(
            type="label_failed", summary=f"Failed to label GitHub PR #{pr_number}: {exc}"
        )
    await jira_client.add_comment(
        jira_key,
        f"Artisan opened a PR: {pr_url}\n\n{{noformat}}\n{execution_result.diff_summary}\n{{noformat}}",
    )
    await event_context.current_sink().emit(
        type="jira_synced", summary=f"Commented PR link on {jira_key}"
    )
    try:
        await jira_client.add_label(jira_key, "artisan-pr-open")
    except Exception as exc:  # noqa: BLE001 - labeling is nice-to-have; must not abort the PR flow
        await event_context.current_sink().emit(
            type="label_failed", summary=f"Failed to label Jira {jira_key}: {exc}"
        )


async def _escalate(repo: str, issue_number: int, jira_key: str, *, reason: str) -> None:
    ticket = await firestore_client.get_ticket(repo, issue_number)
    if ticket is not None and ticket.status == "done":
        # Issue deleted mid-Gate-2 — the cleanup already closed the ticket out. Skip the
        # escalation entirely: flipping `done` back to `escalated` would resurrect a dead ticket,
        # and the reporter-facing comment would 404 against the deleted issue.
        return

    entry = EscalationEntry(at=datetime.now(timezone.utc), reason=reason, gate="2")
    await firestore_client.append_escalation(repo, issue_number, entry)
    # Short reporter-facing notice on the issue itself — no PR exists yet at this point in the
    # loop, and the reporter may not have Jira access, so this is their only visibility that
    # automation gave up. Jira gets the full diagnostic detail (see docs/SYSTEM_DESIGN.md §9).
    await github_client.post_issue_comment(
        repo, issue_number,
        "Artisan couldn't resolve this automatically after multiple attempts — "
        "it's been handed to the team.",
    )
    await jira_client.add_comment(
        jira_key,
        f"Artisan needs manual pickup: {MAX_EXECUTION_RETRIES} execution attempts without a "
        f"passing verification. Last feedback: {reason}",
    )
