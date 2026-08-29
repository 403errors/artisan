"""GitHub App authentication. Per TECH_STACK.md version-pin rules — no long-lived PAT anywhere,
GitHub auth is always via the App's JWT -> installation-token flow. `githubkit`'s
`AppInstallationAuthStrategy` mints and caches the short-lived installation token internally, so
callers never see or manage a raw JWT/token. The actual client-construction logic lives in
`artisan_shared.github_auth`, shared with `execution-sandbox` (Sprint 3) — this module just binds
it to the orchestrator's own config/secrets."""

from functools import lru_cache

from artisan_shared.github_auth import build_installation_client
from githubkit import GitHub

from artisan_agents.config import (
    GITHUB_APP_ID,
    GITHUB_INSTALLATION_ID,
    SECRET_GITHUB_APP_PRIVATE_KEY,
)
from artisan_agents.gcp.secrets import get_secret


@lru_cache(maxsize=1)
def get_installation_client() -> GitHub:
    """A GitHub client authenticated as the App's installation on the target repo. Safe to reuse
    across requests — token refresh is handled internally by githubkit."""
    private_key = get_secret(SECRET_GITHUB_APP_PRIVATE_KEY)
    return build_installation_client(
        app_id=GITHUB_APP_ID, installation_id=GITHUB_INSTALLATION_ID, private_key=private_key
    )
