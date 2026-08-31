#!/usr/bin/env bash
# ==============================================================================
# Artisan — One-Command GCP Infrastructure Setup
#
# Idempotently provisions all external GCP prerequisites for Artisan:
# - Enables required APIs (Cloud Run, Pub/Sub, Firestore, Secret Manager, etc.)
# - Creates 4 least-privilege Service Accounts & assigns scoped IAM roles
# - Creates Pub/Sub topics (main + DLQ) and dead-lettering IAM bindings
# - Creates native Firestore database & composite indexes
# - Creates Secret Manager placeholders
# - Provisions Workload Identity Federation for GitHub Actions CI/CD
#
# Usage:
#   ./setup-gcp-infra.sh [PROJECT_ID] [REGION]
# ==============================================================================
set -euo pipefail

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null || echo 'artisan-multiagent-ai')}"
REGION="${2:-us-central1}"
REPO_OWNER="403errors"
REPO_NAME="artisan"

echo "=== Setting up Artisan GCP Infrastructure on project: ${PROJECT_ID} (${REGION}) ==="
gcloud config set project "$PROJECT_ID" --quiet

# 1. Enable Required APIs
echo "--> Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudbuild.googleapis.com

# 2. Create Service Accounts
echo "--> Creating Service Accounts..."
create_sa() {
  local sa_name="$1"
  local display_name="$2"
  if ! gcloud iam service-accounts describe "${sa_name}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$sa_name" --display-name="$display_name"
    echo "    Created SA: $sa_name"
  else
    echo "    SA already exists: $sa_name"
  fi
}

create_sa "orchestrator" "Artisan Orchestrator"
create_sa "execution-sandbox" "Artisan Execution Sandbox"
create_sa "dashboard" "Artisan Dashboard"
create_sa "github-actions-deployer" "GitHub Actions Deployer"

ORCHESTRATOR_SA="orchestrator@${PROJECT_ID}.iam.gserviceaccount.com"
SANDBOX_SA="execution-sandbox@${PROJECT_ID}.iam.gserviceaccount.com"
DASHBOARD_SA="dashboard@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_SA="github-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

# 3. Assign IAM Roles
echo "--> Assigning Least-Privilege IAM Roles..."

add_project_role() {
  local sa="$1"
  local role="$2"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${sa}" \
    --role="$role" \
    --condition=None >/dev/null
}

# Orchestrator
for role in roles/datastore.user roles/pubsub.publisher roles/run.developer roles/aiplatform.user roles/cloudtrace.agent roles/iam.serviceAccountTokenCreator; do
  add_project_role "$ORCHESTRATOR_SA" "$role"
done

# Execution Sandbox
for role in roles/datastore.user roles/aiplatform.user; do
  add_project_role "$SANDBOX_SA" "$role"
done

# Dashboard
add_project_role "$DASHBOARD_SA" "roles/datastore.viewer"

# GitHub Actions Deployer
for role in roles/artifactregistry.writer roles/run.admin roles/iam.serviceAccountUser; do
  add_project_role "$DEPLOYER_SA" "$role"
done

# Pub/Sub Token Creator on Orchestrator SA
gcloud iam service-accounts add-iam-policy-binding "$ORCHESTRATOR_SA" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --condition=None >/dev/null

# 4. Pub/Sub Topics & Permissions
echo "--> Creating Pub/Sub Topics..."
if ! gcloud pubsub topics describe "artisan-github-events-dlq" >/dev/null 2>&1; then
  gcloud pubsub topics create "artisan-github-events-dlq"
fi

if ! gcloud pubsub topics describe "artisan-github-events" >/dev/null 2>&1; then
  gcloud pubsub topics create "artisan-github-events"
fi

# Allow dashboard & orchestrator to publish to main topic
gcloud pubsub topics add-iam-policy-binding "artisan-github-events" \
  --member="serviceAccount:${DASHBOARD_SA}" --role="roles/pubsub.publisher" --condition=None >/dev/null
gcloud pubsub topics add-iam-policy-binding "artisan-github-events" \
  --member="serviceAccount:${ORCHESTRATOR_SA}" --role="roles/pubsub.publisher" --condition=None >/dev/null

# Allow Pub/Sub SA to publish to DLQ
gcloud pubsub topics add-iam-policy-binding "artisan-github-events-dlq" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" --role="roles/pubsub.publisher" --condition=None >/dev/null

# 5. Native Firestore Database & Indexes
echo "--> Verifying Firestore Native Database & Indexes..."
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --type=firestore-native
fi

# Composite Indexes (idempotent)
gcloud firestore indexes composite create \
  --collection-group=tickets \
  --field-config=field-path=github_repo,order=ascending \
  --field-config=field-path=updated_at,order=descending --quiet || true

gcloud firestore indexes composite create \
  --collection-group=tickets \
  --field-config=field-path=github_repo,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=updated_at,order=descending --quiet || true

# 6. Secret Manager Placeholders & Scoped Access
echo "--> Creating Secret Manager Placeholders & Permissions..."
create_secret_if_missing() {
  local secret_name="$1"
  if ! gcloud secrets describe "$secret_name" >/dev/null 2>&1; then
    gcloud secrets create "$secret_name" --replication-policy=automatic
    echo "    Created secret: $secret_name"
  fi
}

bind_secret_accessor() {
  local secret_name="$1"
  local sa="$2"
  gcloud secrets add-iam-policy-binding "$secret_name" \
    --member="serviceAccount:${sa}" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None >/dev/null
}

SECRETS=(
  "github-app-private-key"
  "github-webhook-secret"
  "jira-api-token"
  "dashboard-oauth-client-id"
  "dashboard-oauth-client-secret"
  "dashboard-auth-secret"
)

for s in "${SECRETS[@]}"; do
  create_secret_if_missing "$s"
done

# Scoped secretAccessor grants
bind_secret_accessor "github-app-private-key" "$ORCHESTRATOR_SA"
bind_secret_accessor "github-app-private-key" "$SANDBOX_SA"
bind_secret_accessor "github-webhook-secret" "$ORCHESTRATOR_SA"
bind_secret_accessor "jira-api-token" "$ORCHESTRATOR_SA"
bind_secret_accessor "dashboard-oauth-client-id" "$DASHBOARD_SA"
bind_secret_accessor "dashboard-oauth-client-secret" "$DASHBOARD_SA"
bind_secret_accessor "dashboard-auth-secret" "$DASHBOARD_SA"

# 7. Workload Identity Federation (WIF)
echo "--> Configuring Workload Identity Federation for GitHub Actions..."
if ! gcloud iam workload-identity-pools describe "github-actions" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "github-actions" \
    --location=global --display-name="GitHub Actions"
fi

WIP_ID="$(gcloud iam workload-identity-pools describe "github-actions" --location=global --format='value(name)')"

if ! gcloud iam workload-identity-pools providers describe "github" --location=global --workload-identity-pool="github-actions" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "github" \
    --location=global \
    --workload-identity-pool="github-actions" \
    --display-name="GitHub" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository_owner == '${REPO_OWNER}'" \
    --issuer-uri="https://token.actions.githubusercontent.com"
fi

gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIP_ID}/attribute.repository/${REPO_OWNER}/${REPO_NAME}" \
  --condition=None >/dev/null

echo "=== Infrastructure Setup Complete ==="
echo "Workload Identity Provider: ${WIP_ID}/providers/github"
echo "Deployer Service Account: ${DEPLOYER_SA}"
