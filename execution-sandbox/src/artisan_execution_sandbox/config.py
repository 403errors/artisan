"""Execution-sandbox-only config. Values shared with the orchestrator (pinned model id,
GCP/GitHub identifiers, event-log flag) live in `artisan_shared.config` and are re-exported here
so existing `artisan_execution_sandbox.config` imports keep working. Secrets are fetched by name
via artisan_shared.secrets at call time (never inlined)."""

import os

# Re-exports of the shared single source of truth (kept in `__all__` so they're explicit).
from artisan_shared.config import (
    CLOUD_RUN_REGION,
    EVENT_LOG_ENABLED,
    GCP_PROJECT_ID,
    GEMINI_MODEL_ID,
    GITHUB_APP_ID,
    GITHUB_INSTALLATION_ID,
    SECRET_GITHUB_APP_PRIVATE_KEY,
)

__all__ = [
    "CLOUD_RUN_REGION",
    "EVENT_LOG_ENABLED",
    "GCP_PROJECT_ID",
    "GEMINI_MODEL_ID",
    "GITHUB_APP_ID",
    "GITHUB_INSTALLATION_ID",
    "SECRET_GITHUB_APP_PRIVATE_KEY",
]

# Bounds the coding agent's tool-call loop so a stuck model can't run past the job's own Cloud Run
# Jobs execution timeout. Env-overridable: SWE-bench-scale repos need
# more exploration than the demo repos this default was tuned on — the bench runner sets 80 and
# records it in run_log, so bench-vs-production behavior differences stay visible.
MAX_CODING_AGENT_TOOL_CALLS = int(os.environ.get("ARTISAN_MAX_CODING_AGENT_TOOL_CALLS", "40"))

# v1 is scoped to exactly one fixed demo repo (docs/PRD.md §5), so a single configured test
# command is legitimate rather than building generic multi-language test detection.
DEMO_REPO_TEST_COMMAND = os.environ.get("ARTISAN_DEMO_REPO_TEST_COMMAND", "npm test")
