"""Publish GitHub webhook envelopes to `artisan-github-events`, and verify the OIDC token Pub/Sub
attaches to its push-subscription delivery back to /pubsub/push. Per SYSTEM_DESIGN.md §3 step 1-2."""

import base64
import json
from functools import lru_cache

from google.auth.transport import requests as gauth_requests
from google.cloud import pubsub_v1
from google.oauth2 import id_token

from artisan_agents.config import GCP_PROJECT_ID, PUBSUB_PUSH_AUDIENCE, PUBSUB_TOPIC
from artisan_shared.models import GitHubWebhookEnvelope


class PushTokenVerificationError(Exception):
    """Raised when a request to /pubsub/push doesn't carry a valid Pub/Sub-issued OIDC token."""


@lru_cache(maxsize=1)
def _publisher() -> pubsub_v1.PublisherClient:
    return pubsub_v1.PublisherClient()


def publish_github_event(envelope: GitHubWebhookEnvelope) -> str:
    """Publishes the envelope as the message body; returns the Pub/Sub message id."""
    topic_path = _publisher().topic_path(GCP_PROJECT_ID, PUBSUB_TOPIC)
    data = envelope.model_dump_json().encode("utf-8")
    future = _publisher().publish(topic_path, data)
    return future.result()


def verify_push_token(authorization_header: str | None) -> None:
    """Raises PushTokenVerificationError unless `authorization_header` is a valid
    `Bearer <OIDC token>` minted by Pub/Sub for our push subscription's audience."""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise PushTokenVerificationError("missing or malformed Authorization header")
    token = authorization_header.removeprefix("Bearer ")
    try:
        claims = id_token.verify_oauth2_token(
            token, gauth_requests.Request(), audience=PUBSUB_PUSH_AUDIENCE or None
        )
    except ValueError as exc:
        raise PushTokenVerificationError(str(exc)) from exc
    if PUBSUB_PUSH_AUDIENCE and claims.get("aud") != PUBSUB_PUSH_AUDIENCE:
        raise PushTokenVerificationError("unexpected audience")


def decode_push_message(body: dict) -> GitHubWebhookEnvelope:
    """Decodes a Pub/Sub push request body's base64 `message.data` back into the envelope."""
    raw = base64.b64decode(body["message"]["data"])
    return GitHubWebhookEnvelope.model_validate(json.loads(raw))
