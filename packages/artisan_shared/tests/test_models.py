"""Round-trip tests for the shared typed I/O models (moved here from `agents/tests/test_models.py`
in Sprint 3's shared-package extraction — see docs/CONTEXT.md — since both `agents/` and
`execution-sandbox/` now depend on this module)."""

import pytest
from pydantic import ValidationError

from artisan_shared.models import (
    ConflictDetectionResult,
    ConflictVerdict,
    DomainExpertOutput,
    ExecutionResult,
    GitHubWebhookEnvelope,
    IntakeVerdict,
    Plan,
    RoutingDecision,
    VerificationVerdict,
)


def test_routing_decision_round_trips_through_json() -> None:
    decision = RoutingDecision(domains=["frontend", "backend"], parallel=True)
    assert RoutingDecision.model_validate_json(decision.model_dump_json()) == decision


def test_routing_decision_rejects_unknown_domain() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision(domains=["mobile"], parallel=False)


def test_intake_verdict_insufficient_requires_no_question_field_by_default() -> None:
    verdict = IntakeVerdict(sufficient=False, missing_context_question="which endpoint?")
    assert verdict.sufficient is False
    assert verdict.missing_context_question == "which endpoint?"


def test_domain_expert_output_rejects_unknown_domain() -> None:
    with pytest.raises(ValidationError):
        DomainExpertOutput(domain="devops-unknown", technical_summary="x", relevant_files=[])


def test_plan_roundtrip() -> None:
    plan = Plan(steps=["a"], touched_files=["b.py"], test_cases=["c"], doc_updates=["d.md"])
    assert Plan.model_validate(plan.model_dump()) == plan


def test_execution_result_and_verification_verdict_roundtrip() -> None:
    result = ExecutionResult(branch="artisan/ART-1", diff_summary="x", tests_passed=True, logs_uri="gs://x")
    verdict = VerificationVerdict(green=True, feedback=None)
    assert result.tests_passed is True
    assert verdict.green is True


def test_conflict_verdict_classification_literal() -> None:
    verdict = ConflictVerdict(classification="trivial")
    assert verdict.classification in ("trivial", "semantic")


def test_conflict_detection_result_roundtrip() -> None:
    result = ConflictDetectionResult(
        has_conflict=True,
        conflicted_files=["a.py"],
        conflict_markers="<<<<<<<",
        base_branch_history="abc123 main: change",
        diff_summary="1 file changed",
        logs_uri="gs://x",
        head_sha="deadbeef",
    )
    assert ConflictDetectionResult.model_validate_json(result.model_dump_json()) == result


def test_github_webhook_envelope_roundtrip() -> None:
    envelope = GitHubWebhookEnvelope(
        delivery_id="abc-123",
        event="issues",
        action="opened",
        repo="403errors/artisan-demo",
        payload={"issue": {"number": 1}},
    )
    assert GitHubWebhookEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_github_webhook_envelope_rejects_unsupported_event() -> None:
    with pytest.raises(ValidationError):
        GitHubWebhookEnvelope(
            delivery_id="abc-123",
            event="star",
            action="created",
            repo="403errors/artisan-demo",
            payload={},
        )
