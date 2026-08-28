"""Shared GitHub App JWT -> installation-token client construction. Per TECH_STACK.md's
version-pin rules — no long-lived PAT anywhere, GitHub auth is always via the App's installation-
token flow. Used by both `agents/github/auth.py` (orchestrator, PR/comment operations) and
`execution-sandbox` (Sprint 3, needs its own installation token to push a branch — see
SYSTEM_DESIGN.md §8's "execution-sandbox: Firestore write + GitHub App token minting only")."""

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy


def build_installation_client(*, app_id: str, installation_id: str, private_key: str) -> GitHub:
    """A GitHub client authenticated as the App's installation on the target repo. `githubkit`
    mints and internally caches/refreshes the short-lived installation token, so callers never see
    or manage a raw JWT/token."""
    strategy = AppAuthStrategy(app_id=app_id, private_key=private_key).as_installation(
        int(installation_id)
    )
    return GitHub(strategy)


async def mint_installation_token(*, app_id: str, installation_id: str, private_key: str) -> str:
    """Returns the raw installation-token string (rather than a `GitHub` client), for the one case
    that needs it literally — `execution-sandbox` embeds it in a `git push` URL
    (`https://x-access-token:{token}@github.com/...`), which isn't a REST call `githubkit`'s
    `GitHub` client wrapper can make on its behalf. Short-lived (~1 hour); never log it."""
    strategy = AppAuthStrategy(app_id=app_id, private_key=private_key)
    async with GitHub(strategy) as gh:
        response = await gh.rest.apps.async_create_installation_access_token(int(installation_id))
        return response.parsed_data.token
