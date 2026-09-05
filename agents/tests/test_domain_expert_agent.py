"""Unit tests for the Domain-Expert Agent (Phase 3.2 DoD): given a persona and issue, produces a
DomainExpertOutput matching that persona with a non-empty relevant-file list. Stubs the underlying
model — never calls live Gemini."""

import json
from datetime import datetime, timezone

import pytest
from artisan_agents import event_context
from artisan_agents.agents import domain_expert_agent as domain_expert_agent_module
from artisan_agents.agents.domain_expert_agent import _build_prompt, run_domain_expert
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.models import RepoContext

from tests.conftest import FakeLlm


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"

    def child(self, **kwargs):
        return self


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(
            domain_expert_agent_module.domain_expert_agent,
            "model",
            FakeLlm(response_text=response_json),
        )

    return _stub


@pytest.mark.asyncio
async def test_frontend_persona_produces_frontend_domain_output(stub_model) -> None:
    stub_model(
        '{"domain": "frontend", "technical_summary": "Change the submit button color to blue.", '
        '"relevant_files": ["src/components/SubmitButton.tsx"]}'
    )
    output = await run_domain_expert(
        domain="frontend",
        issue_title="Button color is wrong",
        issue_body="The submit button should be blue, not red.",
    )
    assert output.domain == "frontend"
    assert output.relevant_files


@pytest.mark.asyncio
async def test_backend_persona_produces_backend_domain_output(stub_model) -> None:
    stub_model(
        '{"domain": "backend", "technical_summary": "Add a /export endpoint returning CSV.", '
        '"relevant_files": ["src/routes/export.py"]}'
    )
    output = await run_domain_expert(
        domain="backend",
        issue_title="Add CSV export endpoint",
        issue_body="Need a backend endpoint that exports data as CSV.",
    )
    assert output.domain == "backend"
    assert output.relevant_files


@pytest.mark.asyncio
async def test_unknown_domain_falls_back_to_default_lens_instead_of_raising(stub_model) -> None:
    stub_model(
        '{"domain": "quantum-computing", "technical_summary": "Fix the qubit decoherence.", '
        '"relevant_files": ["circuits/main.py"]}'
    )
    output = await run_domain_expert(
        domain="quantum-computing",
        issue_title="Qubit decoherence is broken",
        issue_body="The entanglement circuit decoheres on small devices.",
    )
    assert output.domain == "quantum-computing"


def test_persona_lens_get_falls_back_to_default_lens_for_unknown_domain() -> None:
    prompt = _build_prompt("quantum-computing", "Title", "Body")
    assert "quantum-computing specialist" in prompt
    assert domain_expert_agent_module._DEFAULT_LENS.format(domain="quantum-computing") in prompt


def test_every_bespoke_lens_has_real_review_criteria_not_a_label() -> None:
    # The v2 wave-1 #2 contract: a bespoke lens is genuine expert depth, not a named label.
    # Guards against a shallow entry (empty focus, token criteria) ever passing CI.
    assert domain_expert_agent_module._PERSONA_LENSES, "registry must not be empty"
    for domain, lens in domain_expert_agent_module._PERSONA_LENSES.items():
        assert len(lens.focus) >= 80, f"{domain}: focus is too thin to be an expert lens"
        assert len(lens.review_criteria) >= 3, f"{domain}: needs at least 3 review criteria"
        for criterion in lens.review_criteria:
            assert len(criterion) >= 40, f"{domain}: criterion is a label, not a check: {criterion!r}"


def test_persona_domains_matches_lens_registry() -> None:
    assert domain_expert_agent_module.PERSONA_DOMAINS == tuple(
        domain_expert_agent_module._PERSONA_LENSES
    )


@pytest.mark.parametrize(
    "domain,expected_cue",
    [
        ("frontend", "Accessibility"),
        ("backend", "idempotent"),
        ("infra-devops", "rolled back"),
        ("mobile", "backgrounding"),
        ("data-ml", "leakage"),
        ("cli", "stderr"),
        ("embedded", "watchdog"),
        ("game", "frame"),
        ("security", "trust boundary"),
        ("database", "Migrations"),
    ],
)
def test_bespoke_lens_renders_focus_and_review_criteria(domain: str, expected_cue: str) -> None:
    prompt = _build_prompt(domain, "Title", "Body")
    assert "Review criteria" in prompt
    assert expected_cue in prompt
    # The generic fallback phrasing must not leak into a bespoke lens's prompt.
    assert "applying general software engineering judgment" not in prompt


