"""Unit tests for github/webhook.py — signature verification must run correctly on the raw body,
since a forged webhook is the entire threat model for the public /webhooks/github route."""

import hashlib
import hmac
import json

from artisan_agents.github.webhook import parse_envelope, verify_signature

SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_accepts_correctly_signed_body() -> None:
    body = b'{"action": "opened"}'
    assert verify_signature(body, _sign(body), SECRET) is True


def test_verify_signature_rejects_tampered_body() -> None:
    body = b'{"action": "opened"}'
    signature = _sign(body)
    tampered = b'{"action": "closed"}'
    assert verify_signature(tampered, signature, SECRET) is False


def test_verify_signature_rejects_wrong_secret() -> None:
    body = b'{"action": "opened"}'
    assert verify_signature(body, _sign(body, secret="wrong-secret"), SECRET) is False


def test_verify_signature_rejects_missing_or_malformed_header() -> None:
    body = b'{"action": "opened"}'
    assert verify_signature(body, None, SECRET) is False
    assert verify_signature(body, "not-a-real-signature", SECRET) is False


def test_parse_envelope_extracts_repo_and_action() -> None:
    body = json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "403errors/artisan-demo"},
            "issue": {"number": 1},
        }
    ).encode("utf-8")
    envelope = parse_envelope(delivery_id="d-1", event="issues", raw_body=body)
    assert envelope is not None
    assert envelope.delivery_id == "d-1"
    assert envelope.event == "issues"
    assert envelope.action == "opened"
    assert envelope.repo == "403errors/artisan-demo"
    assert envelope.payload["issue"]["number"] == 1


def test_parse_envelope_returns_none_for_unsupported_event() -> None:
    body = json.dumps({"action": "created", "repository": {"full_name": "a/b"}}).encode("utf-8")
    assert parse_envelope(delivery_id="d-1", event="star", raw_body=body) is None
