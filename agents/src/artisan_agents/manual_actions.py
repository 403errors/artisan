"""Handles a `ManualActionEnvelope` published by the dashboard (Sprint 6): retry a gate, force an
escalation, or mark a ticket resolved. Reaches `/pubsub/push` the same way a real GitHub webhook
does (app.py discriminates on `envelope.kind`) — reusing OIDC-authenticated ingress, at-least-once
delivery, and `claim_delivery`'s idempotency rather than building a second mechanism.

Every branch emits a `manual_action` event first, so the audit record survives even if the action
itself then fails."""

from datetime import datetime, timezone

from artisan_agents import dispatch, event_context, gate2, gate3
from artisan_agents.completion import mark_ticket_done
from artisan_agents.gcp import firestore_client
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client
from artisan_shared.firestore_schema import EscalationEntry, TicketDoc
from artisan_shared.models import ManualActionEnvelope

# A double-click guard, not a real lock: a live ticket whose Firestore doc was written this
# recently is assumed to be a genuinely-running attempt, so a second manual action against it is
# rejected rather than launching an overlapping run.
_IN_FLIGHT_GUARD_SECONDS = 30

_GATE2_STEPS = {"routing", "domain_expert", "planning", "executing", "verifying", "opening_pr"}
_GATE3_STEPS = {"detecting_conflict", "classifying_conflict", "resolving_conflict"}


class ManualActionRejected(Exception):
    """Raised when a manual action can't proceed right now (e.g. no PR to retry Gate 3 against,
    or the ticket looks like it's already actively running) — recorded as an `error` event and
    swallowed, not re-raised: Pub/Sub must not keep retrying a request that will fail identically
    forever, unlike a genuine transient failure (which propagates normally)."""


def _infer_gate(ticket: TicketDoc) -> str:
    """Mirrors dashboard/src/lib/ticket-derived.ts::currentGate exactly, so a force-escalate's
    EscalationEntry.gate matches what the dashboard would already show for this ticket."""
    prefix = (ticket.current_step or "").split(" ")[0]
    if prefix in _GATE3_STEPS:
        return "3"
    if prefix in _GATE2_STEPS:
        return "2"
    if ticket.status == "intake":
        return "1"
    if ticket.escalation_history:
        return ticket.escalation_history[-1].gate
    if ticket.last_conflict_detection is not None:
        return "3"
    if ticket.pr_url:
        return "2"
    return "1"


def _looks_actively_running(ticket: TicketDoc) -> bool:
    if ticket.status not in ("intake", "in_progress"):
        return False
    age = datetime.now(timezone.utc) - ticket.updated_at
    return age.total_seconds() < _IN_FLIGHT_GUARD_SECONDS


async def handle_action(envelope: ManualActionEnvelope) -> None:
    ticket = await firestore_client.get_ticket(envelope.repo, envelope.issue_number)
    if ticket is None:
        return  # not a ticket Artisan tracks — mirrors gate3's untracked-PR no-op

    ticket_id = firestore_client.ticket_doc_id(envelope.repo, envelope.issue_number)
    sink = firestore_client.new_event_sink(
        ticket_id, gate=_infer_gate(ticket), actor=f"user:{envelope.actor}"
    )
    event_context.set_sink(sink)
    await sink.emit(
        type="manual_action",
        summary=f"Manually requested: {envelope.action}",
        detail=envelope.reason,
    )

    if _looks_actively_running(ticket):
        await sink.emit(
            type="error",
            summary="Manual action rejected — ticket is already actively being worked",
        )
        return

    try:
        if envelope.action == "retry_gate1":
            await _retry_gate1(envelope, ticket)
        elif envelope.action == "retry_gate2":
            await _retry_gate2(envelope, ticket)
        elif envelope.action == "retry_gate3":
            await _retry_gate3(envelope, ticket)
        elif envelope.action == "escalate":
            await _escalate(envelope, ticket)
        elif envelope.action == "mark_done":
            await mark_ticket_done(
                envelope.repo,
                envelope.issue_number,
                ticket.jira_key,
                trigger="manual",
                actor=envelope.actor,
            )
    except ManualActionRejected as exc:
        await event_context.current_sink().emit(type="error", summary=str(exc))


async def _retry_gate1(envelope: ManualActionEnvelope, ticket: TicketDoc) -> None:
    # An explicit human grant of fresh clarification budget, not a cap bypass — the cap is still
    # Firestore-enforced from this point forward, a human is just resetting it deliberately.
    await firestore_client.update_ticket(
        envelope.repo, envelope.issue_number, clarification_rounds=0, status="intake"
    )
    await dispatch.evaluate_intake(envelope.repo, envelope.issue_number, ticket.jira_key)


async def _retry_gate2(envelope: ManualActionEnvelope, ticket: TicketDoc) -> None:
    new_generation = ticket.manual_retry_generation + 1
    await firestore_client.update_ticket(
        envelope.repo,
        envelope.issue_number,
        retry_count=0,
        status="in_progress",
        manual_retry_generation=new_generation,
    )
    title, body, _author, _thread = await github_client.get_issue_thread(
        envelope.repo, envelope.issue_number
    )
    await gate2.start_gate2(
        envelope.repo,
        envelope.issue_number,
        ticket.jira_key,
        issue_title=title,
        issue_body=body,
        retry_generation=new_generation,
    )


async def _retry_gate3(envelope: ManualActionEnvelope, ticket: TicketDoc) -> None:
    if ticket.pr_number is None:
        raise ManualActionRejected("ticket has no PR to retry Gate 3 against")

    await firestore_client.update_ticket(envelope.repo, envelope.issue_number, trivial_conflict_attempts=0)
    title, body, base_ref, head_ref, head_sha = await github_client.get_pull_request(
        envelope.repo, ticket.pr_number
    )
    await gate3.start_gate3(
        repo=envelope.repo,
        issue_number=envelope.issue_number,
        jira_key=ticket.jira_key,
        pr_number=ticket.pr_number,
        pr_title=title,
        pr_body=body,
        base_branch=base_ref,
        head_branch=head_ref,
        head_sha=head_sha,
    )


async def _escalate(envelope: ManualActionEnvelope, ticket: TicketDoc) -> None:
    reason = envelope.reason or "manually escalated, no reason given"
    entry = EscalationEntry(
        at=datetime.now(timezone.utc),
        reason=f"Manually escalated by {envelope.actor}: {reason}",
        gate=_infer_gate(ticket),
    )
    await firestore_client.append_escalation(envelope.repo, envelope.issue_number, entry)
    # Same dual GitHub+Jira notify agents already do on escalation (SYSTEM_DESIGN.md §9:
    # "escalation is always visible in both systems") — not skipped just because this one was
    # triggered by a human instead of an agent.
    await github_client.post_issue_comment(
        envelope.repo, envelope.issue_number, f"Artisan needs manual pickup: {reason}"
    )
    await jira_client.add_comment(ticket.jira_key, f"Artisan needs manual pickup: {reason}")
