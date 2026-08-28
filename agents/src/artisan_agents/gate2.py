"""Gate 2 control flow: routing (3.1) -> domain-expert dispatch (3.2) -> plan/execute/verify loop
with retries (3.3-3.5) -> PR + Jira sync (3.6), tracing every decision (3.7). Mirrors dispatch.py's
style (module-level firestore_client/jira_client/github_client imports, monkeypatched directly in
tests). Entered from dispatch.py's sufficient-verdict branch — nothing external re-triggers a
retry, so the whole pipeline runs as one bounded loop within a single call, unlike Gate 1's
clarification loop (which re-enters via a new webhook event)."""

import asyncio
from datetime import datetime, timezone

from artisan_agents import tracing
from artisan_agents.agents.domain_expert_agent import run_domain_expert
from artisan_agents.agents.planning_agent import run_planning
from artisan_agents.agents.routing_agent import run_routing
from artisan_agents.agents.verification_agent import run_verification
from artisan_agents.config import MAX_EXECUTION_RETRIES
from artisan_agents.gcp import cloud_run_jobs, firestore_client
from artisan_agents.gcp.firestore_client import RetryCapExceeded
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client
from artisan_shared.firestore_schema import EscalationEntry
from artisan_shared.models import DomainExpertOutput, ExecutionResult, Plan, RoutingDecision

# Jira's real team-managed Kanban workflow (verified live against ART-8/ART-9, see
# docs/CONTEXT.md) only has Backlog / Selected for Development / In Progress / Done — there is no
# "PR Open — Awaiting Review" status to transition into, despite that being the PRD/system-design
# prose's phrasing. So Gate 2 never attempts a Jira status transition on the PR-open path — it
# stays "In Progress" in Jira, and the PR is communicated via a Jira comment instead (which Jira
# does support). Firestore's own `status` field still tracks "pr_open" precisely, per
# SYSTEM_DESIGN.md §6.4 — Firestore, not Jira's coarser workflow, is the source of truth here.
PR_BASE_BRANCH = "main"


async def start_gate2(
    repo: str, issue_number: int, jira_key: str, *, issue_title: str, issue_body: str
) -> None:
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)

    decision = await run_routing(issue_title=issue_title, issue_body=issue_body, jira_key=jira_key)
    await firestore_client.update_ticket(repo, issue_number, domains=list(decision.domains))
    with tracing.gate_span(ticket_id, "2", "proceed"):
        pass

    domain_outputs = await _run_domain_experts(decision, issue_title, issue_body)

    feedback: str | None = None
    for attempt in range(1, MAX_EXECUTION_RETRIES + 1):
        plan = await run_planning(
            domain_outputs=domain_outputs,
            issue_title=issue_title,
            issue_body=issue_body,
            prior_feedback=feedback,
        )
        await firestore_client.update_ticket(repo, issue_number, plan=plan.model_dump(mode="json"))

        branch = f"artisan/{jira_key}-attempt-{attempt}"
        execution_result = await cloud_run_jobs.trigger_execution(
            repo=repo, issue_number=issue_number, branch=branch, plan=plan, attempt=attempt,
            feedback=feedback,
        )
        await firestore_client.update_ticket(
            repo, issue_number, last_execution_result=execution_result.model_dump(mode="json")
        )

        verdict = await run_verification(
            plan=plan, execution_result=execution_result, issue_title=issue_title,
            issue_body=issue_body,
        )

        if verdict.green:
            with tracing.gate_span(ticket_id, "2", "proceed"):
                pass
            await _open_pr_and_sync(repo, issue_number, jira_key, issue_title, plan, execution_result)
            return

        feedback = verdict.feedback or "Verification failed with no specific feedback."
        with tracing.gate_span(ticket_id, "2", "retry"):
            pass
        try:
            await firestore_client.increment_retry_round(repo, issue_number)
        except RetryCapExceeded:
            await _escalate(repo, issue_number, jira_key, reason=feedback)
            with tracing.gate_span(ticket_id, "2", "escalate"):
                pass
            return


async def _run_domain_experts(
    decision: RoutingDecision, issue_title: str, issue_body: str
) -> list[DomainExpertOutput]:
    if decision.parallel:
        return list(
            await asyncio.gather(
                *(
                    run_domain_expert(domain=d, issue_title=issue_title, issue_body=issue_body)
                    for d in decision.domains
                )
            )
        )
    outputs: list[DomainExpertOutput] = []
    for domain in decision.domains:
        outputs.append(
            await run_domain_expert(domain=domain, issue_title=issue_title, issue_body=issue_body)
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
) -> None:
    pr_number, pr_url = await github_client.open_pull_request(
        repo,
        head=execution_result.branch,
        base=PR_BASE_BRANCH,
        title=f"Artisan: {issue_title}",
        body=_pr_body(issue_number, plan, execution_result),
    )
    await firestore_client.update_ticket(
        repo, issue_number, status="pr_open", pr_url=pr_url, pr_number=pr_number
    )
    # Written so Gate 3 (Sprint 4) can resolve a later `pull_request` webhook straight to this
    # ticket without a Firestore query — see firestore_client.get_ticket_by_pr.
    await firestore_client.write_pr_pointer(repo, pr_number, issue_number)
    await jira_client.add_comment(
        jira_key,
        f"Artisan opened a PR: {pr_url}\n\n{execution_result.diff_summary}",
    )


async def _escalate(repo: str, issue_number: int, jira_key: str, *, reason: str) -> None:
    entry = EscalationEntry(at=datetime.now(timezone.utc), reason=reason, gate="2")
    await firestore_client.append_escalation(repo, issue_number, entry)
    await jira_client.add_comment(
        jira_key,
        f"Artisan needs manual pickup: {MAX_EXECUTION_RETRIES} execution attempts without a "
        f"passing verification. Last feedback: {reason}",
    )