def test_domain_lookup_normalizes_case_and_whitespace() -> None:
    for variant in ("Mobile", " mobile ", "MOBILE"):
        prompt = _build_prompt(variant, "Title", "Body")
        assert "backgrounding" in prompt, f"{variant!r} should hit the bespoke mobile lens"


def test_criteria_for_domains_collects_bespoke_criteria_domain_prefixed() -> None:
    # v2 wave 1.5 (#17): verification judges the executed change against exactly these.
    criteria = domain_expert_agent_module.criteria_for_domains(["backend", " Mobile "])
    assert criteria, "expected bespoke criteria"
    assert all(c.startswith(("[backend] ", "[mobile] ")) for c in criteria)
    backend_count = sum(c.startswith("[backend] ") for c in criteria)
    mobile_count = sum(c.startswith("[mobile] ") for c in criteria)
    assert backend_count == len(domain_expert_agent_module._PERSONA_LENSES["backend"].review_criteria)
    assert mobile_count == len(domain_expert_agent_module._PERSONA_LENSES["mobile"].review_criteria)


def test_criteria_for_domains_skips_fallback_domains() -> None:
    assert domain_expert_agent_module.criteria_for_domains(["quantum-computing"]) == []


# --- v2 wave 1.5 (#18): convention-doc grounding ---


def _ctx_with_conventions() -> RepoContext:
    return RepoContext(
        repo="octocat/demo",
        head_sha="deadbeef",
        file_tree=["CONTRIBUTING.md"],
        manifests={},
        languages={".py": 10},
        convention_docs={"CONTRIBUTING.md": "We never swallow exceptions silently."},
        fetched_at=datetime.now(timezone.utc),
    )


def test_bespoke_lens_prompt_includes_wrapped_repo_conventions() -> None:
    prompt = _build_prompt("backend", "Title", "Body", _ctx_with_conventions())
    assert "Repo conventions" in prompt
    assert "CONTRIBUTING.md" in prompt
    assert "<untrusted_content>\nWe never swallow exceptions silently.\n</untrusted_content>" in prompt


def test_fallback_lens_prompt_omits_repo_conventions() -> None:
    prompt = _build_prompt("quantum-computing", "Title", "Body", _ctx_with_conventions())
    assert "Repo conventions" not in prompt


def test_bespoke_lens_prompt_omits_conventions_section_when_no_docs() -> None:
    ctx = _ctx_with_conventions().model_copy(update={"convention_docs": {}})
    prompt = _build_prompt("backend", "Title", "Body", ctx)
    assert "Repo conventions" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "domain,expected_lens",
    [("backend", "bespoke"), (" Mobile ", "bespoke"), ("quantum-computing", "fallback")],
)
async def test_run_domain_expert_emits_domain_lens_used_event(
    stub_model, domain: str, expected_lens: str
) -> None:
    # v2 wave 1.5 (#14): every dispatch records which side of the lens registry it hit, so the
    # fallback rate — the health signal for the bespoke-lens investment — is computable.
    stub_model(
        '{"domain": "d", "technical_summary": "s", "relevant_files": ["f"]}'
    )
    sink = _RecordingSink()
    event_context.set_sink(sink)

    await run_domain_expert(domain=domain, issue_title="t", issue_body="b")

    lens_events = [e for e in sink.events if e["type"] == "domain_lens_used"]
    assert len(lens_events) == 1
    assert json.loads(lens_events[0]["detail"]) == {"domain": domain, "lens": expected_lens}


def test_prompt_omits_repo_context_section_when_none() -> None:
    prompt = _build_prompt("frontend", "Title", "Body", None)
    assert "Repo context" not in prompt


def test_prompt_includes_repo_context_summary_when_present() -> None:
    context = RepoContext(
        repo="octocat/demo",
        head_sha="deadbeef",
        file_tree=["pyproject.toml"],
        manifests={"pyproject.toml": ""},
        languages={".py": 10},
        fetched_at=datetime.now(timezone.utc),
    )
    prompt = _build_prompt("backend", "Title", "Body", context)
    assert "Repo context" in prompt
    assert "pyproject.toml" in prompt
