"""Secret Manager access, parameterized on project id so both `agents/` (fixed
`ARTISAN_GCP_PROJECT_ID`) and `execution-sandbox/` (its own env-driven project id) share the same
fetch logic instead of each re-implementing the Secret Manager client call. Per SYSTEM_DESIGN.md
§8 — no inline secrets, ever; every credential is fetched here by name at call time."""

from google.cloud import secretmanager


def fetch_secret(project_id: str, name: str, version: str = "latest") -> str:
    """Fetches a secret's payload from Secret Manager. Callers are expected to cache the result
    in-process (e.g. via `functools.lru_cache`) — secrets don't rotate mid-process, and repeated
    per-request fetches would add needless latency."""
    client = secretmanager.SecretManagerServiceClient()
    secret_path = client.secret_version_path(project_id, name, version)
    response = client.access_secret_version(name=secret_path)
    return response.payload.data.decode("utf-8")
