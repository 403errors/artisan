# execution-sandbox Cloud Run Job image (MILESTONE.md Phase 3.4). Multi-stage, uv-based build,
# mirroring agents/Dockerfile's shape (see that file's comments for why the build context must be
# the repo root, not execution-sandbox/, given the uv workspace path dependency on
# packages/artisan_shared):
#   docker build -f execution-sandbox/Dockerfile -t execution-sandbox .   (run from the repo root)
#   gcloud run jobs deploy execution-sandbox --image <pushed-image-tag> --region us-central1
#
# Needs `git` in the final image (unlike agents/, which only talks to GitHub over the REST API) —
# this job shells out to the real `git` CLI to clone/branch/commit/push (see git_ops.py).

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY execution-sandbox/pyproject.toml execution-sandbox/pyproject.toml
COPY packages/artisan_shared/pyproject.toml packages/artisan_shared/pyproject.toml
COPY packages/artisan_shared/src packages/artisan_shared/src
RUN uv sync --frozen --no-install-project --no-dev --package artisan-execution-sandbox

COPY execution-sandbox/src execution-sandbox/src
RUN uv sync --frozen --no-dev --package artisan-execution-sandbox

FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["artisan-execution-sandbox"]
