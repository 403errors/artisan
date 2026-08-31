# --- Orchestrator IAM ---
locals {
  orchestrator_roles = [
    "roles/datastore.user",
    "roles/pubsub.publisher",
    "roles/run.developer",
    "roles/aiplatform.user",
    "roles/cloudtrace.agent",
    "roles/iam.serviceAccountTokenCreator"
  ]
}

resource "google_project_iam_member" "orchestrator_roles" {
  for_each = toset(locals.orchestrator_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.orchestrator.email}"
}

# --- Execution Sandbox IAM ---
locals {
  execution_sandbox_roles = [
    "roles/datastore.user",
    "roles/aiplatform.user"
  ]
}

resource "google_project_iam_member" "execution_sandbox_roles" {
  for_each = toset(locals.execution_sandbox_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.execution_sandbox.email}"
}

# --- Dashboard IAM ---
resource "google_project_iam_member" "dashboard_datastore" {
  project = var.project_id
  role    = "roles/datastore.viewer"
  member  = "serviceAccount:${google_service_account.dashboard.email}"
}

# --- GitHub Actions Deployer IAM ---
locals {
  deployer_roles = [
    "roles/artifactregistry.writer",
    "roles/run.admin",
    "roles/iam.serviceAccountUser"
  ]
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset(locals.deployer_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.github_actions_deployer.email}"
}

# Allow Pub/Sub service agent to create tokens using the orchestrator SA for push auth
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.orchestrator.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
