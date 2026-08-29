"""Gate 3 control flow: conflict detection (4.1) -> Conflict Agent classification (4.2) -> trivial
resolution (4.3) or semantic escalation (4.4), tracing every decision (4.5). Mirrors gate2.py's
style (module-level firestore_client/jira_client/github_client imports, monkeypatched directly in
tests). Unlike Gate 2's bounded plan/execute/verify loop, Gate 3 makes exactly one classification
decision and, on the trivial path, exactly one resolution attempt — no retry loop by design
(MILESTONE.md Phase 4.3: capped at exactly 1 attempt, failure escalates immediately).

Entered from dispatch.py's `pull_request` branch. A `pull_request` event with no matching
`pr_index` pointer is simply not Artisan's concern and is a no-op — Gate 3 never operates on repo
state it doesn't own (PRD.md §5)."""

import asyncio
from datetime import datetime, timezone

from artisan_shared.firestore_schema import EscalationEntry
from artisan_shared.models import ConflictVerdict

from artisan_agents import event_context, tracing
from artisan_agents.agents.conflict_agent import run_conflict_classification
from artisan_agents.gcp import cloud_run_jobs, firestore_client
from artisan_agents.gcp.cloud_run_jobs import ConflictDetectionCrashed
from artisan_agents.gcp.firestore_client import TrivialConflictCapExceeded
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client

# gate2._open_pr_and_sync necessarily writes the pr_index pointer *after* GitHub assigns the PR
# number (it can't be written before the PR exists) — so a `pull_request.opened` webhook can
# reach here before that write lands. A short bounded retry absorbs that race instead of silently
# no-op-ing Gate 3's very first check (MILESTONE.md Sprint 4 close-out note; SPRINT.md Sprint 6).
_MAX_PR_LOOKUP_RETRIES = 3
_PR_LOOKUP_RETRY_DELAY_SECONDS = 1.0


async def handle_pull_request_event(repo: str, payload: dict) -> None:
    pr = payload["pull_request"]
    pr_number = pr["number"]
    ticket = await firestore_client.get_ticket_by_pr(repo, pr_number)
    for _ in range(_MAX_PR_LOOKUP_RETRIES):
        if ticket is not None:
            break
        await asyncio.sleep(_PR_LOOKUP_RETRY_DELAY_SECONDS)
        ticket = await firestore_client.get_ticket_by_pr(repo, pr_number)
    if ticket is None:
        return  # not an Artisan-tracked PR
    await start_gate3(
        repo=repo,
        issue_number=ticket.github_issue_number,
        jira_key=ticket.jira_key,
        pr_number=pr_number,
        pr_title=pr["title"],
        pr_body=pr.get("body") or "",
        base_branch=pr["base"]["ref"],
        head_branch=pr["head"]["ref"],
        head_sha=pr["head"]["sha"],
    )


async def start_gate3(
    *,
    repo: str,
    issue_number: int,
    jira_key: str,
    pr_number: int,
    pr_title: str,
    pr_body: str,
    base_branch: str,
    head_branch: str,
    head_sha: str,
) -> None:
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)
    event_context.set_sink(firestore_client.new_event_sink(ticket_id, gate="3"))
    await event_context.current_sink().emit(
        type="gate_started", summary="Gate 3: merge-conflict triage"
    )

    await firestore_client.update_ticket(repo, issue_number, current_step="detecting_conflict")
    try:
        detection = await cloud_run_jobs.trigger_conflict_detection(
            repo=repo, issue_number=issue_number, base_branch=base_branch,
            head_branch=head_branch, head_sha=head_sha,
        )
    except ConflictDetectionCrashed as exc:
        async with tracing.gate_span(
            ticket_id, "3", "escalate", label="Gate 3: conflict detection crashed"
        ):
            pass
        await _escalate(repo, issue_number, jira_key, pr_number, reason=f"conflict check crashed: {exc}")
        return

    if not detection.has_conflict:
        async with tracing.gate_span(ticket_id, "3", "proceed", label="Gate 3: no conflict detected"):
            pass
        return

    await firestore_client.update_ticket(repo, issue_number, current_step="classifying_conflict")
    verdict = await run_conflict_classification(pr_title=pr_title, pr_body=pr_body, detection=detection)

    if verdict.classification == "semantic":
        async with tracing.gate_span(
            ticket_id, "3", "escalate", label="Gate 3: semantic conflict escalated"
        ):
            pass
        if await firestore_client.claim_semantic_conflict_escalation(repo, issue_number):
            await _escalate_semantic(repo, issue_number, jira_key, pr_number, verdict)
        return

    # trivial: span at classification time...
    async with tracing.gate_span(ticket_id, "3", "proceed", label="Gate 3: trivial conflict classified"):
        pass
    try:
        await firestore_client.increment_trivial_conflict_attempt(repo, issue_number)
    except TrivialConflictCapExceeded:
        async with tracing.gate_span(
            ticket_id, "3", "escalate", label="Gate 3: trivial-conflict cap exceeded"
        ):
            pass
        await _escalate(
            repo, issue_number, jira_key, pr_number,
            reason="trivial-conflict attempt cap already reached",
        )
        return

    await firestore_client.update_ticket(repo, issue_number, current_step="resolving_conflict")
    resolution = await cloud_run_jobs.trigger_conflict_resolution(
        repo=repo, issue_number=issue_number, base_branch=base_branch, head_branch=head_branch,
    )
    await firestore_client.update_ticket(
        repo, issue_number, last_conflict_resolution=resolution.model_dump(mode="json")
    )

    # ...and a second span for the resolution outcome, per Phase 4.5.
    if resolution.tests_passed:
        async with tracing.gate_span(
            ticket_id, "3", "proceed", label="Gate 3: conflict resolution passed"
        ):
            pass
        await github_client.post_issue_comment(
            repo, pr_number,
            f"Artisan auto-resolved a trivial merge conflict (full test suite passed): "
            f"{resolution.diff_summary}",
        )
        await jira_client.add_comment(
            jira_key, f"Artisan auto-resolved a trivial merge conflict on PR #{pr_number}."
        )
        return

    async with tracing.gate_span(
        ticket_id, "3", "escalate", label="Gate 3: conflict resolution failed"
    ):
        pass
    await _escalate(
        repo, issue_number, jira_key, pr_number,
        reason=f"trivial-conflict resolution attempt failed: {resolution.diff_summary}",
    )


async def _escalate_semantic(
    repo: str, issue_number: int, jira_key: str, pr_number: int, verdict: ConflictVerdict
) -> None:
    comparison = verdict.comparison or "(no comparison produced)"
    await firestore_client.append_escalation(
        repo, issue_number, EscalationEntry(at=datetime.now(timezone.utc), reason=comparison, gate="3")
    )
    await github_client.post_issue_comment(
        repo, pr_number,
        f"Artisan detected a semantic merge conflict that needs a maintainer's judgment call:\n\n{comparison}",
    )
    await jira_client.add_comment(
        jira_key, f"Artisan needs manual pickup: semantic merge conflict on PR #{pr_number}.\n\n{comparison}"
    )


async def _escalate(
    repo: str, issue_number: int, jira_key: str, pr_number: int, *, reason: str
) -> None:
    await firestore_client.append_escalation(
        repo, issue_number, EscalationEntry(at=datetime.now(timezone.utc), reason=reason, gate="3")
    )
    await github_client.post_issue_comment(repo, pr_number, f"Artisan needs manual pickup: {reason}")
    await jira_client.add_comment(jira_key, f"Artisan needs manual pickup: {reason}")
