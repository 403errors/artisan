# Dashboard Cloud Run service image (Sprint 5). Multi-stage Next.js build. The build context is
# the REPO ROOT — same convention as agents/Dockerfile and execution-sandbox/Dockerfile:
#   docker build -f dashboard/Dockerfile -t dashboard .   (run from the repo root)
#   gcloud run deploy dashboard --image <pushed-image-tag> --region us-central1
#
# Next.js standalone output (next.config.ts -> output: "standalone") keeps the runtime stage to a
# self-contained server + static assets. Runtime config (AUTH_SECRET, GITHUB_ID, GITHUB_SECRET,
# AUTH_TRUST_HOST, GOOGLE_CLOUD_PROJECT, ...) is supplied by Cloud Run at runtime — never baked in.

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
