#!/usr/bin/env bash
# run_e2e.sh — one-command runner for the live E2E Gate 2 eval (test_e2e_eval.py).
#
# The harness makes LIVE Gemini calls (routing → experts → planning → coding → verification,
# several per scenario), so every run spends real API quota and takes ~25-30 min for the full
# 11-scenario pass. This script therefore preflights auth and asks for confirmation before
# running anything.
#
# Usage:
#   ./run_e2e.sh                      # full run, 1 rep per scenario (overwrites the committed
#                                     #   E2E_REPORT.md / e2e_results.json!)
#   ./run_e2e.sh -f FIXTURE[,FIXTURE] # only these fixtures (comma-separated, no spaces)
#   ./run_e2e.sh -t TAG               # tag outputs (E2E_REPORT.<tag>.md) so the committed
#                                     #   full-run record is never touched — use for shards
#   ./run_e2e.sh -r N                 # N reps per scenario (variance estimates; multiplies cost)
#   ./run_e2e.sh -y                   # skip the confirmation prompt (scripts/CI)
#   ./run_e2e.sh -l                   # list available fixtures and exit
#   ./run_e2e.sh merge TAG [TAG...]   # merge tagged shard reports into the untagged record
#   ./run_e2e.sh ... -- [PYTEST_ARGS] # anything after -- goes straight to pytest
#
# Env overrides (defaults shown):
#   GOOGLE_GENAI_USE_VERTEXAI=TRUE  GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai
#   GOOGLE_CLOUD_LOCATION=global
set -euo pipefail

EVALS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$EVALS_DIR/../.." && pwd)"

: "${GOOGLE_GENAI_USE_VERTEXAI:=TRUE}"
: "${GOOGLE_CLOUD_PROJECT:=artisan-multiagent-ai}"
: "${GOOGLE_CLOUD_LOCATION:=global}"
export GOOGLE_GENAI_USE_VERTEXAI GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_LOCATION

FIXTURES="" TAG="" REPS="" YES=0 PYTEST_EXTRA=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        merge)
            shift
            [[ $# -ge 1 ]] || { echo "merge needs at least one TAG" >&2; exit 2; }
            cd "$EVALS_DIR"
            exec uv run --package artisan-agents python merge_e2e_shards.py "$@"
            ;;
        -f|--fixtures) FIXTURES="$2"; shift 2 ;;
        -t|--tag)      TAG="$2"; shift 2 ;;
        -r|--reps)     REPS="$2"; shift 2 ;;
        -y|--yes)      YES=1; shift ;;
        -l|--list)
            echo "Available fixtures:"
            ls -d "$EVALS_DIR"/e2e_fixtures/*/ | xargs -n1 basename | sed 's/^/  /'
            exit 0
            ;;
        --) shift; PYTEST_EXTRA=("$@"); break ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
    esac
done

# Preflight: auth must be good before we burn quota on a run that dies at scenario 1.
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "ADC invalid — run: gcloud auth application-default login" >&2
    exit 1
fi

[[ -n "$FIXTURES" ]] && export ARTISAN_E2E_FIXTURES="$FIXTURES"
[[ -n "$TAG" ]]      && export ARTISAN_E2E_TAG="$TAG"
[[ -n "$REPS" ]]     && export ARTISAN_E2E_REPS="$REPS"

SCOPE="${FIXTURES:-all 11 scenarios}"
TARGET=$([[ -n "$TAG" ]] && echo "tagged shard '$TAG' (committed report untouched)" \
                         || echo "UNTAGGED — overwrites the committed E2E_REPORT.md")
echo "About to run the LIVE E2E eval: $SCOPE, reps ${REPS:-1}, $TARGET"
if [[ "$YES" -ne 1 ]]; then
    if [[ -t 0 ]]; then
        read -r -p "This makes live Gemini API calls. Proceed? [y/N] " reply
        [[ "$reply" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }
    else
        echo "non-interactive shell without -y — aborting" >&2
        exit 1
    fi
fi

cd "$REPO_ROOT"
exec uv run --package artisan-agents pytest agents/evals/test_e2e_eval.py -m eval -s "${PYTEST_EXTRA[@]}"
