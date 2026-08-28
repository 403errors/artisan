"""Pinned config constants. Per TECH_STACK.md: model id is always pinned explicitly, never a "latest" alias."""

import os

GEMINI_MODEL_ID = "gemini-3.7-flash"

# Caps enforced in Firestore (SYSTEM_DESIGN.md §7), mirrored here for agent-side reference only.
MAX_CLARIFICATION_ROUNDS = 3
MAX_EXECUTION_RETRIES = 3
MAX_TRIVIAL_CONFLICT_ATTEMPTS = 1

# Environment-driven settings — deploy-time identifiers, not secrets (those live in Secret
# Manager, see gcp/secrets.py). Defaults match the identifiers already provisioned in Sprint 1
# (docs/CONTEXT.md "External accounts & identifiers"), overridable via env for local/dev/test.
GCP_PROJECT_ID = os.environ.get("ARTISAN_GCP_PROJECT_ID", "artisan-multiagent-ai")
PUBSUB_TOPIC = os.environ.get("ARTISAN_PUBSUB_TOPIC", "artisan-github-events")
PUBSUB_PUSH_AUDIENCE = os.environ.get("ARTISAN_PUBSUB_PUSH_AUDIENCE", "")
MCP_ATLASSIAN_URL = os.environ.get("ARTISAN_MCP_ATLASSIAN_URL", "")
JIRA_PROJECT_KEY = os.environ.get("ARTISAN_JIRA_PROJECT_KEY", "ART")
GITHUB_APP_ID = os.environ.get("ARTISAN_GITHUB_APP_ID", "4744770")
GITHUB_INSTALLATION_ID = os.environ.get("ARTISAN_GITHUB_INSTALLATION_ID", "157129507")

# Secret Manager secret names (values fetched at call time, never inlined — SYSTEM_DESIGN.md §8).
SECRET_GITHUB_APP_PRIVATE_KEY = "github-app-private-key"
SECRET_GITHUB_WEBHOOK_SECRET = "github-webhook-secret"
SECRET_JIRA_API_TOKEN = "jira-api-token"
