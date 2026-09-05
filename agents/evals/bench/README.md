# Artisan benchmark adapter

External, independent validation of the Artisan pipeline against public SWE benchmarks.
Everything here is **manual-only** — nothing runs in CI, every run spends real Gemini tokens.

## Benchmarks

| Key | Dataset | Frozen? | Language | Notes |
|---|---|---|---|---|
| `swebench-verified` | princeton-nlp/SWE-bench_Verified | ✅ 50 frozen | Python | The industry headline benchmark |
| `swebench-multilingual` | SWE-bench/SWE-bench_Multilingual | ✅ 50 frozen | 9 languages | Moved to the SWE-bench org — no longer gated |
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
3. **Gated datasets**: none currently — if a future benchmark gates, accept its terms on the HF
   page, create a token at https://huggingface.co/settings/tokens, export `HF_TOKEN=...`.

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

## Full runs (Phase 7 — manual, cost-bearing)

Each full run is 50 live pipeline executions (~4–8 h wall time per benchmark on Apple Silicon,
dominated by image pulls and amd64-under-Rosetta test runs; Gemini cost is real). Runs are
resumable — re-invoking the same command skips completed instances.

```bash
cd agents/evals/bench
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai \
       GOOGLE_CLOUD_LOCATION=global
for b in swebench-verified swebench-multilingual swebench-pro swebench-live multi-swe-bench swe-polybench; do
  uv run --package artisan-agents python runner.py --benchmark "$b" --max-attempts 2
done
```

Then grade with each benchmark's OFFICIAL harness (install it separately; point it at
`bench_runs/<benchmark>/predictions.jsonl`) and import the verdicts:

```bash
python bench_report.py --import-harness swebench-verified <harness-log-dir>   # per benchmark
python bench_report.py                                                      # renders BENCH_REPORT.md
```

## Reporting

```bash
# import the official harness's verdicts, then render BENCH_REPORT.md:
python agents/evals/bench/bench_report.py --import-harness swebench-verified logs/run_evaluation/artisan-v2
python agents/evals/bench/bench_report.py   # render (safe to re-run anytime)
```

`--import-harness` accepts a SWE-bench-style log tree (per-instance `report.json`) or a flat
`{"instance_id": bool}` JSON from the other harnesses. Ungraded benchmarks render as
"awaiting official harness" — Artisan never grades itself.

## Status / follow-ups

- All six benchmarks resolve prebuilt per-instance images (verified against the registries
  2026-09): SWE-bench family from Docker Hub (`swebench/` resp. `starryzhang/` for Live), Pro
  from `jefzda/sweap-images:<dockerhub_tag>`, PolyBench from GHCR
  (`timesler/swe-polybench.eval.x86_64.<id>:v1.1`, `:latest` fallback), Multi-SWE-bench from
  `mswebench/<org>_m_<repo>:pr-<n>` (container workdir `/home/<repo>`, not `/testbed`).
- First real runs should smoke with `--limit 1` per benchmark — image sizes are 1–5 GB each and
  amd64-under-Rosetta test runs are slow.
- The runner sets `ARTISAN_MAX_CODING_AGENT_TOOL_CALLS=80` (production default 40): real-scale
  repos need more exploration than the demo repos the default was tuned on — the first smoke run
  had an instance escalate at the cap. Recorded per-run; if 80 materially outperforms 40 that's
  evidence for raising the production default.
- Tests run by applying the agent's patch INSIDE the container over the image's own checkout
  (official-harness flow) — never bind-mounting the host checkout, which would hide in-image
  build artifacts (compiled extensions, e.g. astropy, fail to import under a bind mount).
- Coding-agent tool exceptions (e.g. a model-chosen pathological shell command) degrade to a
  failed attempt → retry/escalate, never a crashed instance.
