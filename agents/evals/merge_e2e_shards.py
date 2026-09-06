#!/usr/bin/env python3
"""Merge tagged E2E eval shards back into the untagged full-run record.

Parallel E2E validation runs are process-level shards (see test_e2e_eval.py's docstring): each
shard ran with ARTISAN_E2E_FIXTURES + ARTISAN_E2E_TAG and wrote a tagged `e2e_results.<tag>.json`
sidecar. Once every fixture is covered by exactly one shard, this script merges them and re-renders
the UNTAGGED `E2E_REPORT.md` / `e2e_results.json` that pipeline_report.py aggregates — so the record
run can be 3-4 parallel processes instead of one sequential multi-hour run.

Usage (from agents/evals/):

    uv run --package artisan-agents python merge_e2e_shards.py tag1 tag2 ...

Shards must be disjoint by fixture id and cover every fixture under e2e_fixtures/ — both are
checked, since a stale or overlapping shard would silently corrupt the headline metrics.
"""

import json
import sys
from pathlib import Path

from test_e2e_eval import FIXTURES_DIR, _build_report

HERE = Path(__file__).parent
UNTAGGED_REPORT = HERE / "E2E_REPORT.md"
UNTAGGED_SIDECAR = HERE / "e2e_results.json"


def main(tags: list[str]) -> None:
    if not tags:
        raise SystemExit("usage: merge_e2e_shards.py <tag> [<tag> ...]")

    results: list[dict] = []
    for tag in tags:
        shard_path = HERE / f"e2e_results.{tag}.json"
        if not shard_path.exists():
            raise SystemExit(f"missing shard sidecar: {shard_path}")
        results.extend(json.loads(shard_path.read_text())["per_scenario"])

    ids = [r["id"] for r in results]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SystemExit(f"shards overlap on fixtures (would double-count): {duplicates}")

    expected = sorted(
        d.name for d in FIXTURES_DIR.iterdir() if (d / "scenario.json").exists()
    )
    missing = sorted(set(expected) - set(ids))
    if missing:
        raise SystemExit(f"shards do not cover every fixture; missing: {missing}")

    report, sidecar = _build_report(results)
    UNTAGGED_REPORT.write_text(report)
    UNTAGGED_SIDECAR.write_text(json.dumps(sidecar, indent=2))
    print(f"merged {len(tags)} shards ({len(results)} scenario runs) -> {UNTAGGED_REPORT}")
    print(f"\n{report}")


if __name__ == "__main__":
    main(sys.argv[1:])
