# Orchestrator Cloud Run service (MILESTONE.md Phase 2.1). Multi-stage, uv-based build.
#
# Sprint 3: agents/pyproject.toml has a `uv` workspace path dependency on
# packages/artisan_shared, so the build context must be the REPO ROOT, not agents/ — e.g.:
#   docker build -f agents/Dockerfile -t orchestrator .   (run from the repo root)
#   gcloud run deploy orchestrator --image <pushed-image-tag> --region us-central1

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/
WORKDIR /app

# Dependencies first, so third-party dependency layers cache independently of our own source
# changes. Note: packages/artisan_shared's *source* (not just its pyproject.toml) has to be
# present for this first `uv sync` too — it's a workspace-local dependency of artisan-agents, not
# a PyPI package, so `--no-install-project` (which only skips installing artisan-agents itself)
# doesn't defer building it. Verified against a local uv-sync simulation before relying on it here.
COPY pyproject.toml uv.lock ./
COPY agents/pyproject.toml agents/pyproject.toml
COPY packages/artisan_shared/pyproject.toml packages/artisan_shared/pyproject.toml
COPY packages/artisan_shared/src packages/artisan_shared/src
RUN uv sync --frozen --no-install-project --no-dev --package artisan-agents

COPY agents/src agents/src
RUN uv sync --frozen --no-dev --package artisan-agents

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080
CMD ["uvicorn", "artisan_agents.app:app", "--host", "0.0.0.0", "--port", "8080"]
