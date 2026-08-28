"""Gate 1 dispatch: routes a decoded GitHub webhook envelope through ticket bootstrap (2.2),
the Intake Agent (2.3), and the clarification loop + caps (2.4), tracing every decision (2.5).
Called from the /pubsub/push route only, after idempotency has already been checked. A sufficient
verdict hands off into Gate 2 (gate2.start_gate2, Sprint 3) in the same call. `pull_request` events
hand off into Gate 3 (gate3.handle_pull_request_event, Sprint 4)."""

from githubkit.exception import RequestFailed

from artisan_agents import gate2, gate3, tracing
from artisan_agents.agents.intake_agent import run_intake
from artisan_agents.gcp import firestore_client
from artisan_agents.gcp.firestore_client import ClarificationCapExceeded
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client
from artisan_shared.models import GitHubWebhookEnvelope


class NonRetriableEventError(Exception):
    """Raised when a webhook event can never succeed no matter how many times Pub/Sub
    redelivers it (e.g. the referenced GitHub issue doesn't exist). Distinct from every other
    exception in this codebase, which is domain-level (caps, crashed jobs) — this one exists
    purely so app.py's push handler can ack instead of retrying a doomed delivery."""


async def handle_event(envelope: GitHubWebhookEnvelope) -> None:
    if envelope.event == "issues" and envelope.action == "opened":
        await _handle_issue_opened(envelope)
    elif envelope.event == "issue_comment" and envelope.action == "created":
        await _handle_issue_comment(envelope)
    elif envelope.event == "pull_request" and envelope.action in {"opened", "synchronize"}:
        await gate3.handle_pull_request_event(envelope.repo, envelope.payload)


async def _handle_issue_opened(envelope: GitHubWebhookEnvelope) -> None:
    issue = envelope.payload["issue"]
    issue_number = issue["number"]
    ticket = await firestore_client.get_ticket(envelope.repo, issue_number)
    if ticket is None:
        jira_key = await jira_client.create_ticket(
            issue["title"], issue["body"] or "", issue["html_url"]
        )
        ticket = await firestore_client.create_ticket(envelope.repo, issue_number, jira_key)
    if ticket.status == "intake":
        await _evaluate_intake(envelope.repo, issue_number, ticket.jira_key)


async def _handle_issue_comment(envelope: GitHubWebhookEnvelope) -> None:
    comment_author_type = envelope.payload.get("comment", {}).get("user", {}).get("type")
    if comment_author_type == "Bot":
        # Never re-trigger on Artisan's own clarifying comment (or any other bot's) — only a
        # human reply should re-enter the clarification loop.
        return
    issue = envelope.payload["issue"]
    issue_number = issue["number"]
    ticket = await firestore_client.get_ticket(envelope.repo, issue_number)
    if ticket is not None and ticket.status == "intake":
        await _evaluate_intake(envelope.repo, issue_number, ticket.jira_key)


async def _evaluate_intake(repo: str, issue_number: int, jira_key: str) -> None:
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)
    try:
        title, body, thread = await github_client.get_issue_thread(repo, issue_number)
    except RequestFailed as exc:
        if exc.response.status_code == 404:
            raise NonRetriableEventError(f"issue {repo}#{issue_number} not found") from exc
        raise
    verdict = await run_intake(
        issue_title=title, issue_body=body, thread=thread, jira_key=jira_key
    )

    if verdict.sufficient:
        await jira_client.transition_ticket(jira_key, "In Progress")
        await firestore_client.update_ticket(repo, issue_number, status="in_progress")
        with tracing.gate_span(ticket_id, "1", "proceed"):
            pass
        await gate2.start_gate2(repo, issue_number, jira_key, issue_title=title, issue_body=body)
        return

    await github_client.post_issue_comment(
        repo, issue_number, verdict.missing_context_question or ""
    )
    try:
        await firestore_client.increment_clarification_round(repo, issue_number)
        with tracing.gate_span(ticket_id, "1", "ask"):
            pass
    except ClarificationCapExceeded:
        await jira_client.add_comment(
            jira_key,
            "Artisan needs manual pickup: 3 clarification rounds without sufficient context.",
        )
        with tracing.gate_span(ticket_id, "1", "escalate"):
            pass
