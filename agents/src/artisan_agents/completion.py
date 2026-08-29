"""Idempotent Jira+Firestore transition to `done`. Two callers — a real GitHub merge webhook
(`dispatch.handle_event`'s `pull_request.closed && merged` branch) and a manual dashboard action
(`manual_actions.py`) — share this one function rather than being two separate paths that could
race each other and disagree.

Per docs/PRD.md §5: "Never moves a ticket to Done on its own — merge by a human is the only
trigger for that transition." Confirmed by reading every status= assignment in this codebase that
nothing sets status="done" today — this closes that real, pre-existing gap."""

from artisan_agents.event_context import current_sink
from artisan_agents.gcp import firestore_client
from artisan_agents.jira import client as jira_client
from artisan_agents.jira.client import JiraClientError


async def mark_ticket_done(
    repo: str, issue_number: int, jira_key: str, *, trigger: str, actor: str | None = None
) -> None:
    """No-ops if the ticket is already `done` — a real merge webhook and a manual "mark resolved"
    action racing each other must not both apply this twice. Firestore is updated before Jira, and
    a Jira failure does not roll back the Firestore write — Firestore is the source of truth
    (SYSTEM_DESIGN.md §7); a Jira hiccup shouldn't leave the ticket looking unfinished."""
    ticket = await firestore_client.get_ticket(repo, issue_number)
    if ticket is not None and ticket.status == "done":
        return

    await firestore_client.update_ticket(repo, issue_number, status="done", current_step=None)
    summary = f"Marked done (trigger={trigger})"
    if actor:
        summary += f", actor={actor}"
    await current_sink().emit(type="ticket_done", summary=summary)

    try:
        await jira_client.transition_ticket(jira_key, "Done")
        await current_sink().emit(type="jira_synced", summary=f"Transitioned {jira_key} to Done")
    except JiraClientError as exc:
        await current_sink().emit(type="error", summary=f"Jira Done transition failed: {exc}")
