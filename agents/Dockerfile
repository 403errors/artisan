# Orchestrator Cloud Run service (SPRINT.md Phase 2.1). Multi-stage, uv-based build — full IaC
# and CI/CD land in Sprint 7 (TECH_STACK.md); this is just "make it reachable" for Sprint 2's
# real-webhook DoD, the same minimal-deploy approach Sprint 1 used for mcp-atlassian.

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/
WORKDIR /app

# Dependencies first, so dependency layers cache independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080
CMD ["uvicorn", "artisan_agents.app:app", "--host", "0.0.0.0", "--port", "8080"]
