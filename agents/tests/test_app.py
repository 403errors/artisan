"""Route-level tests for the orchestrator's two HTTP endpoints (Phase 2.1 DoD): bad signatures
are rejected, valid deliveries are published, and duplicate Pub/Sub deliveries are a no-op."""

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from artisan_agents import app as app_module

SECRET = "test-webhook-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "get_secret", lambda name: SECRET)
    with TestClient(app_module.app) as test_client:
        yield test_client


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_github_webhook_rejects_bad_signature(client) -> None:
    body = json.dumps({"action": "opened", "repository": {"full_name": "a/b"}}).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "d-1",
        },
    )
    assert response.status_code == 401


def test_github_webhook_publishes_valid_delivery(client, monkeypatch) -> None:
    published = []
    monkeypatch.setattr(app_module, "publish_github_event", lambda envelope: published.append(envelope))

    body = json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "403errors/artisan-demo"},
            "issue": {"number": 1},
        }
    ).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "d-1",
        },
    )
    assert response.status_code == 200
    assert len(published) == 1
    assert published[0].delivery_id == "d-1"


def test_pubsub_push_rejects_invalid_token(client, monkeypatch) -> None:
    from artisan_agents.gcp.pubsub import PushTokenVerificationError

    def _fail(_header):
        raise PushTokenVerificationError("bad token")

    monkeypatch.setattr(app_module, "verify_push_token", _fail)
    response = client.post("/pubsub/push", json={"message": {"data": ""}})
    assert response.status_code == 401


def test_pubsub_push_is_a_no_op_for_a_duplicate_delivery(client, monkeypatch) -> None:
    from artisan_shared.models import GitHubWebhookEnvelope

    envelope = GitHubWebhookEnvelope(
        delivery_id="d-1", event="issues", action="opened", repo="a/b", payload={}
    )
    monkeypatch.setattr(app_module, "verify_push_token", lambda _header: None)
    monkeypatch.setattr(app_module, "decode_push_message", lambda _body: envelope)

    async def _claim(_delivery_id):
        return False  # already claimed by another (still-fresh or completed) attempt

    dispatched = []

    async def _handle_event(_envelope):
        dispatched.append(_envelope)

    monkeypatch.setattr(app_module, "claim_delivery", _claim)
    monkeypatch.setattr(app_module, "handle_event", _handle_event)

    response = client.post(
        "/pubsub/push",
        json={"message": {"data": base64.b64encode(b"{}").decode()}},
    )
    assert response.status_code == 200
    assert dispatched == []


def test_pubsub_push_dispatches_and_marks_completed_for_a_new_delivery(client, monkeypatch) -> None:
    from artisan_shared.models import GitHubWebhookEnvelope

    envelope = GitHubWebhookEnvelope(
        delivery_id="d-2", event="issues", action="opened", repo="a/b", payload={}
    )
    monkeypatch.setattr(app_module, "verify_push_token", lambda _header: None)
    monkeypatch.setattr(app_module, "decode_push_message", lambda _body: envelope)

    async def _claim(_delivery_id):
        return True

    dispatched = []
    completed = []

    async def _handle_event(_envelope):
        dispatched.append(_envelope)

    async def _mark_completed(delivery_id):
        completed.append(delivery_id)

    monkeypatch.setattr(app_module, "claim_delivery", _claim)
    monkeypatch.setattr(app_module, "handle_event", _handle_event)
    monkeypatch.setattr(app_module, "mark_delivery_completed", _mark_completed)

    response = client.post(
        "/pubsub/push",
        json={"message": {"data": base64.b64encode(b"{}").decode()}},
    )
    assert response.status_code == 200
    assert len(dispatched) == 1
    assert completed == ["d-2"]


def test_pubsub_push_marks_failed_and_reraises_on_handler_exception(client, monkeypatch) -> None:
    from artisan_shared.models import GitHubWebhookEnvelope

    envelope = GitHubWebhookEnvelope(
        delivery_id="d-3", event="issues", action="opened", repo="a/b", payload={}
    )
    monkeypatch.setattr(app_module, "verify_push_token", lambda _header: None)
    monkeypatch.setattr(app_module, "decode_push_message", lambda _body: envelope)

    async def _claim(_delivery_id):
        return True

    async def _handle_event(_envelope):
        raise RuntimeError("boom")

    failed = []
    completed = []

    async def _mark_failed(delivery_id):
        failed.append(delivery_id)

    async def _mark_completed(delivery_id):
        completed.append(delivery_id)

    monkeypatch.setattr(app_module, "claim_delivery", _claim)
    monkeypatch.setattr(app_module, "handle_event", _handle_event)
    monkeypatch.setattr(app_module, "mark_delivery_failed", _mark_failed)
    monkeypatch.setattr(app_module, "mark_delivery_completed", _mark_completed)

    with pytest.raises(RuntimeError):
        client.post(
            "/pubsub/push",
            json={"message": {"data": base64.b64encode(b"{}").decode()}},
        )
    assert failed == ["d-3"]
    assert completed == []
