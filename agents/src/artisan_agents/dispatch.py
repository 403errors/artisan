"""Event dispatch: routes a decoded GitHub webhook envelope through ticket bootstrap (2.2),
the Intake Agent (2.3), and the clarification loop + caps (2.4), tracing every decision (2.5).
Called from the /pubsub/push route only, after idempotency has already been checked. A sufficient
verdict hands off into Gate 2 (gate2.start_gate2, Sprint 3) in the same call. `pull_request` events
hand off into Gate 3 (gate3.handle_pull_request_event, Sprint 4). The two terminal triggers live
here too: `pull_request.closed && merged` -> completion.mark_ticket_done (Sprint 6) and
`issues.deleted` -> completion.handle_issue_deleted (Sprint 7/8)."""

from datetime import datetime, timezone

from githubkit.exception import RequestFailed

from artisan_agents import completion, event_context, gate2, gate3, tracing
from artisan_agents.agents.duplicate_agent import run_duplicate_check
from artisan_agents.agents.duplicate_confirm_agent import run_duplicate_confirm
from artisan_agents.agents.intake_agent import run_intake
from artisan_agents.config import MAX_DUPLICATE_FOLLOWUPS
from artisan_agents.gcp import firestore_client
from artisan_agents.gcp.firestore_client import ClarificationCapExceeded
from artisan_agents.github import client as github_client
from artisan_agents.jira import client as jira_client
from artisan_shared import prompt_safety
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import DuplicateCandidate, GitHubWebhookEnvelope


class NonRetriableEventError(Exception):
    """Raised when a webhook event can never succeed no matter how many times Pub/Sub
    redelivers it (e.g. the referenced GitHub issue doesn't exist). Distinct from every other
    exception in this codebase, which is domain-level (caps, crashed jobs) — this one exists
    purely so app.py's push handler can ack instead of retrying a doomed delivery."""


#: Step prefixes per gate — shared with manual_actions.infer_gate so a force-escalate's
#: EscalationEntry.gate and the issue-deleted event sink's gate both match what the dashboard
#: would already show for this ticket (dashboard/src/lib/ticket-derived.ts::currentGate).
_GATE2_STEPS = {"routing", "domain_expert", "planning", "executing", "verifying", "opening_pr"}
_GATE3_STEPS = {"detecting_conflict", "classifying_conflict", "resolving_conflict"}


def infer_gate(ticket: TicketDoc) -> str:
    """Mirrors dashboard/src/lib/ticket-derived.ts::currentGate exactly, so events/entries tagged
    from a ticket's current state land on the same gate the dashboard would show for it."""
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
    elif envelope.event == "issues" and envelope.action == "deleted":
        await _handle_issue_deleted(envelope)


async def _handle_issue_deleted(envelope: GitHubWebhookEnvelope) -> None:
    """`issues.deleted` webhook (Sprint 7/8): the issuer removed the issue, so the ticket is moot
    — neutralize it via completion.handle_issue_deleted (Firestore `done` + event, close any
    Artisan PR, Jira `Done` + comment). A ticket Artisan never tracked is a no-op, mirroring the
    untracked-PR no-op in `_handle_pull_request_merged`. Unlike `_handle_pull_request_merged`, this
    installs a real event sink — the `issue_deleted`/`pr_closed` audit trail is the point of the
    path, not an incidental."""
    issue_number = envelope.payload["issue"]["number"]
    ticket = await firestore_client.get_ticket(envelope.repo, issue_number)
    if ticket is None:
        return  # not a ticket Artisan tracks
    ticket_id = firestore_client.ticket_doc_id(envelope.repo, issue_number)
    event_context.set_sink(firestore_client.new_event_sink(ticket_id, gate=infer_gate(ticket)))
    await completion.handle_issue_deleted(
        envelope.repo, issue_number, ticket.jira_key, pr_number=ticket.pr_number
    )


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
    if ticket is None or ticket.status == "done":
        # A pre-existing `done` doc on a *new* `opened` delivery means the original issue was
        # deleted — a live issue keeps its number forever, so a number is only ever reusable
        # after deletion (the issue-deleted cleanup lands the old doc in `done`). Start fresh
        # rather than letting a future issue #N inherit the dead ticket's stale plan/PR state.
        jira_key, jira_summary = await jira_client.create_ticket(
            issue_number, issue["title"], issue["body"] or "", issue["html_url"]
        )
        ticket = await firestore_client.create_ticket(envelope.repo, issue_number, jira_key, jira_summary)
    if ticket.status == "intake":
        await evaluate_intake(envelope.repo, issue_number, ticket.jira_key)


