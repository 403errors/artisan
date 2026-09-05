"""Pinned config + env-var-driven settings for the execution-sandbox job. Mirrors
agents/config.py's shape: deploy-time identifiers here, secrets fetched by name via
artisan_shared.secrets at call time (never inlined)."""

import os

GEMINI_MODEL_ID = "gemini-3.8-flash"

GCP_PROJECT_ID = os.environ.get("ARTISAN_GCP_PROJECT_ID", "artisan-multiagent-ai")
CLOUD_RUN_REGION = os.environ.get("ARTISAN_CLOUD_RUN_REGION", "us-central1")
GITHUB_APP_ID = os.environ.get("ARTISAN_GITHUB_APP_ID", "4744770")
GITHUB_INSTALLATION_ID = os.environ.get("ARTISAN_GITHUB_INSTALLATION_ID", "157129507")
SECRET_GITHUB_APP_PRIVATE_KEY = "github-app-private-key"

# Bounds the coding agent's tool-call loop so a stuck model can't run past the job's own Cloud Run
# Jobs execution timeout (MILESTONE.md Phase 3.4).
MAX_CODING_AGENT_TOOL_CALLS = 40

# v1 is scoped to exactly one fixed demo repo (docs/PRD.md §5), so a single configured test
# command is legitimate rather than building generic multi-language test detection.
DEMO_REPO_TEST_COMMAND = os.environ.get("ARTISAN_DEMO_REPO_TEST_COMMAND", "npm test")

# Kill switch for the agent-execution event log (Sprint 6) — mirrors agents/config.py's flag of
# the same name so both services can be disabled independently without a redeploy.
EVENT_LOG_ENABLED = os.environ.get("ARTISAN_EVENT_LOG_ENABLED", "true").lower() == "true"
