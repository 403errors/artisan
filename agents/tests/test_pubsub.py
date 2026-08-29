"""Unit tests for `gcp.pubsub.decode_push_message`'s union decode (Sprint 6): a manual-action
message and a real GitHub webhook envelope share the same Pub/Sub topic, discriminated by `kind`."""

import base64
import json

from artisan_agents.gcp.pubsub import decode_push_message
from artisan_shared.models import GitHubWebhookEnvelope, ManualActionEnvelope


def _push_body(payload: dict) -> dict:
    return {"message": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}}


def test_decodes_a_github_webhook_envelope_with_explicit_kind() -> None:
    envelope = decode_push_message(
        _push_body(
            {
                "kind": "github_event",
                "delivery_id": "d-1",
                "event": "issues",
                "action": "opened",
                "repo": "acme/demo",
                "payload": {},
            }
        )
    )
    assert isinstance(envelope, GitHubWebhookEnvelope)
    assert envelope.delivery_id == "d-1"


def test_decodes_a_github_webhook_envelope_with_no_kind_field_at_all() -> None:
    """Messages published before ManualActionEnvelope existed have no `kind` field — must still
    decode as a GitHubWebhookEnvelope, not fail validation."""
    envelope = decode_push_message(
        _push_body(
            {
                "delivery_id": "d-2",
                "event": "issues",
                "action": "opened",
                "repo": "acme/demo",
                "payload": {},
            }
        )
    )
    assert isinstance(envelope, GitHubWebhookEnvelope)


def test_decodes_a_manual_action_envelope() -> None:
    envelope = decode_push_message(
        _push_body(
            {
                "kind": "manual_action",
                "action_id": "uuid-1",
                "action": "retry_gate2",
                "repo": "acme/demo",
                "issue_number": 1,
                "actor": "user:octocat",
            }
        )
    )
    assert isinstance(envelope, ManualActionEnvelope)
    assert envelope.action == "retry_gate2"
