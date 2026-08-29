"""Shared writer for the `tickets/{ticketId}/events` subcollection. `agents/` and
`execution-sandbox/` each bind their own Firestore client (different construction — see each
package's `gcp/firestore_client.py`/`firestore_write.py`) but share this emit/patch/truncate/redact
logic. Every public method swallows its own exceptions: an audit log must never be able to fail a
gate or a coding-agent tool call."""

import logging
import uuid
from typing import Any

from google.cloud import firestore

from artisan_shared.events import (
    MAX_DETAIL_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TOOL_ARG_CHARS,
    MAX_TOOL_RESULT_CHARS,
    TicketEventType,
    redact_secrets,
    truncate,
)

logger = logging.getLogger(__name__)


class EventSink:
    """Appends events to `tickets/{ticket_id}/events` for one ticket. `seq` is a plain in-process
    counter — a same-server-timestamp-tick tiebreaker only, not a global ordering guarantee (that
    would need a Firestore transaction per event, contending with the coding agent's hot loop for
    no real benefit: nothing downstream needs gap-free ordering, only display order)."""

    def __init__(
        self,
        client: firestore.AsyncClient | None,
        ticket_id: str,
        *,
        gate: str | None = None,
        actor: str = "orchestrator",
        redact_token: str | None = None,
        run_id: str | None = None,
        enabled: bool = True,
        _seq_box: list[int] | None = None,
    ) -> None:
        self._client = client
        self._ticket_id = ticket_id
        self._gate = gate
        self._actor = actor
        self._redact_token = redact_token
        self._run_id = run_id or str(uuid.uuid4())
        self._enabled = enabled
        self._seq_box = _seq_box if _seq_box is not None else [0]

    def _next_seq(self) -> int:
        seq = self._seq_box[0]
        self._seq_box[0] += 1
        return seq

    def child(self, *, gate: str | None = None, actor: str | None = None) -> "EventSink":
        """A sink sharing this one's run_id/seq counter but scoped to a different gate/actor —
        keeps events from one logical run ordered relative to each other even across gate/actor
        boundaries within the same process."""
        return EventSink(
            self._client,
            self._ticket_id,
            gate=gate if gate is not None else self._gate,
            actor=actor if actor is not None else self._actor,
            redact_token=self._redact_token,
            run_id=self._run_id,
            enabled=self._enabled,
            _seq_box=self._seq_box,
        )

    def _clean(self, text: str, limit: int) -> tuple[str, bool]:
        return truncate(redact_secrets(text, token=self._redact_token), limit)

    async def emit(
        self,
        *,
        type: TicketEventType,
        summary: str,
        gate: str | None = None,
        detail: str | None = None,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        tool_result_summary: str | None = None,
    ) -> str | None:
        """Appends one event doc. Returns the new doc's id (for a later `patch`), or `None` if the
        sink is disabled or the write failed."""
        if not self._enabled or self._client is None:
            return None
        try:
            truncated = False

            summary, t = self._clean(summary, MAX_SUMMARY_CHARS)
            truncated = truncated or t

            if detail is not None:
                detail, t = self._clean(detail, MAX_DETAIL_CHARS)
                truncated = truncated or t

            if tool_result_summary is not None:
                tool_result_summary, t = self._clean(tool_result_summary, MAX_TOOL_RESULT_CHARS)
                truncated = truncated or t

            clean_args: dict[str, str] | None = None
            if tool_args is not None:
                clean_args = {}
                for key, value in tool_args.items():
                    text, t = self._clean(str(value), MAX_TOOL_ARG_CHARS)
                    truncated = truncated or t
                    clean_args[key] = text

            doc_ref = (
                self._client.collection("tickets")
                .document(self._ticket_id)
                .collection("events")
                .document()
            )
            await doc_ref.set(
                {
                    "seq": self._next_seq(),
                    "run_id": self._run_id,
                    "at": firestore.SERVER_TIMESTAMP,
                    "gate": gate if gate is not None else self._gate,
                    "type": type,
                    "actor": self._actor,
                    "summary": summary,
                    "detail": detail,
                    "tool_name": tool_name,
                    "tool_args": clean_args,
                    "tool_result_summary": tool_result_summary,
                    "truncated": truncated,
                }
            )
            return doc_ref.id
        except Exception:
            logger.exception("event sink emit failed for ticket %s", self._ticket_id)
            return None

    async def patch(self, doc_id: str | None, **fields: Any) -> None:
        """Updates an existing event doc — used to attach a tool's result onto the same event
        created for its call, correlated by `FunctionCall.id`/`FunctionResponse.id`."""
        if not self._enabled or self._client is None or not doc_id:
            return
        try:
            clean: dict[str, Any] = {}
            if "tool_result_summary" in fields and fields["tool_result_summary"] is not None:
                text, truncated = self._clean(fields["tool_result_summary"], MAX_TOOL_RESULT_CHARS)
                clean["tool_result_summary"] = text
                if truncated:
                    clean["truncated"] = True
            if not clean:
                return
            await (
                self._client.collection("tickets")
                .document(self._ticket_id)
                .collection("events")
                .document(doc_id)
                .update(clean)
            )
        except Exception:
            logger.exception(
                "event sink patch failed for ticket %s doc %s", self._ticket_id, doc_id
            )


class NoOpEventSink(EventSink):
    """The default sink when no ticket context is active — every method is a safe no-op."""

    def __init__(self) -> None:
        super().__init__(client=None, ticket_id="", enabled=False)
