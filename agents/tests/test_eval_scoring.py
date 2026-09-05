"""Unit tests for the eval harnesses' pure scoring rules (agents/evals/scoring.py) — the
path-matching contract decides every expert-eval number, so it gets CI-covered tests even though
the harness itself is live-only."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

from scoring import covers, file_precision_recall, grounded, normalize_path  # noqa: E402

TREE = [
    "src/pages/settings.tsx",
    "src/components/SettingsForm.tsx",
    "src/lib/api.ts",
    "package.json",
    "README.md",
]


def test_normalize_strips_dot_slash_and_trailing_slash():
    assert normalize_path("./src/pages/") == "src/pages"
    assert normalize_path("src\\pages\\settings.tsx") == "src/pages/settings.tsx"


def test_exact_match_covers():
    assert covers("src/pages/settings.tsx", "src/pages/settings.tsx")


def test_ancestor_directory_covers():
    assert covers("src/pages", "src/pages/settings.tsx")
    assert covers("src", "src/pages/settings.tsx")


def test_prediction_under_labeled_directory_covers():
    assert covers("src/pages/settings.tsx", "src/pages")


def test_sibling_does_not_cover():
    assert not covers("src/pages/index.tsx", "src/pages/settings.tsx")
    assert not covers("src/components", "src/pages/settings.tsx")


def test_glob_prediction_covers():
    assert covers("src/pages/*.tsx", "src/pages/settings.tsx")
    assert not covers("src/lib/*.ts", "src/pages/settings.tsx")


def test_grounded_rules():
    assert grounded("src/pages/settings.tsx", TREE)  # exact file
    assert grounded("src/pages", TREE)  # real directory (ancestor of entries)
    assert grounded("src/**/*.tsx", TREE)  # glob matching real entries
    assert not grounded("src/pages/settingsUtils.ts", TREE)  # fabricated file in a real dir
    assert not grounded("docs/guide.md", TREE)  # fabricated path entirely


def test_precision_recall_with_mixed_predictions():
    predictions = ["src/pages", "src/components/SettingsForm.tsx", "src/made_up.py"]
    labels = ["src/pages/settings.tsx", "src/components/SettingsForm.tsx"]
    precision, recall, hallucinated = file_precision_recall(predictions, labels, TREE)
    assert recall == 1.0
    assert precision == pytest.approx(2 / 3)
    assert hallucinated == ["src/made_up.py"]


def test_empty_predictions_zero_recall_none_precision():
    precision, recall, hallucinated = file_precision_recall([], ["src/lib/api.ts"], TREE)
    assert precision is None
    assert recall == 0.0
    assert hallucinated == []


def test_labels_required():
    with pytest.raises(ValueError):
        file_precision_recall(["src"], [], TREE)
