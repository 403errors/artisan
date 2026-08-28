"""Secret Manager access. Per SYSTEM_DESIGN.md §8 — no inline secrets, ever; every credential is
fetched here by name at call time, never hardcoded or passed as a literal."""

from functools import lru_cache

from google.cloud import secretmanager

from artisan_agents.config import GCP_PROJECT_ID


@lru_cache(maxsize=None)
def get_secret(name: str, version: str = "latest") -> str:
    """Fetches a secret's payload from Secret Manager. Cached in-process per (name, version) —
    secrets don't rotate mid-process, and repeated per-request fetches would add needless
    latency to the webhook hot path."""
    client = secretmanager.SecretManagerServiceClient()
    secret_path = client.secret_version_path(GCP_PROJECT_ID, name, version)
    response = client.access_secret_version(name=secret_path)
    return response.payload.data.decode("utf-8")
