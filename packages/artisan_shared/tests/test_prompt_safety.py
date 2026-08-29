"""Unit tests for the prompt-injection isolation helpers (Sprint 7 WS2)."""

from artisan_shared.prompt_safety import (
    INJECTION_MARKERS,
    UNTRUSTED_CONTENT_NOTICE,
    flag_possible_injection,
    wrap_untrusted,
)


def test_wrap_untrusted_wraps_text_in_untrusted_content_tags() -> None:
    wrapped = wrap_untrusted("hello world")
    assert wrapped == "<untrusted_content>\nhello world\n</untrusted_content>"


def test_flag_possible_injection_true_for_each_marker_case_insensitively() -> None:
    for marker in INJECTION_MARKERS:
        assert flag_possible_injection(f"blah blah {marker.upper()} blah")
        assert flag_possible_injection(f"blah blah {marker} blah")


def test_flag_possible_injection_false_for_benign_text() -> None:
    assert not flag_possible_injection("The login page 404s when clicking the reset link.")


def test_untrusted_content_notice_is_nonempty_string() -> None:
    assert isinstance(UNTRUSTED_CONTENT_NOTICE, str)
    assert UNTRUSTED_CONTENT_NOTICE
