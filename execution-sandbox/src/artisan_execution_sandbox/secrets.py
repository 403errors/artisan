"""Binds artisan_shared.secrets to this job's own project id. Per SYSTEM_DESIGN.md §8 — no
inline secrets, ever."""

from artisan_shared.secrets import fetch_secret

from artisan_execution_sandbox.config import GCP_PROJECT_ID


def get_secret(name: str, version: str = "latest") -> str:
    return fetch_secret(GCP_PROJECT_ID, name, version)
