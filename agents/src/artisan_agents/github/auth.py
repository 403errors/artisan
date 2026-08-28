"""GitHub App authentication. Per TECH_STACK.md version-pin rules — no long-lived PAT anywhere,
GitHub auth is always via the App's JWT -> installation-token flow. `githubkit`'s
`AppInstallationAuthStrategy` mints and caches the short-lived installation token internally, so
callers never see or manage a raw JWT/token."""

from functools import lru_cache

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy

from artisan_agents.config import GITHUB_APP_ID, GITHUB_INSTALLATION_ID
from artisan_agents.gcp.secrets import get_secret


@lru_cache(maxsize=1)
def get_installation_client() -> GitHub:
    """A GitHub client authenticated as the App's installation on the target repo. Safe to reuse
    across requests — token refresh is handled internally by githubkit."""
    private_key = get_secret("github-app-private-key")
    strategy = AppAuthStrategy(app_id=GITHUB_APP_ID, private_key=private_key).as_installation(
        int(GITHUB_INSTALLATION_ID)
    )
    return GitHub(strategy)
