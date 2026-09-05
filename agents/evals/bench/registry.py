"""Registry of the external benchmarks Artisan can be run against (v2 eval wave).

Six independent benchmarks — every major public issue-resolution benchmark except SWE-bench
Lite (excluded: it's a subset of the same pool as Verified, and Verified is the better-curated
one). 50 instances per benchmark, randomly selected ONCE with a pinned seed and frozen into
selected/<name>.json (full instance rows, not just IDs — a frozen file is reproducible even if
the upstream dataset changes). SWE-bench-Live is the exception: it refreshes from live GitHub
activity by design, so its selection is a dated snapshot marked "frozen": false and re-running
selection pulls a fresh one.

Grading philosophy: Artisan only GENERATES patches (predictions.jsonl per benchmark). Scoring is
done by each benchmark's OWN official harness — never by our code — so the numbers are
externally credible. See README.md for the exact commands.
"""

import json
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Benchmark:
    key: str
    dataset: str  # HuggingFace dataset id
    config: str
    split: str
    frozen: bool  # False only for SWE-bench-Live (continuously refreshed upstream)
    gated: bool  # needs an HF token with accepted terms
    language: str  # "python" | "multi" — multi-language benchmarks need non-Python toolchains
    # "rows": datasets-server /rows API. "jsonl_tree": per-language JSONL files in the repo tree
    # (Multi-SWE-bench isn't indexed by the datasets-server — HTTP 500 on /rows).
    fetcher: str
    normalize: Callable[[dict], dict]  # raw dataset row -> canonical instance dict


def _as_list(value) -> list[str]:
    """FAIL_TO_PASS-style fields are JSON-encoded strings in some datasets, lists in others."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value.strip() else []
    if isinstance(value, dict):  # Multi-SWE-bench: {test_file: [test_methods]}
        return [f"{f}::{m}" for f, methods in value.items() for m in methods]
    return [str(v) for v in (value or [])]


def _canonical(row: dict, *, f2p_field: str, p2p_field: str, extra: dict | None = None) -> dict:
    return {
        "instance_id": str(row["instance_id"]),
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "problem_statement": row.get("problem_statement") or "",
        "test_patch": row.get("test_patch") or "",
        "fail_to_pass": _as_list(row.get(f2p_field)),
        "pass_to_pass": _as_list(row.get(p2p_field)),
        # Benchmark-specific extras the runner needs (Docker image tags, test commands).
        "extra": extra or {},
    }


def _norm_swebench(row: dict) -> dict:
    extra = {}
    if row.get("test_cmds"):  # SWE-bench-Live carries per-instance test commands
        extra["test_cmds"] = row["test_cmds"]
    return _canonical(row, f2p_field="FAIL_TO_PASS", p2p_field="PASS_TO_PASS", extra=extra)


def _norm_pro(row: dict) -> dict:
    return _canonical(
        row,
        f2p_field="fail_to_pass",
        p2p_field="pass_to_pass",
        extra={"dockerhub_tag": row.get("dockerhub_tag"), "repo_language": row.get("repo_language")},
    )


def _norm_polybench(row: dict) -> dict:
    return _canonical(
        row,
        f2p_field="F2P",
        p2p_field="P2P",
        extra={"test_command": row.get("test_command"), "language": row.get("language")},
    )


def _norm_multi_swe(row: dict) -> dict:
    # Two row shapes exist in the tree: most languages carry title/body + base.sha + instance_id;
    # kotlin rows LACK instance_id (synthesize org__repo-number); python rows use the SWE-bench
    # schema (problem_statement + base_commit at top level).
    problem = row.get("problem_statement") or ""
    if not problem:
        problem = row.get("title") or ""
        if row.get("body"):
            problem += f"\n\n{row['body']}"
    instance_id = row.get("instance_id") or f"{row['org']}__{row['repo']}-{row['number']}"
    base_commit = row.get("base_commit") or row["base"]["sha"]
    return {
        "instance_id": str(instance_id),
        "repo": f"{row['org']}/{row['repo']}",
        "base_commit": base_commit,
        "problem_statement": problem,
        "test_patch": row.get("test_patch") or "",
        "fail_to_pass": _as_list(row.get("f2p_tests") or row.get("FAIL_TO_PASS")),
        "pass_to_pass": _as_list(row.get("p2p_tests") or row.get("PASS_TO_PASS")),
        "extra": {"language": row.get("_language")},
    }


BENCHMARKS: dict[str, Benchmark] = {
    # The most-cited issue-resolution benchmark: 500 human-validated real GitHub issues
    # (Python). Saturating at the frontier, but the recognizable yardstick.
    "swebench-verified": Benchmark(
        key="swebench-verified",
        dataset="princeton-nlp/SWE-bench_Verified",
        config="default",
        split="test",
        frozen=True,
        gated=False,
        language="python",
        fetcher="rows",
        normalize=_norm_swebench,
    ),
    # Same methodology, 42 repos across 9 languages. GATED on HuggingFace — needs a token with
    # accepted terms before selection can run.
    "swebench-multilingual": Benchmark(
        key="swebench-multilingual",
        dataset="princeton-nlp/SWE-bench_Multilingual",
        config="default",
        split="test",
        frozen=True,
        gated=True,
        language="multi",
        fetcher="rows",
        normalize=_norm_swebench,
    ),
    # Scale AI's contamination-resistant benchmark (copyleft-licensed repos). The public test
    # split is the credible hard number; significantly more difficult than Verified.
    "swebench-pro": Benchmark(
        key="swebench-pro",
        dataset="ScaleAI/SWE-bench_Pro",
        config="default",
        split="test",
        frozen=True,
        gated=False,
        language="python",
        fetcher="rows",
        normalize=_norm_pro,
    ),
    # Continuously refreshed from live GitHub activity — contamination-proof by construction,
    # but NOT freezable: the selection is a dated snapshot and re-selecting pulls a fresh one.
    "swebench-live": Benchmark(
        key="swebench-live",
        dataset="SWE-bench-Live/SWE-bench-Live",
        config="default",
        split="verified",
        frozen=False,
        gated=False,
        language="python",
        fetcher="rows",
        normalize=_norm_swebench,
    ),
    # ByteDance's multilingual issue-resolution benchmark: 1,632 expert-annotated instances
    # across Java/TS/JS/Go/Rust/C/C++.
    "multi-swe-bench": Benchmark(
        key="multi-swe-bench",
        dataset="ByteDance-Seed/Multi-SWE-bench",
        config="default",
        split="train",
        frozen=True,
        gated=False,
        language="multi",
        fetcher="jsonl_tree",
        normalize=_norm_multi_swe,
    ),
    # Amazon's multi-language repo-level benchmark (Java/JS/TS/Python) — the Verified subset
    # (382 instances) is the curated one; covers bug fixes, features, and refactors.
    "swe-polybench": Benchmark(
        key="swe-polybench",
        dataset="AmazonScience/SWE-PolyBench_Verified",
        config="default",
        split="test",
        frozen=True,
        gated=False,
        language="multi",
        fetcher="rows",
        normalize=_norm_polybench,
    ),
}

#: Instances per benchmark, frozen at selection time.
BENCH_SAMPLE_SIZE = 50

#: Pinned seed for reproducible selection. One seed per benchmark (seed + key) so adding a
#: benchmark later never reshuffles existing selections.
SELECTION_SEED = 20260905
