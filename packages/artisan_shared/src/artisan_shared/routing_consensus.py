"""Pure helpers for routing-decision consensus (self-consistency voting) and eval scoring.

Single source of truth shared by production routing
(agents/src/artisan_agents/agents/routing_agent.py) and the routing eval harness
(agents/evals/test_routing_eval.py) — agents/evals/ is not importable from production code, so
anything both sides need lives here.

- canonical_domains: off-registry labels collapse to one "fallback" token. Synonym drift across
  reps ("blockchain" vs "smart-contracts") is the same fallback *behavior* and must not count as
  disagreement — raw labels stay on the decision/report for audit.
- consensus_vote: majority vote over canonical sets. Ties prefer sets containing
  bespoke-registry domains (a registry lens plans with real review criteria; fallback is the
  shallower default), then earliest-seen, so the result is deterministic.
- agreement_to_confidence: maps the winning cluster's share to a derived confidence level —
  measured, unlike the model's self-reported confidence (the wave-1.5/1.7 evals showed that one
  is uncalibrated: "high" on every rep, including stable misses).
"""

from collections.abc import Iterable
from typing import Literal

FALLBACK_LABEL = "fallback"

Confidence = Literal["low", "medium", "high"]


def canonical_domains(domains: Iterable[str], registry: Iterable[str]) -> frozenset[str]:
    """Canonicalize a predicted domain set for voting/stability comparison: casing and
    whitespace are normalized (same rule the lens lookup applies), bespoke-registry labels are
    kept, every off-registry label maps to FALLBACK_LABEL."""
    registry_set = set(registry)
    return frozenset(
        d if d in registry_set else FALLBACK_LABEL
        for d in (label.strip().lower() for label in domains)
        if d
    )


def consensus_vote(
    canonical_sets: list[frozenset[str]], registry: Iterable[str]
) -> tuple[frozenset[str], float]:
    """Return (winning canonical set, agreement) where agreement is the winning cluster's share
    of all sets (1.0 = unanimous). Tie-break: sets containing a registry domain beat pure-
    fallback sets; remaining ties resolve to the earliest-seen set (dict order is insertion
    order, and max() keeps the first maximal item), so the vote is deterministic."""
    if not canonical_sets:
        raise ValueError("consensus_vote requires at least one prediction")
    registry_set = set(registry)
    clusters: dict[frozenset[str], int] = {}
    for s in canonical_sets:
        clusters[s] = clusters.get(s, 0) + 1

    def _rank(s: frozenset[str]) -> tuple[int, int]:
        has_registry = any(d in registry_set for d in s)
        return (clusters[s], 1 if has_registry else 0)

    winner = max(clusters, key=_rank)
    return winner, clusters[winner] / len(canonical_sets)


def agreement_to_confidence(agreement: float) -> Confidence:
    """Unanimous agreement -> high, majority -> medium, no majority -> low."""
    if agreement >= 1.0:
        return "high"
    if agreement > 0.5:
        return "medium"
    return "low"