async def _handle_issue_comment(envelope: GitHubWebhookEnvelope) -> None:
    comment_author_type = envelope.payload.get("comment", {}).get("user", {}).get("type")
    if comment_author_type == "Bot":
        # Never re-trigger on Artisan's own comments (or any other bot's) — only a human reply
        # should re-enter the clarification loop or answer a duplicate flag.
        return
    issue = envelope.payload["issue"]
    issue_number = issue["number"]
    ticket = await firestore_client.get_ticket(envelope.repo, issue_number)
    if ticket is None:
        return
    if ticket.status == "duplicate_review":
        await _handle_duplicate_review_comment(envelope, ticket)
        return
    if ticket.status == "intake":
        await evaluate_intake(envelope.repo, issue_number, ticket.jira_key)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_duplicate_flag_comment(candidates: list[DuplicateCandidate]) -> str:
    """The body Artisan posts when it flags a new issue as a likely duplicate (Gate 1) — with a
    link to every candidate so the reporter can check each one manually. Also reconstructed by
    `_handle_duplicate_review_comment` so the Duplicate Confirm Agent sees exactly what was asked.
    The @-mention of the reporter is added by `_flag_duplicates`, which has the login."""
    links = "\n".join(f"- #{c.issue_number}: {c.title} — {c.html_url}" for c in candidates)
    return (
        "Artisan found existing issues that look like they may cover the same request:\n\n"
        f"{links}\n\n"
        "If this is the same issue, reply confirming and Artisan will close this one out. "
        "If it's actually different, reply explaining how it differs and Artisan will proceed "
        "automatically."
    )


async def _flag_duplicates(
    repo: str, issue_number: int, author_login: str, candidates: list[DuplicateCandidate]
) -> None:
    """Posts the duplicate-flag comment (@-mentioning the reporter, linking every candidate), moves
    the ticket to `duplicate_review`, and records the candidates + check time on the doc. The
    ticket now waits on a human reply (`_handle_duplicate_review_comment`) — nothing is ever
    auto-closed (PRD.md §5)."""
    await github_client.post_issue_comment(
        repo, issue_number, f"@{author_login} {build_duplicate_flag_comment(candidates)}"
    )
    await firestore_client.update_ticket(
        repo,
        issue_number,
        status="duplicate_review",
        current_step="duplicate_review",
        duplicate_checked_at=_utcnow(),
        duplicate_candidates=[c.model_dump(mode="json") for c in candidates],
    )
    await event_context.current_sink().emit(
        type="duplicate_flagged",
        summary="Flagged #"
        + str(issue_number)
        + " as a possible duplicate of "
        + ", ".join(f"#{c.issue_number}" for c in candidates),
    )
    async with tracing.gate_span(
        firestore_client.ticket_doc_id(repo, issue_number),
        "1",
        "ask",
        label="Gate 1: duplicate flag posted",
    ):
        pass


#: How many "please confirm" follow-ups Artisan posts when the reply to a duplicate flag is
#: ambiguous — after this, the issue proceeds to normal intake rather than blocking forever.
_DUPLICATE_FOLLOWUP_COMMENT = (
    "Could you confirm whether this is the same as the issue(s) above, or a different one? "
    "If it's the same, reply 'duplicate'; if it's different, describe what's different and "
    "Artisan will proceed."
)


