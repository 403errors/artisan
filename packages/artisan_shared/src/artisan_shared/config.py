"""Config constants shared by the orchestrator and execution-sandbox services.

Single source of truth for values both services must agree on: the pinned model id, deploy-time
GCP/GitHub identifiers, and the event-log kill switch. Service-specific settings stay in each
service's own config module. Per TECH_STACK.md: the model id is always pinned explicitly, never
a "latest" alias. Defaults match the provisioned identifiers (docs/CONTEXT.md "External Accounts
& Identifiers"); every env-driven value is overridable for local/dev/test.
"""

import os

GEMINI_MODEL_ID = "gemini-3.8-flash"

GCP_PROJECT_ID = os.environ.get("ARTISAN_GCP_PROJECT_ID", "artisan-multiagent-ai")
CLOUD_RUN_REGION = os.environ.get("ARTISAN_CLOUD_RUN_REGION", "us-central1")

GITHUB_APP_ID = os.environ.get("ARTISAN_GITHUB_APP_ID", "4744770")
GITHUB_INSTALLATION_ID = os.environ.get("ARTISAN_GITHUB_INSTALLATION_ID", "157129507")

# Secret Manager secret names (values fetched at call time, never inlined — SYSTEM_DESIGN.md §8).
SECRET_GITHUB_APP_PRIVATE_KEY = "github-app-private-key"

# Kill switch for the agent-execution event log — disableable without a redeploy since an audit
# log going wrong should never require pulling the whole service. Read independently by each
# service so they can still be disabled separately.
EVENT_LOG_ENABLED = os.environ.get("ARTISAN_EVENT_LOG_ENABLED", "true").lower() == "true"
