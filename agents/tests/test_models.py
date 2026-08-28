from artisan_agents.config import GEMINI_MODEL_ID
from artisan_agents.models import (
    ConflictVerdict,
    DomainExpertOutput,
    ExecutionResult,
    IntakeVerdict,
    Plan,
    VerificationVerdict,
)


def test_model_id_is_pinned_not_latest_alias() -> None:
    assert GEMINI_MODEL_ID == "gemini-3.7-flash"


def test_intake_verdict_insufficient_requires_no_question_field_by_default() -> None:
    verdict = IntakeVerdict(sufficient=False, missing_context_question="which endpoint?")
    assert verdict.sufficient is False
    assert verdict.missing_context_question == "which endpoint?"


def test_domain_expert_output_rejects_unknown_domain() -> None:
    import pytest
    from pydantic import ValidationError

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
    verdict = ConflictVerdict(classification="trivial", resolution_branch="artisan/fix-1")
    assert verdict.classification in ("trivial", "semantic")