async def _handle_duplicate_review_comment(
    envelope: GitHubWebhookEnvelope, ticket: TicketDoc
) -> None:
    """A human replied to Artisan's duplicate-flag comment while the ticket is in
    `duplicate_review` (Gate 1). Classify the reply:
    - `confirm_duplicate` -> close the issue as a duplicate + neutralize the ticket
      (`completion.mark_ticket_duplicate`).
    - `not_duplicate` -> clear the candidates, return to `intake`, and run normal intake.
    - `needs_clarification` -> one follow-up comment (capped by MAX_DUPLICATE_FOLLOWUPS), then
      treat as not_duplicate so an unresolved thread never blocks the issue forever."""
    repo = envelope.repo
    issue_number = envelope.payload["issue"]["number"]
    reply = envelope.payload.get("comment", {}).get("body") or ""
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)
    verdict = await run_duplicate_confirm(
        candidates=ticket.duplicate_candidates,
        flag_comment=build_duplicate_flag_comment(ticket.duplicate_candidates),
        reply=reply,
    )

    if verdict.intent == "confirm_duplicate":
        duplicate_of = verdict.target_issue_number or (
            ticket.duplicate_candidates[0].issue_number if ticket.duplicate_candidates else None
        )
        if duplicate_of is not None:
            await completion.mark_ticket_duplicate(
                repo, issue_number, ticket.jira_key, duplicate_of=duplicate_of
            )
            return
        # No candidate to point at (shouldn't happen while in duplicate_review) — proceed below
        # rather than dead-ending.

    if verdict.intent == "not_duplicate" or ticket.duplicate_followups >= MAX_DUPLICATE_FOLLOWUPS:
        await firestore_client.update_ticket(
            repo,
            issue_number,
            status="intake",
            duplicate_candidates=[],
        )
        await event_context.current_sink().emit(
            type="duplicate_rejected",
            summary="Confirmed not a duplicate — proceeding with intake",
        )
        async with tracing.gate_span(
            ticket_id, "1", "proceed", label="Gate 1: duplicate rejected, proceeding to intake"
        ):
            pass
        await evaluate_intake(repo, issue_number, ticket.jira_key)
        return

    # needs_clarification, with follow-up budget left — ask once more.
    await github_client.post_issue_comment(repo, issue_number, _DUPLICATE_FOLLOWUP_COMMENT)
    await firestore_client.update_ticket(
        repo, issue_number, duplicate_followups=ticket.duplicate_followups + 1
    )
    await event_context.current_sink().emit(
        type="clarification_asked",
        summary="Duplicate confirmation reply was ambiguous — asked once more",
    )


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
            # The issue was deleted between the webhook firing and this delivery being processed —
            # neutralize the ticket (the `issues.deleted` webhook may not have been processed yet)
            # before acking, so it isn't left stuck in `intake` forever.
            ticket = await firestore_client.get_ticket(repo, issue_number)
            if ticket is not None:
                await completion.handle_issue_deleted(
                    repo, issue_number, ticket.jira_key, pr_number=ticket.pr_number
                )
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

    # Gate 1 duplicate check (SYSTEM_DESIGN.md §3): runs at most once per issue, guarded by
    # `duplicate_checked_at` so re-delivered webhooks and manual Gate 1 retries never re-run it
    # (nor re-flag an already-confirmed issue). If strong candidates exist, flag the issue and ask
    # the reporter to confirm instead of automating immediately.
    ticket = await firestore_client.get_ticket(repo, issue_number)
    if ticket is not None and ticket.duplicate_checked_at is None:
        candidates = await run_duplicate_check(
            repo=repo,
            issue_number=issue_number,
            issue_title=title,
            issue_body=body,
            jira_key=jira_key,
        )
        if candidates:
            await _flag_duplicates(repo, issue_number, author_login, candidates)
            return
        await firestore_client.update_ticket(
            repo, issue_number, duplicate_checked_at=datetime.now(timezone.utc)
        )

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
        else:
            # First-pass sufficient: no clarification round preceded this, so the reporter never
            # got any acknowledgement that automation engaged — without this comment the first
            # thing they'd see is a PR appearing out of nowhere. Post a short notification so the
            # issuer always knows Artisan picked the issue up.
            await github_client.post_issue_comment(
                repo,
                issue_number,
                f"@{author_login} Thanks for the details — Artisan has everything it needs and "
                "is taking over to resolve this issue.",
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
