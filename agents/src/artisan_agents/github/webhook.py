"""GitHub webhook signature verification + envelope parsing. Runs at the /webhooks/github
ingestion route, before anything is published to Pub/Sub — this is the only place the raw request
body is available, so signature verification must happen here, not downstream."""

import hashlib
import hmac
import json

from artisan_shared.models import GitHubWebhookEnvelope

SUPPORTED_EVENTS = {"issues", "issue_comment", "pull_request"}


def verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Verifies `X-Hub-Signature-256` (`sha256=<hexdigest>`) via constant-time comparison."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def parse_envelope(
    *, delivery_id: str, event: str, raw_body: bytes
) -> GitHubWebhookEnvelope | None:
    """Returns None for event types we don't act on (cross-cutting: only publish what the
    orchestrator will actually consume, to keep the Pub/Sub topic free of noise)."""
    if event not in SUPPORTED_EVENTS:
        return None
    payload = json.loads(raw_body)
    return GitHubWebhookEnvelope(
        delivery_id=delivery_id,
        event=event,
        action=payload.get("action", ""),
        repo=payload["repository"]["full_name"],
        payload=payload,
    )
