"""This job mints its own GitHub App installation token (SYSTEM_DESIGN.md §8: "execution-sandbox:
Firestore write + GitHub App token minting only") rather than being handed one by the
orchestrator — needs its own `secretAccessor` IAM grant on `github-app-private-key` only."""

from artisan_shared.github_auth import mint_installation_token

from artisan_execution_sandbox.config import (
    GITHUB_APP_ID,
    GITHUB_INSTALLATION_ID,
    SECRET_GITHUB_APP_PRIVATE_KEY,
)
from artisan_execution_sandbox.secrets import get_secret


async def get_installation_token() -> str:
    """Returns a raw, short-lived installation-token string for embedding in a `git push` URL.
    Never log this value."""
    private_key = get_secret(SECRET_GITHUB_APP_PRIVATE_KEY)
    return await mint_installation_token(
        app_id=GITHUB_APP_ID, installation_id=GITHUB_INSTALLATION_ID, private_key=private_key
    )
