"""One-time frozen instance selection for the benchmark adapter (manual tool — never runs in CI).

    python agents/evals/bench/select_instances.py --all
    python agents/evals/bench/select_instances.py --benchmark swebench-verified
    HF_TOKEN=... python agents/evals/bench/select_instances.py --benchmark swebench-multilingual

Picks BENCH_SAMPLE_SIZE instances per benchmark with a pinned per-benchmark seed and writes the
FULL instance rows to selected/<benchmark>.json — frozen files are checked into git, so every
future bench run anywhere uses byte-identical problems. Re-running selection for a frozen
benchmark refuses unless --force is passed (protecting comparability across runs). SWE-bench-Live
is the designed exception: its selection is a dated snapshot ("frozen": false) and re-selecting
pulls the current live set — that benchmark exists to answer "does it generalize to issues
created after training cutoffs", which requires fresh problems.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hf_rows import GatedDatasetError, fetch_jsonl_tree, fetch_rows
from registry import BENCH_SAMPLE_SIZE, BENCHMARKS, SELECTION_SEED, Benchmark

SELECTED_DIR = Path(__file__).resolve().parent / "selected"


def _gradeable(instance: dict) -> bool:
    """Only instances the official harness can actually grade: a test patch and at least one
    fail-to-pass test. Ungradeable rows would silently deflate the resolution rate."""
    return bool(instance["test_patch"].strip()) and bool(instance["fail_to_pass"])


def select(benchmark: Benchmark, *, force: bool = False) -> dict:
    out_path = SELECTED_DIR / f"{benchmark.key}.json"
    if out_path.exists() and benchmark.frozen and not force:
        existing = json.loads(out_path.read_text())
        print(f"{benchmark.key}: already frozen ({existing['n']} instances) — skipping "
              "(pass --force to re-select and break comparability with prior runs)")
        return existing

    print(f"{benchmark.key}: fetching {benchmark.dataset} ({benchmark.split})...")
    if benchmark.fetcher == "jsonl_tree":
        raw_rows = fetch_jsonl_tree(benchmark.dataset)
    else:
        raw_rows = fetch_rows(benchmark.dataset, benchmark.config, benchmark.split)
    instances = [benchmark.normalize(row) for row in raw_rows]
    pool = sorted(
        {inst["instance_id"]: inst for inst in instances if _gradeable(inst)}.values(),
        key=lambda inst: inst["instance_id"],
    )
    if not pool:
        raise RuntimeError(f"{benchmark.key}: no gradeable instances found — schema drift?")

    rng = random.Random(f"{SELECTION_SEED}:{benchmark.key}")
    chosen = rng.sample(pool, min(BENCH_SAMPLE_SIZE, len(pool)))

    payload = {
        "benchmark": benchmark.key,
        "dataset": benchmark.dataset,
        "split": benchmark.split,
        "frozen": benchmark.frozen,
        "selection_seed": f"{SELECTION_SEED}:{benchmark.key}",
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "pool_size": len(pool),
        "n": len(chosen),
        "instances": sorted(chosen, key=lambda inst: inst["instance_id"]),
    }
    SELECTED_DIR.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1))
    print(f"{benchmark.key}: froze {len(chosen)}/{len(pool)} gradeable instances -> {out_path.name}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--benchmark", choices=sorted(BENCHMARKS))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    keys = sorted(BENCHMARKS) if args.all else [args.benchmark]
    failures = 0
    for key in keys:
        try:
            select(BENCHMARKS[key], force=args.force)
        except GatedDatasetError as exc:
            print(f"SKIPPED: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 — one benchmark's fetch failure must not stop
            failures += 1  # the others; reported loudly at the end
            print(f"FAILED {key}: {exc}", file=sys.stderr)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
