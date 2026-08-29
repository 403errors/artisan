"""Unit tests for the event-log truncation/redaction helpers and `TicketEvent` schema."""

import pytest
from artisan_shared.events import TicketEvent, redact_secrets, truncate, truncate_middle
from pydantic import ValidationError


def test_truncate_leaves_short_text_untouched() -> None:
    assert truncate("hello", 100) == ("hello", False)


def test_truncate_cuts_and_marks_long_text() -> None:
    text, truncated = truncate("x" * 1000, 50)
    assert truncated is True
    assert len(text) <= 50
    assert "truncated: 1000 chars total" in text


def test_truncate_middle_keeps_head_and_tail() -> None:
    text, truncated = truncate_middle("a" * 100 + "MIDDLE" + "b" * 100, head=10, tail=10)
    assert truncated is True
    assert text.startswith("a" * 10)
    assert text.endswith("b" * 10)
    assert "MIDDLE" not in text


def test_truncate_middle_leaves_short_text_untouched() -> None:
    assert truncate_middle("short", head=10, tail=10) == ("short", False)


def test_redact_secrets_strips_an_explicit_token() -> None:
    assert redact_secrets("token is abc123", token="abc123") == "token is ***"


def test_redact_secrets_strips_github_installation_token_shapes() -> None:
    ghs = "ghs_" + "a" * 36
    assert ghs not in redact_secrets(f"here: {ghs}")


def test_redact_secrets_strips_x_access_token_urls() -> None:
    text = "https://x-access-token:supersecret@github.com/acme/demo.git"
    redacted = redact_secrets(text)
    assert "supersecret" not in redacted


def test_redact_secrets_is_a_noop_on_clean_text() -> None:
    assert redact_secrets("nothing sensitive here") == "nothing sensitive here"


def test_ticket_event_roundtrip_with_at_unset() -> None:
    event = TicketEvent(
        seq=0,
        run_id="run-1",
        gate="2",
        type="tool_call",
        actor="coding_agent",
        summary="read_file(a.txt)",
        tool_name="read_file",
        tool_args={"path": "a.txt"},
    )
    assert event.at is None
    assert TicketEvent.model_validate_json(event.model_dump_json()) == event


def test_ticket_event_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        TicketEvent(seq=0, run_id="r", type="not_a_real_type", actor="x", summary="x")
