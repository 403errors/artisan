"""Orchestrator Cloud Run service. Two routes (MILESTONE.md Phase 2.1):

- POST /webhooks/github: GitHub's registered webhook URL. Verifies the HMAC signature while the
  raw body is still available, then publishes to Pub/Sub and returns fast. No side effects beyond
  that — this route's only job is fast, verified ingestion.
- POST /pubsub/push: the push subscription's target. Verifies the Pub/Sub-issued OIDC token,
  atomically claims the delivery via `processed_deliveries` *before* dispatching (cross-cutting
  rule 5 — claim-before-process, not check-then-mark-after, since Gate 2 can run for minutes and a
  naive after-the-fact mark leaves a window for Pub/Sub's own redelivery to double-process), then
  dispatches (dispatch.py).
"""

from contextlib import asynccontextmanager

from artisan_shared.models import ManualActionEnvelope
from fastapi import FastAPI, Request, Response

from artisan_agents import manual_actions, tracing
from artisan_agents.config import SECRET_GITHUB_WEBHOOK_SECRET
from artisan_agents.dispatch import NonRetriableEventError, handle_event
from artisan_agents.gcp.firestore_client import (
    claim_delivery,
    mark_delivery_completed,
    mark_delivery_failed,
)
from artisan_agents.gcp.pubsub import (
    PushTokenVerificationError,
    decode_push_message,
    publish_github_event,
    verify_push_token,
)
from artisan_agents.gcp.secrets import get_secret
from artisan_agents.github.webhook import parse_envelope, verify_signature


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    tracing.setup_tracing()
    yield


app = FastAPI(title="artisan-orchestrator", lifespan=_lifespan)


@app.post("/webhooks/github")
async def github_webhook(request: Request) -> Response:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    secret = get_secret(SECRET_GITHUB_WEBHOOK_SECRET)
    if not verify_signature(raw_body, signature, secret):
        return Response(status_code=401)

    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    event = request.headers.get("X-GitHub-Event", "")
    envelope = parse_envelope(delivery_id=delivery_id, event=event, raw_body=raw_body)
    if envelope is not None:
        publish_github_event(envelope)
    return Response(status_code=200)


@app.post("/pubsub/push")
async def pubsub_push(request: Request) -> Response:
    try:
        verify_push_token(request.headers.get("Authorization"))
    except PushTokenVerificationError:
        return Response(status_code=401)

    body = await request.json()
    envelope = decode_push_message(body)
    # ManualActionEnvelope has no delivery_id (it's dashboard-originated, not a GitHub delivery) —
    # action_id is its own claim_delivery key instead, serving the identical double-delivery-guard
    # purpose.
    claim_key = (
        envelope.action_id if isinstance(envelope, ManualActionEnvelope) else envelope.delivery_id
    )

    if not await claim_delivery(claim_key):
        return Response(status_code=200)

    try:
        if isinstance(envelope, ManualActionEnvelope):
            await manual_actions.handle_action(envelope)
        else:
            await handle_event(envelope)
    except NonRetriableEventError:
        # This delivery will fail identically forever (e.g. the GitHub issue it references
        # doesn't exist) — mark it completed so Pub/Sub doesn't burn the dead-letter budget
        # retrying something that can never succeed.
        await mark_delivery_completed(claim_key)
        return Response(status_code=200)
    except Exception:
        await mark_delivery_failed(claim_key)
        raise

    await mark_delivery_completed(claim_key)
    return Response(status_code=200)
