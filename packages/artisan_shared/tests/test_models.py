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
    ManualActionEnvelope,
    Plan,
    RoutingDecision,
    VerificationVerdict,
)


def test_routing_decision_round_trips_through_json() -> None:
    decision = RoutingDecision(domains=["frontend", "backend"], parallel=True)
    assert RoutingDecision.model_validate_json(decision.model_dump_json()) == decision


def test_routing_decision_accepts_non_web_domain() -> None:
    # WS4: domains are open-ended strings now — the routing agent derives a fitting domain name
    # from repo context rather than being constrained to a fixed 3-way Literal.
    decision = RoutingDecision(domains=["mobile"], parallel=False)
    assert decision.domains == ["mobile"]
    assert decision.subproject is None


def test_routing_decision_subproject_defaults_to_none_and_round_trips() -> None:
    decision = RoutingDecision(domains=["backend"], parallel=False, subproject="services/api")
    assert RoutingDecision.model_validate_json(decision.model_dump_json()) == decision


def test_intake_verdict_needs_info_carries_missing_context_questions() -> None:
    verdict = IntakeVerdict(verdict="needs_info", missing_context_questions=["which endpoint?"])
    assert verdict.verdict == "needs_info"
    assert verdict.missing_context_questions == ["which endpoint?"]


def test_intake_verdict_sufficient_defaults_to_no_questions() -> None:
    verdict = IntakeVerdict(verdict="sufficient")
    assert verdict.missing_context_questions == []


def test_intake_verdict_rejects_unknown_verdict_value() -> None:
    with pytest.raises(ValidationError):
        IntakeVerdict(verdict="maybe")


def test_domain_expert_output_accepts_non_web_domain() -> None:
    # WS4: `domain` is an open-ended string matching `RoutingDecision.domains`'s new type.
    output = DomainExpertOutput(domain="devops-unknown", technical_summary="x", relevant_files=[])
    assert output.domain == "devops-unknown"


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


def test_github_webhook_envelope_defaults_kind_for_backward_compat() -> None:
    envelope = GitHubWebhookEnvelope(
        delivery_id="abc-123",
        event="issues",
        action="opened",
        repo="403errors/artisan-demo",
        payload={},
    )
    assert envelope.kind == "github_event"


def test_manual_action_envelope_roundtrip() -> None:
    envelope = ManualActionEnvelope(
        action_id="uuid-1",
        action="retry_gate2",
        repo="403errors/artisan-demo",
        issue_number=10,
        actor="user:octocat",
        reason="stuck",
    )
    assert envelope.kind == "manual_action"
    assert ManualActionEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_manual_action_envelope_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        ManualActionEnvelope(
            action_id="uuid-1",
            action="retry_everything",
            repo="403errors/artisan-demo",
            issue_number=10,
            actor="user:octocat",
        )
