"""Pinned config constants. Per TECH_STACK.md: model id is always pinned explicitly, never a "latest" alias."""

import os

GEMINI_MODEL_ID = "gemini-3.8-flash"

# Caps enforced in Firestore (SYSTEM_DESIGN.md §7), mirrored here for agent-side reference only.
MAX_CLARIFICATION_ROUNDS = 3
MAX_EXECUTION_RETRIES = 3
MAX_TRIVIAL_CONFLICT_ATTEMPTS = 1
# Gate 1 duplicate check (SYSTEM_DESIGN.md §3): how many open issues the GitHub Search API returns
# as keyword candidates, how many of those the Duplicate Detector Agent may flag as true
# duplicates, and how many follow-up "please confirm" comments Artisan posts when the issuer's
# reply to a duplicate flag is ambiguous.
DUPLICATE_SEARCH_LIMIT = 10
MAX_DUPLICATE_CANDIDATES = 5
MAX_DUPLICATE_FOLLOWUPS = 1
# A claimed-but-still-"in_progress" delivery older than this is assumed to belong to a Cloud Run
# instance that died mid-request (never reached the except/mark_delivery_failed path) and is
# reclaimable rather than blocking that delivery forever. Must stay longer than the orchestrator's
# own Cloud Run request timeout (3600s, its max — see docs/SYSTEM_DESIGN.md §7) so a claim only
# goes stale after the underlying request could no longer possibly still be legitimately running —
# 1800 would have been shorter than that timeout and reopened the exact race this guards against
# for a long-running attempt, so this must stay above 3600.
DELIVERY_CLAIM_STALE_AFTER_SECONDS = 4200

# Environment-driven settings — deploy-time identifiers, not secrets (those live in Secret
# Manager, see gcp/secrets.py). Defaults match the identifiers already provisioned in Sprint 1
# (docs/CONTEXT.md "External accounts & identifiers"), overridable via env for local/dev/test.
GCP_PROJECT_ID = os.environ.get("ARTISAN_GCP_PROJECT_ID", "artisan-multiagent-ai")
PUBSUB_TOPIC = os.environ.get("ARTISAN_PUBSUB_TOPIC", "artisan-github-events")
PUBSUB_PUSH_AUDIENCE = os.environ.get("ARTISAN_PUBSUB_PUSH_AUDIENCE", "")
# Direct Jira Cloud REST API access (see jira/client.py docstring for why this replaced
# mcp-atlassian: an unresolved auth bug in the pinned sooperset/mcp-atlassian:0.23.1 image itself).
JIRA_URL = os.environ.get("ARTISAN_JIRA_URL", "https://pieisnot22by7.atlassian.net")
JIRA_USERNAME = os.environ.get("ARTISAN_JIRA_USERNAME", "pieisnot22by7@gmail.com")
JIRA_PROJECT_KEY = os.environ.get("ARTISAN_JIRA_PROJECT_KEY", "ART")
GITHUB_APP_ID = os.environ.get("ARTISAN_GITHUB_APP_ID", "4744770")
GITHUB_INSTALLATION_ID = os.environ.get("ARTISAN_GITHUB_INSTALLATION_ID", "157129507")
# Gate 2 (Sprint 3): the execution-sandbox Cloud Run Job the orchestrator triggers per attempt.
CLOUD_RUN_REGION = os.environ.get("ARTISAN_CLOUD_RUN_REGION", "us-central1")
EXECUTION_SANDBOX_JOB_NAME = os.environ.get("ARTISAN_EXECUTION_SANDBOX_JOB_NAME", "execution-sandbox")

# Kill switch for the agent-execution event log (Sprint 6) — disableable without a redeploy since
# an audit log going wrong should never require pulling the whole service.
EVENT_LOG_ENABLED = os.environ.get("ARTISAN_EVENT_LOG_ENABLED", "true").lower() == "true"

# Secret Manager secret names (values fetched at call time, never inlined — SYSTEM_DESIGN.md §8).
SECRET_GITHUB_APP_PRIVATE_KEY = "github-app-private-key"
SECRET_GITHUB_WEBHOOK_SECRET = "github-webhook-secret"
SECRET_JIRA_API_TOKEN = "jira-api-token"
