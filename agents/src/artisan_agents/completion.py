"""Idempotent terminal transitions shared by multiple callers, so distinct triggers never race
each other and disagree. Three functions:

- `mark_ticket_done` — the *success* terminal state. Callers: a real GitHub merge webhook
  (`dispatch.handle_event`'s `pull_request.closed && merged` branch) and a manual dashboard action
  (`manual_actions.py`).
- `handle_issue_deleted` — the *withdrawn* terminal state, when the issuer deletes the GitHub
  issue itself. Callers: the `issues.deleted` webhook branch and the 404 race path (an issue
  deleted mid-flight shows up to in-flight gates as a 404 on the issue).
- `mark_ticket_duplicate` — the *duplicate* terminal state, when the reporter confirms a flagged
  issue is a duplicate of an existing one (Gate 1 duplicate check, `dispatch._flag_duplicates`).
  Caller: `dispatch._handle_duplicate_review_comment`. The issue is closed as a duplicate only
  after that human confirmation — never on Artisan's own initiative.

All three: no-op if the ticket is already `done`, write Firestore first (single source of truth per
docs/PRD.md §5 — "merge by a human is the only trigger for that transition" and its siblings), and
treat Jira as best-effort — a Jira failure never rolls back the Firestore write.

Per docs/PRD.md §5: "Never moves a ticket to Done on its own — merge by a human is the only
trigger for that transition." Confirmed by reading every status= assignment in this codebase that
nothing sets status="done" outside this module — this closes that real, pre-existing gap."""

from artisan_agents.event_context import current_sink
from artisan_agents.gcp import firestore_client
from artisan_agents.github import client as github_client
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


async def handle_issue_deleted(
    repo: str, issue_number: int, jira_key: str, *, pr_number: int | None = None
) -> None:
    """Terminal cleanup when the issuer deletes the GitHub issue. Same shape as `mark_ticket_done`
    (idempotent no-op if already `done`, Firestore first, Jira best-effort) plus one extra job:
    closing any Artisan-opened PR for the issue.

    Because a deleted issue frees its number for reuse, the old doc must not survive in a
    non-terminal state or a future issue reusing the number would inherit stale plan/PR state —
    so this lands the ticket in the same terminal `done` a merge would, distinguished only by the
    `issue_deleted` event. The PR is closed because it's Artisan's own PR (PRD.md §5's "never
    operate on repo state it doesn't own" is not violated) and has no rationale left once the
    issue it resolves is gone."""
    ticket = await firestore_client.get_ticket(repo, issue_number)
    if ticket is not None and ticket.status == "done":
        return

    await firestore_client.update_ticket(repo, issue_number, status="done", current_step=None)
    await current_sink().emit(
        type="issue_deleted",
        summary=f"GitHub issue #{issue_number} deleted by its author — ticket closed out",
    )

    if pr_number is not None:
        try:
            await github_client.close_pull_request(
                repo,
                pr_number,
                f"Closing this PR — the issue it resolves (#{issue_number}) was deleted by its "
                "author, so there's nothing left to merge.",
            )
            await current_sink().emit(
                type="pr_closed", summary=f"Closed Artisan PR #{pr_number} (issue deleted)"
            )
        except Exception as exc:  # noqa: BLE001 - best-effort close; must never abort the flow
            await current_sink().emit(
                type="error", summary=f"Failed to close PR #{pr_number}: {exc}"
            )

    try:
        await jira_client.add_comment(
            jira_key,
            f"GitHub issue #{issue_number} was deleted by its author — Artisan closed this "
            "ticket out.",
        )
        await jira_client.transition_ticket(jira_key, "Done")
        await current_sink().emit(type="jira_synced", summary=f"Transitioned {jira_key} to Done")
    except JiraClientError as exc:
        await current_sink().emit(type="error", summary=f"Jira Done transition failed: {exc}")


async def mark_ticket_duplicate(
    repo: str,
    issue_number: int,
    jira_key: str,
    *,
    duplicate_of: int,
    actor: str | None = None,
) -> None:
    """Terminal transition when the reporter confirms a flagged issue is a duplicate (Gate 1
    duplicate check). Same shape as `mark_ticket_done`/`handle_issue_deleted` — idempotent no-op if
    already `done`, Firestore first (single source of truth), then the GitHub close and Jira move
    are best-effort.

    The GitHub issue is closed as a duplicate (explanatory comment + `state_reason="not_planned"`)
    and Jira moves to Done with an explanatory comment. Only ever called after the reporter
    confirmed — Artisan never closes an issue on its own initiative (PRD.md §5)."""
    ticket = await firestore_client.get_ticket(repo, issue_number)
    if ticket is not None and ticket.status == "done":
        return

    await firestore_client.update_ticket(repo, issue_number, status="done", current_step=None)
    summary = f"Closed #{issue_number} as a duplicate of #{duplicate_of}"
    if actor:
        summary += f", actor={actor}"
    await current_sink().emit(type="duplicate_confirmed", summary=summary)

    try:
        await github_client.close_issue_as_duplicate(repo, issue_number, duplicate_of)
    except Exception as exc:  # noqa: BLE001 - best-effort close; must never abort the flow
        await current_sink().emit(
            type="error", summary=f"Failed to close #{issue_number} as duplicate: {exc}"
        )

    try:
        await jira_client.add_comment(
            jira_key,
            f"GitHub issue #{issue_number} was confirmed a duplicate of #{duplicate_of} — "
            "Artisan closed this ticket out.",
        )
        await jira_client.transition_ticket(jira_key, "Done")
        await current_sink().emit(type="jira_synced", summary=f"Transitioned {jira_key} to Done")
    except JiraClientError as exc:
        await current_sink().emit(type="error", summary=f"Jira Done transition failed: {exc}")
