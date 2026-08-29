"""Gate 1 dispatch: routes a decoded GitHub webhook envelope through ticket bootstrap (2.2),
the Intake Agent (2.3), and the clarification loop + caps (2.4), tracing every decision (2.5).
Called from the /pubsub/push route only, after idempotency has already been checked. A sufficient
verdict hands off into Gate 2 (gate2.start_gate2, Sprint 3) in the same call. `pull_request` events
hand off into Gate 3 (gate3.handle_pull_request_event, Sprint 4)."""

from githubkit.exception import RequestFailed

from artisan_agents import completion, event_context, gate2, gate3, tracing
from artisan_agents.agents.intake_agent import run_intake
from artisan_agents.gcp import firestore_client
from artisan_agents.gcp.firestore_client import ClarificationCapExceeded
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client
from artisan_shared import prompt_safety
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
    elif (
        envelope.event == "pull_request"
        and envelope.action == "closed"
        and envelope.payload["pull_request"].get("merged") is True
    ):
        await _handle_pull_request_merged(envelope)


async def _handle_pull_request_merged(envelope: GitHubWebhookEnvelope) -> None:
    """Sprint 6: this branch didn't exist before — `pull_request.closed` deliveries were already
    flowing through Pub/Sub (per SUPPORTED_EVENTS) but silently dropped, so nothing ever moved a
    ticket to `done` despite docs/SYSTEM_DESIGN.md §9 claiming otherwise. `"pull_request"` needs
    no webhook-side change since it's already a subscribed event type."""
    pr_number = envelope.payload["pull_request"]["number"]
    ticket = await firestore_client.get_ticket_by_pr(envelope.repo, pr_number)
    if ticket is None:
        return  # not an Artisan-tracked PR
    await completion.mark_ticket_done(
        envelope.repo, ticket.github_issue_number, ticket.jira_key, trigger="merge"
    )


async def _handle_issue_opened(envelope: GitHubWebhookEnvelope) -> None:
    issue = envelope.payload["issue"]
    issue_number = issue["number"]
    ticket = await firestore_client.get_ticket(envelope.repo, issue_number)
    if ticket is None:
        jira_key = await jira_client.create_ticket(
            issue_number, issue["title"], issue["body"] or "", issue["html_url"]
        )
        ticket = await firestore_client.create_ticket(envelope.repo, issue_number, jira_key)
    if ticket.status == "intake":
        await evaluate_intake(envelope.repo, issue_number, ticket.jira_key)


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
        await evaluate_intake(envelope.repo, issue_number, ticket.jira_key)


#: Above this many raw markdown image URLs on an issue thread, dispatch.py routes the ticket to a
#: human before ever running the Intake Agent (WS1) — bounds both download cost and the number of
#: inline image parts stuffed into one Gemini prompt.
SUS_IMAGE_COUNT_THRESHOLD = 3

_SUS_IMAGE_COMMENT = (
    "This issue has several images attached — a maintainer will take a look before Artisan "
    "proceeds automatically."
)
_NOT_ACTIONABLE_COMMENT = (
    "This doesn't look like something Artisan can act on automatically — it's been handed to the "
    "team for a look."
)


async def evaluate_intake(repo: str, issue_number: int, jira_key: str) -> None:
    """Public (not `_`-prefixed) since a manual "retry Gate 1" action re-enters here directly,
    same as a fresh webhook would — Sprint 6's manual_actions.py."""
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)
    event_context.set_sink(firestore_client.new_event_sink(ticket_id, gate="1"))
    await event_context.current_sink().emit(type="gate_started", summary="Gate 1: evaluating intake")
    try:
        title, body, author_login, thread = await github_client.get_issue_thread(repo, issue_number)
    except RequestFailed as exc:
        if exc.response.status_code == 404:
            raise NonRetriableEventError(f"issue {repo}#{issue_number} not found") from exc
        raise

    injection_flagged = prompt_safety.flag_possible_injection(body)
    if injection_flagged:
        await event_context.current_sink().emit(
            type="injection_flagged",
            summary="Issue body flagged as a possible prompt-injection attempt",
        )

    if github_client.count_markdown_images(body, thread) > SUS_IMAGE_COUNT_THRESHOLD:
        # WS1 sus-image gate: never even attempt automated triage on an issue this image-heavy —
        # hand it straight to a maintainer instead of spending an Intake Agent call on it.
        await github_client.post_issue_comment(repo, issue_number, _SUS_IMAGE_COMMENT)
        await firestore_client.mark_needs_human_review(repo, issue_number)
        return

    await firestore_client.update_ticket(repo, issue_number, current_step="evaluating_intake")
    images = await github_client.extract_and_download_images(title, body, thread)
    verdict = await run_intake(
        issue_title=title,
        issue_body=body,
        thread=thread,
        jira_key=jira_key,
        images=images,
        injection_flagged=injection_flagged,
    )

    if verdict.verdict == "sufficient":
        ticket = await firestore_client.get_ticket(repo, issue_number)
        if ticket is not None and ticket.clarification_rounds > 0:
            await github_client.post_issue_comment(
                repo,
                issue_number,
                f"@{author_login} Thanks — that's enough to proceed. Artisan is taking over "
                "from here to resolve this issue.",
            )
            # The Jira description is otherwise write-once from the original (often vague) issue
            # body — fold the reply thread in now so a Jira-only reader can see what was clarified
            # without needing to cross-reference the GitHub issue.
            clarifications = "\n\n".join(thread)
            await jira_client.update_description(
                jira_key,
                f"{body}\n\n---\nClarifications (from GitHub issue thread):\n{clarifications}",
            )
            # Sprint 7: the dashboard's activity feed had nowhere to show the issuer's replies —
            # `clarification_asked` only ever carried the *questions*. This carries the answers.
            await event_context.current_sink().emit(
                type="clarification_answered",
                summary="Issuer replied with clarifying information",
                detail=clarifications,
            )
        await jira_client.transition_ticket(jira_key, "In Progress")
        await firestore_client.update_ticket(repo, issue_number, status="in_progress")
        async with tracing.gate_span(ticket_id, "1", "proceed", label="Gate 1: intake sufficient"):
            pass
        await gate2.start_gate2(repo, issue_number, jira_key, issue_title=title, issue_body=body)
        return

    if verdict.verdict == "not_actionable":
        await github_client.post_issue_comment(repo, issue_number, _NOT_ACTIONABLE_COMMENT)
        await firestore_client.mark_manual_pickup_directly(
            repo, issue_number, reason="not_actionable"
        )
        await jira_client.add_comment(
            jira_key,
            "Artisan needs manual pickup: this issue has no actionable engineering ask.",
        )
        return

    # verdict.verdict == "needs_info"
    questions_list = "\n".join(
        f"{i}. {question}" for i, question in enumerate(verdict.missing_context_questions, start=1)
    )
    questions_comment = f"@{author_login} could you help clarify a few things?\n\n{questions_list}"
    await github_client.post_issue_comment(repo, issue_number, questions_comment)
    await event_context.current_sink().emit(type="clarification_asked", summary=questions_list)
    try:
        await firestore_client.increment_clarification_round(repo, issue_number)
        async with tracing.gate_span(ticket_id, "1", "ask", label="Gate 1: clarification requested"):
            pass
    except ClarificationCapExceeded:
        await jira_client.add_comment(
            jira_key,
            "Artisan needs manual pickup: 3 clarification rounds without sufficient context.",
        )
        async with tracing.gate_span(
            ticket_id, "1", "escalate", label="Gate 1: clarification cap exceeded"
        ):
            pass
