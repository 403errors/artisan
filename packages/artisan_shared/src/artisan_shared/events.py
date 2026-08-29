"""Agent-execution event log types + truncation/redaction helpers, shared between `agents/`
(orchestrator) and `execution-sandbox/`. Firestore stores these as `tickets/{ticketId}/events/{autoId}`
documents — a subcollection, not an array field on `TicketDoc`, since Firestore's ~1MiB per-document
cap would otherwise risk bricking the parent ticket doc's own writes on a busy ticket, and
`ArrayUnion` would silently dedupe identical-looking events (see `event_log.py` for the writer)."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

TicketEventType = Literal[
    "gate_started",
    "gate_decision",
    "step_changed",
    "agent_invoked",
    "agent_completed",
    "tool_call",
    "job_started",
    "job_completed",
    "clarification_asked",
    "clarification_answered",
    "pr_opened",
    "jira_synced",
    "escalated",
    "ticket_done",
    "manual_action",
    "error",
]

MAX_SUMMARY_CHARS = 500
MAX_DETAIL_CHARS = 4000
MAX_TOOL_ARG_CHARS = 500
MAX_TOOL_RESULT_CHARS = 2000

# GitHub App installation tokens (ghs_/ghp_/github_pat_ prefixes) and generic
# authorization-header-shaped strings — a regex-fallback safety net for when the caller doesn't
# have the live token in scope to pass explicitly (see redact_secrets' `token` param).
_SECRET_PATTERNS = [
    re.compile(r"ghs_[A-Za-z0-9]{36}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"x-access-token:[^@\s]*@"),
    re.compile(r"(?i)(authorization|api[_-]?token|password|secret)\s*[:=]\s*\S+"),
]


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """Truncates `text` to at most `limit` chars, appending a marker noting the original length.
    Returns (possibly-truncated text, whether truncation happened)."""
    if len(text) <= limit:
        return text, False
    marker = f"… [truncated: {len(text)} chars total]"
    head = text[: max(limit - len(marker), 0)]
    return head + marker, True


def truncate_middle(text: str, head: int, tail: int) -> tuple[str, bool]:
    """Keeps the first `head` and last `tail` chars, dropping the middle — a failing test's actual
    error is usually at the end of shell output, not the start, so a plain head-truncate would
    throw away the useful part."""
    if len(text) <= head + tail:
        return text, False
    marker = f"\n… [truncated: {len(text)} chars total] …\n"
    return text[:head] + marker + text[-tail:], True


def redact_secrets(text: str, *, token: str | None = None) -> str:
    """Strips a known live token (when the caller has it in scope, e.g. the execution-sandbox's
    installation token) plus regex fallbacks for common GitHub token shapes. Must run BEFORE
    truncation — a truncated-but-unredacted token is still a leak if it lands in the untruncated
    portion."""
    if token:
        text = text.replace(token, "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


class TicketEvent(BaseModel):
    """One entry in a ticket's `events` subcollection. `at` is `datetime | None` because the
    write path (`event_log.py::EventSink`) substitutes Firestore's `SERVER_TIMESTAMP` sentinel
    instead of a client-computed value — required since the orchestrator (Cloud Run service) and
    execution-sandbox (Cloud Run Job) are different processes with unbounded clock skew, and their
    events must interleave in a correct, server-authoritative order."""

    seq: int
    run_id: str
    at: datetime | None = None
    gate: Literal["1", "2", "3"] | None = None
    type: TicketEventType
    actor: str
    summary: str
    detail: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, str] | None = None
    tool_result_summary: str | None = None
    truncated: bool = False
