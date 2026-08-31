# Dashboard Cloud Run service image (Sprint 5). Multi-stage Next.js build. The build context is
# the REPO ROOT — same convention as agents/Dockerfile and execution-sandbox/Dockerfile:
#   docker build -f dashboard/Dockerfile -t dashboard .   (run from the repo root)
#   gcloud run deploy dashboard --image <pushed-image-tag> --region us-central1
#
# Next.js standalone output (next.config.ts -> output: "standalone") keeps the runtime stage to a
# self-contained server + static assets. Server-runtime config (AUTH_SECRET, GITHUB_ID,
# GITHUB_SECRET, AUTH_TRUST_HOST, GOOGLE_CLOUD_PROJECT, ARTISAN_TARGET_REPO, ...) is supplied by
# Cloud Run at runtime — never baked in. Client-visible config (NEXT_PUBLIC_JIRA_SITE,
# NEXT_PUBLIC_GCP_PROJECT_ID) IS baked at `next build` time via the build args in the builder stage.

FROM node:22-alpine AS base
RUN corepack enable

# --- Dependencies (layer only changes when package.json / pnpm-lock.yaml change) ---
FROM base AS deps
WORKDIR /app
COPY dashboard/package.json dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- Build (plain `next build` so standalone output is guaranteed; dev/CI use --turbopack) ---
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY dashboard/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# Client-visible config is inlined into the browser bundle at `next build` — set these at build
# time with --build-arg (defaults match the v1 deployment). Server-runtime values are NOT set
# here; they come from Cloud Run at deploy time.
ARG NEXT_PUBLIC_JIRA_SITE=pieisnot22by7.atlassian.net
ARG NEXT_PUBLIC_GCP_PROJECT_ID=artisan-multiagent-ai
ENV NEXT_PUBLIC_JIRA_SITE=$NEXT_PUBLIC_JIRA_SITE \
    NEXT_PUBLIC_GCP_PROJECT_ID=$NEXT_PUBLIC_GCP_PROJECT_ID
RUN pnpm exec next build

# --- Runtime ---
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=8080
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 8080
CMD ["node", "server.js"]
