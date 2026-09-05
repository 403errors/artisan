"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

import csv

from featurepipe.features import write_features

ROWS = [{"id": 1, "score": 80}, {"id": 2, "score": 95}]


def _read(out):
    with open(out) as handle:
        return list(csv.reader(handle))


def test_rerun_produces_identical_file(tmp_path):
    out = tmp_path / "features.csv"
    write_features(ROWS, str(out))
    first = _read(out)
    write_features(ROWS, str(out))  # re-run after "partial failure"
    assert _read(out) == first


def test_rerun_does_not_duplicate_rows_or_headers(tmp_path):
    out = tmp_path / "features.csv"
    for _ in range(3):
        write_features(ROWS, str(out))
    rows = _read(out)
    assert rows.count(["id", "score"]) == 1
    assert len(rows) == 3


def test_content_still_correct(tmp_path):
    out = tmp_path / "features.csv"
    write_features(ROWS, str(out))
    rows = _read(out)
    assert rows[1] == ["1", "0.8"]
    assert rows[2] == ["2", "0.95"]
