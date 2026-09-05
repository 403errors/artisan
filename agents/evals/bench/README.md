# Artisan benchmark adapter

External, independent validation of the Artisan pipeline against public SWE benchmarks.
Everything here is **manual-only** — nothing runs in CI, every run spends real Gemini tokens.

## Benchmarks

| Key | Dataset | Frozen? | Language | Notes |
|---|---|---|---|---|
| `swebench-verified` | princeton-nlp/SWE-bench_Verified | ✅ 50 frozen | Python | The industry headline benchmark |
| `swebench-multilingual` | princeton-nlp/SWE-bench_Multilingual | ✅ 50 frozen | 9 languages | **Gated** — needs `HF_TOKEN` (see below) |
| `swebench-pro` | ScaleAI/SWE-bench_Pro | ✅ 50 frozen | Python+ | Harder, contamination-screened |
| `swebench-live` | SWE-bench-Live/SWE-bench-Live | ❌ dated snapshot | Python | Post-cutoff issues; re-freeze to refresh |
| `multi-swe-bench` | ByteDance-Seed/Multi-SWE-bench | ✅ 50 frozen | Java/TS/Go/Rust/… | JSONL-tree dataset (not /rows-indexed) |
| `swe-polybench` | AmazonScience/SWE-PolyBench_Verified | ✅ 50 frozen | Java/JS/TS/Python | Mixed task types (bug/feature/refactor) |

Frozen selections live in `selected/<key>.json` (checked into git, pinned seed — byte-identical
problems on every run). `swebench-live` is the designed exception: re-run its selection to pull
the current live set.

## Setup

1. **Gemini/Vertex**: `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`,
   `GOOGLE_CLOUD_LOCATION=global` in the environment.
2. **Docker**: must be running (`docker info`). Instance test environments come from the
   benchmarks' official images (pulled lazily, ~1–5 GB each). On Apple Silicon the x86_64
   images run under emulation — functional but slow.
3. **Gated datasets** (Multilingual): accept terms on the dataset's HF page, create a token at
   https://huggingface.co/settings/tokens, export `HF_TOKEN=...`.

## Workflow

```bash
# 1. Freeze instances (once per benchmark; already done for 5/6 — multilingual needs HF_TOKEN)
uv run --package artisan-agents python agents/evals/bench/select_instances.py --benchmark <key>

# 2. Smoke-test on 2 instances
uv run --package artisan-agents python agents/evals/bench/runner.py --benchmark <key> --limit 2

# 3. Full 50-instance run (resumable — re-running skips completed instance_ids)
uv run --package artisan-agents python agents/evals/bench/runner.py --benchmark <key>
```

Output in `bench_runs/<key>/`:
- `predictions.jsonl` — SWE-bench prediction format (`instance_id`, `model_name_or_path`,
  `model_patch`). This is the artifact the official harnesses grade.
- `run_log.json` — Artisan-internal detail per instance (routing domains, attempts, verdicts,
  terminal state, durations).

## What the runner measures (and what it doesn't)

The runner exercises the real Gate 2 pipeline end-to-end (routing → domain experts → planning →
coding agent → verification loop, capped at `--max-attempts`) with externals faked exactly like
the E2E mini-bench. The coding agent edits a host checkout at the instance's `base_commit`;
the pipeline's internal test signal runs in the benchmark's official container with the checkout
bind-mounted over `/testbed`.

**Oracle hygiene**: agents never see the test patch. The internal signal runs the *pre-patch*
versions of test files whose paths appear in the test patch (a dev running "tests near the
change") — paths only, never content. Final correctness is judged exclusively by the official
harness's hidden FAIL_TO_PASS/PASS_TO_PASS evaluation.

## Official grading (the credible number)

```bash
# SWE-bench family (Verified / Multilingual / Live)
python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified --split test \
    --predictions_path bench_runs/swebench-verified/predictions.jsonl \
    --max_workers 8 --run_id artisan-v2

# SWE-bench Pro — ScaleAI's fork: https://github.com/scaleapi/SWE-bench_Pro-os
# Multi-SWE-bench — https://github.com/multi-swe-bench/multi-swe-bench (per-language harness)
# SWE-PolyBench — https://github.com/AmazonScience/swe-bench-polybench
```

The harness-reported **resolved rate** is the headline external number. Combine with
`run_log.json` for Artisan-internal funnel metrics (routing accuracy, attempts, escalation).

## Status / follow-ups

- `multi-swe-bench`, `swe-polybench`: no prebuilt per-instance images — their harnesses build
  environments from per-instance Dockerfiles. `runner.py` raises with guidance for these;
  support is a follow-up (build images via their repos, then the same runner flow applies).
