import csv

from featurepipe.features import normalize, write_features

ROWS = [{"id": 1, "score": 80}, {"id": 2, "score": 95}]


def test_normalize_scales_scores():
    assert normalize(ROWS) == [{"id": 1, "score": 0.8}, {"id": 2, "score": 0.95}]


def test_write_features_writes_header_and_rows(tmp_path):
    out = tmp_path / "features.csv"
    assert write_features(ROWS, str(out)) == 2
    with open(out) as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["id", "score"]
    assert len(rows) == 3
