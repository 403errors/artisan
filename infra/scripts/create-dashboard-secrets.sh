#!/usr/bin/env bash
# Creates the dashboard's GitHub OAuth App credentials in Secret Manager and grants
# dashboard@ scoped secretAccessor on each — closes the Sprint 6 Phase 6.3 audit gap
# (docs/SYSTEM_DESIGN.md §8): these three values previously lived only in
# dashboard/.env.local. Reads values from env vars so nothing gets committed.
#
# Usage:
#   GITHUB_ID=... GITHUB_SECRET=... AUTH_SECRET=... ./create-dashboard-secrets.sh [project_id]
set -euo pipefail

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
SA_EMAIL="dashboard@${PROJECT_ID}.iam.gserviceaccount.com"

: "${GITHUB_ID:?Set GITHUB_ID (dashboard OAuth App client id)}"
: "${GITHUB_SECRET:?Set GITHUB_SECRET (dashboard OAuth App client secret)}"
: "${AUTH_SECRET:?Set AUTH_SECRET (Auth.js session-signing secret)}"

# macOS ships bash 3.2 (no associative arrays), so pair names/values by index instead.
SECRET_NAMES=("dashboard-oauth-client-id" "dashboard-oauth-client-secret" "dashboard-auth-secret")
SECRET_VALUES=("$GITHUB_ID" "$GITHUB_SECRET" "$AUTH_SECRET")

for i in "${!SECRET_NAMES[@]}"; do
  name="${SECRET_NAMES[$i]}"
  value="${SECRET_VALUES[$i]}"

  if gcloud secrets describe "$name" --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "secret exists, adding new version: $name"
    printf '%s' "$value" | gcloud secrets versions add "$name" \
      --project="$PROJECT_ID" --data-file=-
  else
    echo "creating secret: $name"
    printf '%s' "$value" | gcloud secrets create "$name" \
      --project="$PROJECT_ID" --replication-policy=automatic --data-file=-
  fi

  echo "binding secretAccessor on $name to $SA_EMAIL"
  gcloud secrets add-iam-policy-binding "$name" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None >/dev/null
done

echo "done. dashboard@ has scoped secretAccessor on: ${SECRET_NAMES[*]}"
