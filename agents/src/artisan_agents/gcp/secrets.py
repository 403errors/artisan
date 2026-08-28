"""Secret Manager access. Per SYSTEM_DESIGN.md §8 — no inline secrets, ever; every credential is
fetched here by name at call time, never hardcoded or passed as a literal. The actual Secret
Manager call lives in `artisan_shared.secrets`, shared with `execution-sandbox` (Sprint 3) — this
module just binds it to the orchestrator's own project id and adds the in-process cache."""

from functools import lru_cache

from artisan_agents.config import GCP_PROJECT_ID
from artisan_shared.secrets import fetch_secret


@lru_cache(maxsize=None)
def get_secret(name: str, version: str = "latest") -> str:
    """Fetches a secret's payload from Secret Manager. Cached in-process per (name, version) —
    secrets don't rotate mid-process, and repeated per-request fetches would add needless
    latency to the webhook hot path."""
    return fetch_secret(GCP_PROJECT_ID, name, version)
