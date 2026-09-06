"""Unit tests for artisan_shared.routing_consensus — the pure voting/canonicalization helpers
shared by production routing (run_routing self-consistency) and the routing eval harness."""

import pytest
from artisan_shared.routing_consensus import (
    FALLBACK_LABEL,
    agreement_to_confidence,
    canonical_domains,
    consensus_vote,
)

REGISTRY = ("frontend", "backend", "infra-devops", "security", "database")


def test_canonical_keeps_registry_labels():
    assert canonical_domains(["backend", "database"], REGISTRY) == frozenset(
        {"backend", "database"}
    )


def test_canonical_collapses_off_registry_labels_to_fallback():
    # Synonym drift across reps is the same fallback behavior — one token.
    assert canonical_domains(["blockchain"], REGISTRY) == frozenset({FALLBACK_LABEL})
    assert canonical_domains(["smart-contracts"], REGISTRY) == frozenset({FALLBACK_LABEL})


def test_canonical_normalizes_case_and_whitespace():
    assert canonical_domains([" Backend ", "BLOCKCHAIN"], REGISTRY) == frozenset(
        {"backend", FALLBACK_LABEL}
    )


def test_canonical_drops_empty_labels():
    assert canonical_domains(["", "  "], REGISTRY) == frozenset()


def test_consensus_unanimous():
    sets = [frozenset({"backend"})] * 3
    winner, agreement = consensus_vote(sets, REGISTRY)
    assert winner == frozenset({"backend"})
    assert agreement == 1.0


def test_consensus_majority():
    sets = [frozenset({"backend"}), frozenset({"backend"}), frozenset({"frontend"})]
    winner, agreement = consensus_vote(sets, REGISTRY)
    assert winner == frozenset({"backend"})
    assert agreement == pytest.approx(2 / 3)


def test_consensus_synonym_drift_votes_together():
    # blockchain / smart-contracts / blockchain — three identical canonical sets.
    reps = [["blockchain"], ["smart-contracts"], ["blockchain"]]
    sets = [canonical_domains(r, REGISTRY) for r in reps]
    winner, agreement = consensus_vote(sets, REGISTRY)
    assert winner == frozenset({FALLBACK_LABEL})
    assert agreement == 1.0


def test_consensus_tie_prefers_registry_containing_set():
    sets = [frozenset({"backend"}), frozenset({FALLBACK_LABEL})]
    winner, agreement = consensus_vote(sets, REGISTRY)
    assert winner == frozenset({"backend"})
    assert agreement == 0.5


def test_consensus_tie_break_is_deterministic_first_seen():
    sets = [frozenset({"frontend"}), frozenset({"backend"})]
    winner, _ = consensus_vote(sets, REGISTRY)
    assert winner == frozenset({"frontend"})


def test_consensus_requires_predictions():
    with pytest.raises(ValueError):
        consensus_vote([], REGISTRY)


def test_agreement_to_confidence_thresholds():
    assert agreement_to_confidence(1.0) == "high"
    assert agreement_to_confidence(2 / 3) == "medium"
    assert agreement_to_confidence(1 / 3) == "low"
    assert agreement_to_confidence(0.5) == "low"  # no majority
