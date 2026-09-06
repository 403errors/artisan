"""Orchestrator-only config constants. Values shared with execution-sandbox (pinned model id,
GCP/GitHub identifiers, event-log flag) live in `artisan_shared.config` and are re-exported here
so existing `artisan_agents.config` imports keep working."""

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
# Manager, see gcp/secrets.py). Overridable via env for local/dev/test.
PUBSUB_TOPIC = os.environ.get("ARTISAN_PUBSUB_TOPIC", "artisan-github-events")
PUBSUB_PUSH_AUDIENCE = os.environ.get("ARTISAN_PUBSUB_PUSH_AUDIENCE", "")
# Direct Jira Cloud REST API access (see jira/client.py docstring for why this replaced
# mcp-atlassian: an unresolved auth bug in the pinned sooperset/mcp-atlassian:0.23.1 image itself).
JIRA_URL = os.environ.get("ARTISAN_JIRA_URL", "https://pieisnot22by7.atlassian.net")
JIRA_USERNAME = os.environ.get("ARTISAN_JIRA_USERNAME", "pieisnot22by7@gmail.com")
JIRA_PROJECT_KEY = os.environ.get("ARTISAN_JIRA_PROJECT_KEY", "ART")
# Gate 2: the execution-sandbox Cloud Run Job the orchestrator triggers per attempt.
EXECUTION_SANDBOX_JOB_NAME = os.environ.get("ARTISAN_EXECUTION_SANDBOX_JOB_NAME", "execution-sandbox")
# Gate 2 routing self-consistency: how many concurrent samples run_routing takes per decision;
# the majority-vote agreement becomes RoutingDecision.derived_confidence (the self-reported
# `confidence` is uncalibrated — see agents/evals/REPORT.md). Routing is a small classification
# prompt at temperature 0, so 3x cost is trivial next to planning; set 1 to disable.
ROUTING_SELF_CONSISTENCY = int(os.environ.get("ARTISAN_ROUTING_SELF_CONSISTENCY", "3"))

# Secret Manager secret names (values fetched at call time, never inlined — SYSTEM_DESIGN.md §8).
SECRET_GITHUB_WEBHOOK_SECRET = "github-webhook-secret"
SECRET_JIRA_API_TOKEN = "jira-api-token"
