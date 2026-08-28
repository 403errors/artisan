"""Unit tests for the shared Firestore ticket doc-id scheme (Sprint 3 shared-package extraction —
see docs/CONTEXT.md). Both `agents/` and `execution-sandbox/` must resolve the same repo/issue
pair to the exact same doc id, or the execution-sandbox job's `last_execution_result` write would
land on a different document than the orchestrator later reads from."""

from artisan_shared.ticket_ids import ticket_doc_id


def test_deterministic_for_same_repo_and_issue() -> None:
    assert ticket_doc_id("acme/demo", 42) == ticket_doc_id("acme/demo", 42)


def test_slugifies_disallowed_characters_in_repo() -> None:
    assert ticket_doc_id("acme/demo", 1) == "acme_demo__1"


def test_different_issue_numbers_produce_different_ids() -> None:
    assert ticket_doc_id("acme/demo", 1) != ticket_doc_id("acme/demo", 2)
