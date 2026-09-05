"""Nightly feature export: normalizes raw rows and writes them to CSV."""

import csv


def normalize(rows: list[dict]) -> list[dict]:
    """Scales each row's `score` from 0-100 to 0-1."""
    return [{"id": row["id"], "score": row["score"] / 100} for row in rows]


def write_features(rows: list[dict], out_path: str) -> int:
    """Writes normalized feature rows to `out_path` as CSV. Returns the row count."""
    normalized = normalize(rows)
    with open(out_path, "a", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "score"])
        for row in normalized:
            writer.writerow([row["id"], row["score"]])
    return len(normalized)
