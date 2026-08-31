# --- Secrets Definitions ---

resource "google_secret_manager_secret" "github_app_private_key" {
  secret_id = "github-app-private-key"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "github_webhook_secret" {
  secret_id = "github-webhook-secret"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "jira_api_token" {
  secret_id = "jira-api-token"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "dashboard_oauth_client_id" {
  secret_id = "dashboard-oauth-client-id"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "dashboard_oauth_client_secret" {
  secret_id = "dashboard-oauth-client-secret"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "dashboard_auth_secret" {
  secret_id = "dashboard-auth-secret"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

# --- Scoped Secret Accessor IAM Bindings ---

# github-app-private-key -> orchestrator & execution-sandbox
resource "google_secret_manager_secret_iam_member" "github_app_private_key_orchestrator" {
  secret_id = google_secret_manager_secret.github_app_private_key.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}

resource "google_secret_manager_secret_iam_member" "github_app_private_key_sandbox" {
  secret_id = google_secret_manager_secret.github_app_private_key.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.execution_sandbox.email}"
}

# github-webhook-secret -> orchestrator
resource "google_secret_manager_secret_iam_member" "github_webhook_secret_orchestrator" {
  secret_id = google_secret_manager_secret.github_webhook_secret.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}

# jira-api-token -> orchestrator
resource "google_secret_manager_secret_iam_member" "jira_api_token_orchestrator" {
  secret_id = google_secret_manager_secret.jira_api_token.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}

# Dashboard secrets -> dashboard SA
resource "google_secret_manager_secret_iam_member" "dashboard_client_id" {
  secret_id = google_secret_manager_secret.dashboard_oauth_client_id.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dashboard.email}"
}

resource "google_secret_manager_secret_iam_member" "dashboard_client_secret" {
  secret_id = google_secret_manager_secret.dashboard_oauth_client_secret.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dashboard.email}"
}

resource "google_secret_manager_secret_iam_member" "dashboard_auth_secret" {
  secret_id = google_secret_manager_secret.dashboard_auth_secret.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dashboard.email}"
}
